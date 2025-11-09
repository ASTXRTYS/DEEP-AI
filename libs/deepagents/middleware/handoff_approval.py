"""Middleware for handoff approval via HITL interrupts."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from langgraph.types import interrupt


class HandoffApprovalMiddleware(AgentMiddleware):
    """Emit HITL interrupt for handoff approval.

    This middleware watches for handoff proposals in state and emits an
    interrupt to present the summary to the user for approval. It does NOT
    generate summaries (that's HandoffSummarizationMiddleware's job).

    Uses after_model hook to ensure the model has completed its response
    before presenting the approval decision.
    """

    def __init__(self) -> None:
        """Initialize approval middleware.

        Note: No model parameter - this middleware only handles approval,
        not summary generation.
        """
        super().__init__()

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Emit interrupt if handoff proposal exists and needs approval.

        Args:
            state: Current agent state
            runtime: Runtime context

        Returns:
            State update with handoff_decision, or None if no proposal
        """
        # Check for proposal
        proposal = state.get("handoff_proposal")
        if not proposal:
            return None

        # Skip if already approved
        if state.get("handoff_approved"):
            return None

        # Emit interrupt for HITL approval
        interrupt_payload = {
            "__interrupt__": {
                "schema_version": 1,
                "middleware_source": "HandoffApprovalMiddleware",
                "action_requests": [
                    {
                        "name": "handoff_summary",
                        "description": "Preview handoff summary for approval",
                        "args": proposal,
                    }
                ],
            }
        }

        # Wait for decision
        decision = interrupt(interrupt_payload)

        # Extract decision from response
        decisions = decision.get("decisions", []) if isinstance(decision, dict) else []
        user_decision = decisions[0] if decisions else {"type": "reject"}

        # Return decision in state
        return {
            "handoff_proposal": None,  # Clear proposal
            "handoff_decision": user_decision,
            "handoff_approved": user_decision.get("type") == "approve",
        }


__all__ = ["HandoffApprovalMiddleware"]
