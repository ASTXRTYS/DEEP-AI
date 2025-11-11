"""Cleanup middleware for handoff summary blocks."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from langsmith import traceable

# Summary block markers (must match CLI persistence layer)
SUMMARY_START_TAG = "<current_thread_summary>"
SUMMARY_END_TAG = "</current_thread_summary>"
SUMMARY_PLACEHOLDER = "None recorded yet."


class HandoffCleanupMiddleware(AgentMiddleware):
    """Automatically clean up handoff summary after first turn in child thread.

    This middleware detects when a thread is a handoff child (via metadata)
    and clears the summary block from agent.md after the agent completes
    its first response. This prevents the summary from polluting future
    turns in the child thread.

    Uses after_agent hook to run cleanup after the agent has fully completed
    its response to the user.
    """

    def __init__(self) -> None:
        """Initialize cleanup middleware."""
        super().__init__()

    @traceable(name="handoff.cleanup", tags=["middleware", "handoff"]) 
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Clean up summary block if this is a handoff child's first turn.

        Args:
            state: Current agent state
            runtime: Runtime context

        Returns:
            State update marking cleanup done, or None if no cleanup needed
        """
        # Check if cleanup already done
        if state.get("_handoff_cleanup_done"):
            return None

        # Get thread metadata
        config = getattr(runtime, "config", {}) or {}
        metadata = dict(config.get("metadata") or {})
        handoff = metadata.get("handoff", {})

        # Check if this thread needs cleanup
        if not handoff.get("pending") or not handoff.get("cleanup_required"):
            return None

        # Trigger cleanup via state flag
        # Actual file writing is done by CLI (this middleware is platform-agnostic)
        # CLI watches for this flag and performs the file operation
        return {
            "_handoff_cleanup_pending": True,
            "_handoff_cleanup_done": True,
        }


__all__ = ["HandoffCleanupMiddleware"]
