"""Handoff summarization helpers and middleware."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, AgentState, PrivateStateAttr
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langgraph.runtime import Runtime

# Summarization configuration constants
# Based on Claude Sonnet 4 context window and typical conversation patterns
MAX_PROMPT_TOKENS = 4000  # Leave room for system prompt + summary generation prompt
MAX_SUMMARY_OUTPUT_TOKENS = 200  # Concise summaries (3-5 bullet points typical)
MAX_MESSAGES_TO_SCORE = 120  # Scan last ~120 messages for relevance scoring
MAX_TOOL_PAIR_LOOKBACK = 25  # Search up to 25 messages back for orphaned tool pairs


class HandoffState(AgentState):
    """Extended state schema for handoff middleware.

    Includes internal coordination fields for handoff proposal and approval flow.
    """

    _handoff_proposal: NotRequired[Annotated[dict[str, Any] | None, PrivateStateAttr]]
    handoff_decision: NotRequired[dict[str, Any] | None]
    handoff_approved: NotRequired[bool]


@dataclass
class HandoffSummary:
    """Structured representation of a handoff summary."""

    handoff_id: str
    summary_json: dict[str, Any]
    summary_md: str


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
        if hasattr(call, "id") and call.id == tool_call_id:
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
        has_pair = any(isinstance(candidate, AIMessage) and _ai_has_tool_call(candidate, tool_call_id) for candidate in window[:idx])
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
    return f"### Recent Thread Snapshot\n**Title:** {title.strip()}\n**TL;DR:** {tldr.strip()}\n\n#### Key Points\n" + "\n".join(bullet_lines) + "\n"


def generate_handoff_summary(
    *,
    model: BaseChatModel | str,
    messages: Sequence[BaseMessage],
    assistant_id: str,
    parent_thread_id: str,
) -> HandoffSummary:
    """Generate a structured handoff summary for the provided message history.

    Pattern Reference: Adapted from LangChain SummarizationMiddleware
    https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/middleware/summarization.py

    Args:
        model: LLM to use for summary generation
        messages: Conversation history to summarize
        assistant_id: ID of the current assistant
        parent_thread_id: Thread ID being handed off from

    Returns:
        HandoffSummary with structured JSON and markdown representations

    Raises:
        ValueError: If LLM invocation fails after retries
    """
    import logging
    from uuid import uuid4

    logger = logging.getLogger(__name__)
    llm = _ensure_model(model)

    selected = select_messages_for_summary(messages)
    trimmed = _trim_for_prompt(selected)
    prompt_messages = _messages_to_prompt(trimmed) if trimmed else "No recent conversation history."

    from langchain.agents.middleware.summarization import DEFAULT_SUMMARY_PROMPT

    # Add retry logic for LLM calls (Issue #3)
    max_retries = 2
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            response = llm.invoke(
                DEFAULT_SUMMARY_PROMPT.format(messages=prompt_messages),
                max_tokens=MAX_SUMMARY_OUTPUT_TOKENS,
            )
            break  # Success, exit retry loop
        except Exception as e:
            last_error = e
            logger.warning(f"LLM invocation failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt == max_retries:
                # Final attempt failed, raise with context
                raise ValueError(f"Failed to generate handoff summary after {max_retries + 1} attempts") from e

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


class HandoffSummarizationMiddleware(AgentMiddleware[HandoffState]):
    """Generate handoff summaries when request_handoff tool is called.

    Pattern Reference: Follows LangChain middleware pattern of separation of concerns.
    This middleware generates summaries, HandoffApprovalMiddleware handles HITL approval.
    https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/add-human-in-the-loop/

    This middleware:
    1. Detects request_handoff tool calls
    2. Generates structured summary using LLM
    3. Places summary in state for HandoffApprovalMiddleware to present

    State Keys (Issue #4):
    - _handoff_proposal: Internal state, summary awaiting approval
    - handoff_decision: Public API, final decision from user
    - handoff_approved: Public API, boolean approval status
    """

    state_schema = HandoffState

    def __init__(self, model: BaseChatModel | str) -> None:
        """Initialize summarization middleware.

        Args:
            model: Model to use for generating summaries (Claude Sonnet 4 recommended)
        """
        super().__init__()
        self.model = _ensure_model(model)

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Generate summary after model proposes handoff tool call.

        Pattern Reference: Generation-only, no interrupt(). HandoffApprovalMiddleware
        handles HITL approval using interrupt() per LangChain v1 pattern.
        https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/add-human-in-the-loop/

        Metadata Emission:
        Emits observability metadata to LangSmith traces:
        - handoff.summary_generation: Always true when this middleware generates a summary
        - handoff.summary_error: Error message if summary generation fails

        Args:
            state: Current agent state
            runtime: Runtime context

        Returns:
            State update with _handoff_proposal, or None if no handoff requested
        """
        import logging

        from langchain_core.callbacks.manager import get_callback_manager_for_config

        logger = logging.getLogger(__name__)

        # Check if handoff was requested
        if not self._handoff_requested(state):
            return None

        # Skip if proposal already generated (prevent duplicate summaries)
        if state.get("_handoff_proposal"):
            return None

        # Extract metadata
        config = getattr(runtime, "config", {}) or {}
        metadata = dict(config.get("metadata") or {})
        configurable = dict(config.get("configurable") or {})

        assistant_id = metadata.get("assistant_id") or metadata.get("assistant") or "agent"
        parent_thread_id = configurable.get("thread_id") or metadata.get("thread_id") or "unknown"
        preview_only = metadata.get("handoff_preview_only", False)

        # Generate summary using helper function with error handling
        messages = state.get("messages") or []

        # Emit metadata for summary generation
        config = getattr(runtime, "config", None)
        if config and (callbacks := config.get("callbacks")):
            try:
                callback_manager = get_callback_manager_for_config(config)
                if callback_manager:
                    callback_manager.add_metadata(
                        {"handoff.summary_generation": True},
                        inherit=False,
                    )
            except Exception as e:
                logger.debug(f"Failed to emit summary generation metadata: {e}")

        try:
            summary = generate_handoff_summary(
                model=self.model,
                messages=messages,
                assistant_id=assistant_id,
                parent_thread_id=parent_thread_id,
            )
        except Exception as e:
            logger.error(f"Failed to generate handoff summary: {e}")

            # Emit error metadata
            if config and (callbacks := config.get("callbacks")):
                try:
                    callback_manager = get_callback_manager_for_config(config)
                    if callback_manager:
                        callback_manager.add_metadata(
                            {"handoff.summary_error": str(e)[:200]},
                            inherit=False,
                        )
                except Exception as meta_err:
                    logger.debug(f"Failed to emit error metadata: {meta_err}")

            # Return error state instead of crashing
            return {
                "_handoff_proposal": None,
                "handoff_decision": {"type": "error", "error": str(e)},
                "handoff_approved": False,
            }

        # Build proposal dict with only serializable types
        proposal = {
            "summary_json": dict(summary.summary_json),  # Ensure plain dict
            "summary_md": str(summary.summary_md),
            "handoff_id": str(summary.handoff_id),
            "assistant_id": str(assistant_id),
            "parent_thread_id": str(parent_thread_id),
            "preview_only": bool(preview_only),
        }

        # Return proposal in state for HandoffApprovalMiddleware to present
        # (Issue #1: NO interrupt() here - that's HandoffApprovalMiddleware's job)
        return {"_handoff_proposal": proposal}

    def _handoff_requested(self, state: AgentState) -> bool:
        """Check if handoff was requested via tool call or state flag.

        Args:
            state: Current agent state

        Returns:
            True if handoff should be generated
        """
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
                # Tool calls are standardized dicts in LangChain v1
                if tc["name"] == "request_handoff":
                    return True

        return False


__all__ = [
    "HandoffSummarizationMiddleware",
    "HandoffSummary",
    "generate_handoff_summary",
    "render_summary_markdown",
    "select_messages_for_summary",
]
