"""Middleware for handoff approval via HITL interrupts."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from langgraph.types import interrupt


class HandoffApprovalMiddleware(AgentMiddleware):
    """Middleware that emits interrupts for handoff approval.

    This middleware runs after HandoffSummarizationMiddleware generates a proposal.
    It calls interrupt() to pause execution and wait for human decision.
    """

    def __init__(self) -> None:
        """Initialize approval middleware."""
        super().__init__()

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Emit interrupt for handoff approval.

        Per LangChain v1 HumanInTheLoopMiddleware pattern, call interrupt() directly
        in after_model to pause execution and wait for human decision.

        Args:
            state: Current agent state
            runtime: Runtime context

        Returns:
            State update with approval decision
        """
        # Check for proposal
        proposal = state.get("handoff_proposal")
        if not proposal:
            return None

        # Skip if already decided
        if state.get("handoff_decision") or state.get("handoff_approved"):
            return None

        # Emit interrupt for HITL approval
        interrupt_payload = {
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

        # Wait for decision - interrupt() returns the resume payload
        resume_data = interrupt(interrupt_payload)

        # Extract decision from response
        decisions = resume_data.get("decisions", []) if isinstance(resume_data, dict) else []
        user_decision = decisions[0] if decisions else {"type": "reject"}

        # Return decision in state
        return {
            "handoff_proposal": None,  # Clear proposal
            "handoff_decision": user_decision,
            "handoff_approved": user_decision.get("type") == "approve",
        }


__all__ = ["HandoffApprovalMiddleware"]
