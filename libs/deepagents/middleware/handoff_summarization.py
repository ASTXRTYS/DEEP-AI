"""Handoff summarization helpers and middleware."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Iterable, Sequence

from langchain.agents.middleware.types import AgentMiddleware, AgentState
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
    """Middleware that emits handoff summaries when explicitly requested."""

    def __init__(
        self,
        model: BaseChatModel | str,
        *,
        summary_state_key: str = "handoff_proposal",
    ) -> None:
        super().__init__()
        self.model = _ensure_model(model)
        self.summary_state_key = summary_state_key

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        config = getattr(runtime, "config", {}) or {}
        configurable = dict(config.get("configurable") or {})
        metadata = dict(config.get("metadata") or {})
        should_summarize = configurable.pop("handoff_requested", False) or metadata.get(
            "handoff_requested", False
        )
        if not should_summarize:
            return None

        assistant_id = metadata.get("assistant_id") or metadata.get("assistant") or "agent"
        parent_thread_id = configurable.get("thread_id") or metadata.get("thread_id") or "unknown"

        messages: Sequence[BaseMessage] = state.get("messages") or []
        summary = generate_handoff_summary(
            model=self.model,
            messages=messages,
            assistant_id=assistant_id,
            parent_thread_id=parent_thread_id,
        )

        return {
            self.summary_state_key: {
                "summary_json": summary.summary_json,
                "summary_md": summary.summary_md,
                "handoff_id": summary.handoff_id,
                "assistant_id": assistant_id,
                "parent_thread_id": parent_thread_id,
            }
        }


__all__ = [
    "HandoffSummarizationMiddleware",
    "HandoffSummary",
    "generate_handoff_summary",
    "render_summary_markdown",
    "select_messages_for_summary",
]
