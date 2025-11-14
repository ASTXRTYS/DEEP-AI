"""Cleanup middleware for handoff summary blocks."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime

# Summary block markers (must match CLI persistence layer)
SUMMARY_START_TAG = "<current_thread_summary>"
SUMMARY_END_TAG = "</current_thread_summary>"
SUMMARY_PLACEHOLDER = "None recorded yet."


class HandoffCleanupMiddleware(AgentMiddleware):
    """Automatically clean up handoff summary after first turn in child thread.

    Threads annotate ``metadata["handoff"]`` using the canonical schema defined
    in :mod:`deepagents_cli.handoff_persistence`. The CLI marks child threads as
    ``pending=True``/``cleanup_required=True`` until their first response is
    streamed, at which point this middleware emits ephemeral flags signaling the
    CLI to clear ``agent.md`` and flip metadata to a finalized state.

    Uses ``after_agent`` to run cleanup after the agent has fully completed
    its response. The middleware itself stays platform-agnostic by only
    emitting the lightweight ``_handoff_cleanup_pending`` and
    ``_handoff_cleanup_done`` markers; out-of-band code performs filesystem
    writes and timestamp recording.
    """

    def __init__(self) -> None:
        """Initialize cleanup middleware."""
        super().__init__()

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
        handoff_state = dict(metadata.get("handoff") or {})
        pending = bool(handoff_state.get("pending"))
        cleanup_required = bool(handoff_state.get("cleanup_required"))

        # Check if this thread needs cleanup. Both flags must be true for a
        # single-shot cleanup. The CLI will flip them off after clearing.
        if not (pending and cleanup_required):
            return None

        # Trigger cleanup via state flag
        # Actual file writing is done by CLI (this middleware is platform-agnostic)
        # CLI watches for this flag and performs the file operation
        return {
            "_handoff_cleanup_pending": True,
            "_handoff_cleanup_done": True,
        }


__all__ = ["HandoffCleanupMiddleware"]
