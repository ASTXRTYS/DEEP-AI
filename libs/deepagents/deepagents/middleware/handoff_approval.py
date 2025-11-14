"""Deprecated middleware stub for handoff approval."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langgraph.runtime import Runtime


class HandoffApprovalMiddleware(AgentMiddleware):
    """Compatibility shim retained for backwards compatibility.

    Handoff approval interrupts are now emitted exclusively by
    :class:`HandoffSummarizationMiddleware`. This middleware remains as a no-op so
    existing configurations that still reference it continue to function without
    raising import errors.
    """

    def __init__(self) -> None:
        """Initialize approval middleware."""
        super().__init__()

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """No-op hook retained for compatibility."""
        return None


__all__ = ["HandoffApprovalMiddleware"]
