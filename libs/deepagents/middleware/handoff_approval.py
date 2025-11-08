"""Middleware responsible for emitting handoff approval interrupts."""

from __future__ import annotations

from typing import Any, Sequence

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from .handoff_summarization import generate_handoff_summary


class HandoffApprovalMiddleware(AgentMiddleware):
    """Emit an interrupt for the CLI (or any client) to review a handoff summary."""

    def __init__(
        self,
        *,
        summary_state_key: str = "handoff_proposal",
        action_name: str = "handoff_summary",
        model: BaseChatModel | str | None = None,
    ) -> None:
        super().__init__()
        self.summary_state_key = summary_state_key
        self.action_name = action_name
        self._model = self._ensure_model(model) if model else None

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        config = getattr(runtime, "config", {}) or {}
        configurable = dict(config.get("configurable") or {})
        metadata = dict(config.get("metadata") or {})
        proposal = state.get(self.summary_state_key)

        if not proposal:
            proposal = self._generate_proposal_if_requested(
                state=state,
                metadata=metadata,
                configurable=configurable,
            )
            if proposal:
                state[self.summary_state_key] = proposal

        if not proposal:
            return None

        action_request = {
            "name": self.action_name,
            "description": "Preview handoff summary for approval",
            "args": {
                "handoff_id": proposal.get("handoff_id"),
                "summary_json": proposal.get("summary_json"),
                "summary_md": proposal.get("summary_md"),
                "assistant_id": proposal.get("assistant_id"),
                "parent_thread_id": proposal.get("parent_thread_id"),
                "preview_only": metadata.get("handoff_preview_only", False),
            },
        }

        hitl_request = {
            "schema_version": 1,
            "middleware_source": type(self).__name__,
            "action_requests": [action_request],
            "review_configs": [
                {
                    "action_name": self.action_name,
                    "allowed_decisions": ["approve", "edit", "reject"],
                }
            ],
        }

        response = interrupt(hitl_request)
        decisions = response.get("decisions", []) if isinstance(response, dict) else []
        decision = decisions[0] if decisions else {"type": "reject"}

        return {
            self.summary_state_key: None,
            "handoff_decision": decision,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_model(model: BaseChatModel | str | None) -> BaseChatModel | None:
        if model is None:
            return None
        if isinstance(model, BaseChatModel):
            return model
        return init_chat_model(model)

    def _generate_proposal_if_requested(
        self,
        *,
        state: AgentState,
        metadata: dict[str, Any],
        configurable: dict[str, Any],
    ) -> dict[str, Any] | None:
        should_summarize = configurable.get("handoff_requested") or metadata.get("handoff_requested")
        if not should_summarize or self._model is None:
            return None

        assistant_id = metadata.get("assistant_id") or metadata.get("assistant") or "agent"
        parent_thread_id = configurable.get("thread_id") or metadata.get("thread_id") or "unknown"
        messages: Sequence[BaseMessage] = state.get("messages") or []

        summary = generate_handoff_summary(
            model=self._model,
            messages=messages,
            assistant_id=assistant_id,
            parent_thread_id=parent_thread_id,
        )

        return {
            "summary_json": summary.summary_json,
            "summary_md": summary.summary_md,
            "handoff_id": summary.handoff_id,
            "assistant_id": assistant_id,
            "parent_thread_id": parent_thread_id,
        }


__all__ = ["HandoffApprovalMiddleware"]
