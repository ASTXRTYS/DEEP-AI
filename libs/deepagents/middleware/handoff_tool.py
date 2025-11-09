"""Handoff tool middleware - provides request_handoff tool."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.tools import tool
from langgraph.runtime import Runtime


@tool
def request_handoff(preview_only: bool = False) -> dict[str, Any]:
    """Request a handoff summary to transition to a new thread.

    This tool triggers the handoff flow which:
    1. Generates a summary of the current conversation
    2. Presents it for human approval
    3. Creates a new child thread if approved

    Args:
        preview_only: If True, show preview without creating thread

    Returns:
        Dict with handoff_requested=True to trigger middleware pipeline
    """
    return {
        "handoff_requested": True,
        "preview_only": preview_only,
    }


class HandoffToolMiddleware(AgentMiddleware):
    """Middleware that provides the request_handoff tool to agents.

    This middleware adds a tool that agents can call to initiate a thread handoff.
    When called, it sets state flags that trigger the summarization and approval
    middleware downstream.
    """

    def __init__(self) -> None:
        super().__init__()
        # Tool is registered automatically via middleware.tools
        self.tools = [request_handoff]

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """No pre-processing needed - tool registration is automatic."""
        return None


__all__ = ["HandoffToolMiddleware", "request_handoff"]
