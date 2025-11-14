"""Handoff summarization helpers and middleware.

This module centralizes the schema used by the summarization middleware and
the CLI's Human-In-The-Loop UX so we do not accidentally fork the payload
format in multiple places.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Iterable, Sequence

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain.agents.middleware.human_in_the_loop import (
    ActionRequest,
    HITLRequest,
    ReviewConfig,
)
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langgraph.runtime import Runtime
from typing_extensions import Literal, NotRequired, TypedDict

HANDOFF_ACTION_NAME = "approve_handoff"

MAX_PROMPT_TOKENS = 4000
MAX_SUMMARY_OUTPUT_TOKENS = 200
MAX_MESSAGES_TO_SCORE = 120
MAX_TOOL_PAIR_LOOKBACK = 25


@dataclass
class HandoffSummary:
    """Structured representation of a handoff summary."""

    handoff_id: str
    summary_json: dict[str, Any]
    summary_md: str


class HandoffActionArgs(TypedDict):
    """Canonical args embedded inside the HITL ActionRequest."""

    handoff_id: str
    assistant_id: str
    parent_thread_id: str
    summary_json: dict[str, Any]
    summary_md: str
    preview_only: bool


class HandoffInterruptMetadata(TypedDict, total=False):
    """Metadata block provided alongside the HITL payload."""

    handoff: NotRequired[dict[str, Any]]
    handoff_id: NotRequired[str]
    parent_thread_id: NotRequired[str]


class HandoffDecisionRecord(TypedDict, total=False):
    """Normalized decision stored in agent state for downstream observers."""

    type: Literal["approve", "reject", "edit", "preview"]
    message: NotRequired[str]
    edited_action: NotRequired[ActionRequest]
    summary_json: NotRequired[dict[str, Any]]
    summary_md: NotRequired[str]
    feedback: NotRequired[str]
    handoff_id: NotRequired[str]
    assistant_id: NotRequired[str]
    parent_thread_id: NotRequired[str]
    preview_only: NotRequired[bool]


def _build_action_args(
    *,
    summary: HandoffSummary,
    assistant_id: str,
    parent_thread_id: str,
    preview_only: bool,
) -> HandoffActionArgs:
    return {
        "handoff_id": summary.handoff_id,
        "assistant_id": assistant_id,
        "parent_thread_id": parent_thread_id,
        "summary_json": dict(summary.summary_json),
        "summary_md": str(summary.summary_md),
        "preview_only": bool(preview_only),
    }


def _build_interrupt_metadata(args: HandoffActionArgs) -> HandoffInterruptMetadata:
    handoff_block = {
        "pending": True,
        "handoff_id": args["handoff_id"],
        "parent_thread_id": args["parent_thread_id"],
        "assistant_id": args["assistant_id"],
        "preview_only": args["preview_only"],
        "summary_title": args["summary_json"].get("title"),
    }
    return {
        "handoff": handoff_block,
        "handoff_id": args["handoff_id"],
        "parent_thread_id": args["parent_thread_id"],
    }


def _normalize_decision(
    resume_data: Any,
    action_args: HandoffActionArgs,
) -> HandoffDecisionRecord:
    """Return a sanitized decision record for downstream consumers."""

    normalized: HandoffDecisionRecord = {
        "type": "reject",
        "handoff_id": action_args["handoff_id"],
        "assistant_id": action_args["assistant_id"],
        "parent_thread_id": action_args["parent_thread_id"],
        "preview_only": action_args["preview_only"],
        "summary_json": deepcopy(action_args["summary_json"]),
        "summary_md": action_args["summary_md"],
    }

    if isinstance(resume_data, dict):
        decisions = resume_data.get("decisions") or []
        if decisions:
            raw = decisions[0]
            if isinstance(raw, dict):
                normalized.update({k: v for k, v in raw.items() if k not in {"edited_action"}})
                decision_type = str(raw.get("type") or "reject")
                normalized["type"] = decision_type

                edited_action = raw.get("edited_action") if decision_type == "edit" else None
                if isinstance(edited_action, dict):
                    args_override = edited_action.get("args")
                    if isinstance(args_override, dict):
                        overrides = dict(args_override)
                        summary_json_override = overrides.get("summary_json")
                        summary_md_override = overrides.get("summary_md")
                        if isinstance(summary_json_override, dict):
                            normalized["summary_json"] = dict(summary_json_override)
                        if isinstance(summary_md_override, str):
                            normalized["summary_md"] = summary_md_override
                        feedback_text = overrides.get("feedback")
                        if isinstance(feedback_text, str):
                            normalized["feedback"] = feedback_text
                    normalized["edited_action"] = {
                        "name": edited_action.get("name") or HANDOFF_ACTION_NAME,
                        "args": dict(edited_action.get("args") or {}),
                    }
                elif decision_type == "approve":
                    normalized.setdefault("summary_json", deepcopy(action_args["summary_json"]))
                    normalized.setdefault("summary_md", action_args["summary_md"])

    return normalized


def _ensure_model(model: BaseChatModel | str) -> BaseChatModel:
    if isinstance(model, str):
        return init_chat_model(model)
    return model


def _model_identifier(model: BaseChatModel | str) -> str:
    if isinstance(model, str):
        return model
    for attr in ("model_name", "model", "__class__"):
        value = getattr(model, attr, None)
        if isinstance(value, str):
            return value
        if hasattr(value, "__name__"):
            return value.__name__
    return "unknown-model"


def _messages_to_prompt(messages: Sequence[BaseMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        role = type(message).__name__.removesuffix("Message").lower()
        content = message.content
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts = [block.get("text", "") for block in content if isinstance(block, dict)]
            text = "\n".join(part for part in parts if part)
        else:
            text = str(content)
        lines.append(f"[{role}] {text}")
    return "\n".join(lines)


def _ai_has_tool_call(ai_message: AIMessage, tool_call_id: str | None) -> bool:
    if not tool_call_id:
        return False
    tool_calls = getattr(ai_message, "tool_calls", None) or []
    for call in tool_calls:
        if isinstance(call, dict) and call.get("id") == tool_call_id:
            return True
        if hasattr(call, "id") and getattr(call, "id") == tool_call_id:
            return True
    return False


def select_messages_for_summary(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Select a high-signal window of messages for summarization."""

    if not messages:
        return []

    start_index = max(0, len(messages) - MAX_MESSAGES_TO_SCORE)
    window = list(messages[start_index:])

    missing_pairs: list[tuple[int, BaseMessage]] = []
    for idx, msg in enumerate(window):
        if not isinstance(msg, ToolMessage):
            continue
        tool_call_id = getattr(msg, "tool_call_id", None)
        if tool_call_id is None:
            continue
        has_pair = any(
            isinstance(candidate, AIMessage) and _ai_has_tool_call(candidate, tool_call_id)
            for candidate in window[:idx]
        )
        if has_pair:
            continue
        search_upper = max(0, start_index - MAX_TOOL_PAIR_LOOKBACK)
        for src_index in range(start_index - 1, search_upper - 1, -1):
            candidate = messages[src_index]
            if isinstance(candidate, AIMessage) and _ai_has_tool_call(candidate, tool_call_id):
                missing_pairs.append((src_index, candidate))
                break

    if missing_pairs:
        missing_pairs.sort(key=lambda item: item[0])
        window = [msg for _, msg in missing_pairs] + window

    return window


def _trim_for_prompt(messages: list[BaseMessage]) -> list[BaseMessage]:
    if not messages:
        return []
    try:
        return trim_messages(
            messages,
            max_tokens=MAX_PROMPT_TOKENS,
            token_counter=count_tokens_approximately,
            start_on="human",
            strategy="last",
            allow_partial=True,
            include_system=True,
        )
    except Exception:  # pragma: no cover - defensive fallback
        return messages[-25:]


def _split_sentences(text: str) -> list[str]:
    pieces = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]
    return pieces or [text.strip() or "Summary unavailable."]


def render_summary_markdown(title: str, tldr: str, body: Iterable[str]) -> str:
    bullet_lines = [f"- {line.strip()}" for line in body if line.strip()]
    if not bullet_lines:
        bullet_lines = ["- Additional details pending."]
    return (
        "### Recent Thread Snapshot\n"
        f"**Title:** {title.strip()}\n"
        f"**TL;DR:** {tldr.strip()}\n\n"
        "#### Key Points\n"
        + "\n".join(bullet_lines)
        + "\n"
    )


def generate_handoff_summary(
    *,
    model: BaseChatModel | str,
    messages: Sequence[BaseMessage],
    assistant_id: str,
    parent_thread_id: str,
) -> HandoffSummary:
    """Generate a structured handoff summary for the provided message history."""

    from uuid import uuid4

    llm = _ensure_model(model)

    selected = select_messages_for_summary(messages)
    trimmed = _trim_for_prompt(selected)
    prompt_messages = _messages_to_prompt(trimmed) if trimmed else "No recent conversation history."

    from langchain.agents.middleware.summarization import DEFAULT_SUMMARY_PROMPT

    response = llm.invoke(
        DEFAULT_SUMMARY_PROMPT.format(messages=prompt_messages),
        max_tokens=MAX_SUMMARY_OUTPUT_TOKENS,
    )

    raw_content = getattr(response, "content", "")
    if isinstance(raw_content, list):
        text_parts = [block.get("text", "") for block in raw_content if isinstance(block, dict)]
        summary_text = "\n".join(part for part in text_parts if part).strip()
    else:
        summary_text = str(raw_content or "").strip()

    if not summary_text:
        summary_text = "Summary unavailable. No content was returned by the model."

    sentences = _split_sentences(summary_text)
    title = sentences[0][:120]
    tldr = sentences[0][:200]
    body = sentences[1:6] or sentences[:3]

    usage = getattr(response, "usage_metadata", {}) or {}
    tokens_used = usage.get("output_tokens") or usage.get("total_tokens") or 0

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    handoff_id = str(uuid4())
    summary_md = render_summary_markdown(title, tldr, body)
    summary_json = {
        "schema_version": 1,
        "handoff_id": handoff_id,
        "assistant_id": assistant_id,
        "parent_thread_id": parent_thread_id,
        "child_thread_id": None,
        "title": title,
        "body": body,
        "tldr": tldr,
        "model": _model_identifier(model),
        "tokens_used": tokens_used,
        "created_at": now,
    }

    return HandoffSummary(handoff_id=handoff_id, summary_json=summary_json, summary_md=summary_md)


class HandoffSummarizationMiddleware(AgentMiddleware):
    """Generate summaries and emit the canonical handoff HITL payload.

    Responsibilities:
    * Detect ``request_handoff`` tool usage (state flag or tool inspection).
    * Summarize the recent conversation when a handoff is requested.
    * Emit :func:`langgraph.types.interrupt` with an ``ActionRequest`` that
      uses :class:`HandoffActionArgs` so the CLI can render the UX.
    * Normalize the HITL resume data into ``handoff_decision`` /
      ``handoff_approved`` state entries.

    By keeping the payload contract here the CLI (and any other client) can
    reason about the exact schema without duplicating serialization logic.

    State flags:
    - ``handoff_requested``: Latched by the request_handoff tool. Cleared once
      this middleware receives a decision so new handoffs must opt in again.
    - ``handoff_decision``: Dict describing the human decision returned from
      the interrupt (type, optional edits, metadata).
    - ``handoff_approved``: Convenience boolean derived from the decision.
    """

    def __init__(self, model: BaseChatModel | str) -> None:
        """Initialize summarization middleware.

        Args:
            model: Model to use for generating summaries
        """
        super().__init__()
        self.model = _ensure_model(model)

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Generate summary after model proposes handoff tool call.

        Runs in after_model to ensure tool call is detected in the same phase
        as HandoffToolMiddleware sets the state flag. The only cross-phase
        contract we maintain is the minimal set of state flags documented in
        issue #91 (handoff_requested, handoff_decision, handoff_approved).

        Args:
            state: Current agent state
            runtime: Runtime context

        Returns:
            State update with the user's decision, or None if no handoff was
            requested in this turn.
        """
        # Check if handoff was requested
        if not self._handoff_requested(state):
            return None

        # Extract metadata
        config = getattr(runtime, "config", {}) or {}
        metadata = dict(config.get("metadata") or {})
        configurable = dict(config.get("configurable") or {})

        assistant_id = metadata.get("assistant_id") or metadata.get("assistant") or "agent"
        parent_thread_id = configurable.get("thread_id") or metadata.get("thread_id") or "unknown"
        preview_only = bool(
            metadata.get("handoff_preview_only")
            or metadata.get("handoff", {}).get("preview_only")
            or state.get("preview_only")
        )

        # Generate summary using helper function
        messages = state.get("messages") or []
        summary = generate_handoff_summary(
            model=self.model,
            messages=messages,
            assistant_id=assistant_id,
            parent_thread_id=parent_thread_id,
        )

        action_args = _build_action_args(
            summary=summary,
            assistant_id=str(assistant_id),
            parent_thread_id=str(parent_thread_id),
            preview_only=preview_only,
        )

        action_request: ActionRequest = {
            "name": HANDOFF_ACTION_NAME,
            "description": "Review and approve the generated handoff summary.",
            "args": action_args,
        }

        review_config: ReviewConfig = {
            "action_name": HANDOFF_ACTION_NAME,
            "allowed_decisions": ["approve", "reject", "edit", "preview"],
        }

        hitl_request: HITLRequest = {
            "action_requests": [action_request],
            "review_configs": [review_config],
        }

        # Import interrupt here to avoid circular deps
        from langgraph.types import interrupt

        request_metadata = _build_interrupt_metadata(action_args)

        interrupt_payload: dict[str, Any] = {
            **hitl_request,
            "schema_version": 1,
            "middleware_source": "HandoffSummarizationMiddleware",
            "action": HANDOFF_ACTION_NAME,
            "handoff_id": action_args["handoff_id"],
            "assistant_id": action_args["assistant_id"],
            "parent_thread_id": action_args["parent_thread_id"],
            "summary_json": action_args["summary_json"],
            "summary": action_args["summary_md"],
            "preview_only": action_args["preview_only"],
            "metadata": request_metadata,
        }

        # Wait for human decision
        resume_data = interrupt(interrupt_payload)

        decision_record = _normalize_decision(resume_data, action_args)
        approved = decision_record.get("type") == "approve"

        return {
            # Clear the request flag once we have a final decision so future
            # handoff attempts explicitly set it again via the tool.
            "handoff_requested": False,
            "handoff_decision": dict(decision_record),
            "handoff_approved": approved,
        }

    def _handoff_requested(self, state: AgentState) -> bool:
        """Check if handoff was requested via tool call or state flag."""

        # Check for explicit state flag
        if state.get("handoff_requested"):
            return True

        # Check if last message was request_handoff tool call
        messages = state.get("messages", [])
        if not messages:
            return False

        last_msg = messages[-1]

        # Check for tool calls in AIMessage
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                # Handle both dict and object formats
                tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if tool_name == "request_handoff":
                    return True

        return False


__all__ = [
    "HANDOFF_ACTION_NAME",
    "HandoffActionArgs",
    "HandoffDecisionRecord",
    "HandoffSummarizationMiddleware",
    "HandoffSummary",
    "generate_handoff_summary",
    "render_summary_markdown",
    "select_messages_for_summary",
]
