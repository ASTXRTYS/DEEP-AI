"""Middleware for handoff approval via HITL interrupts.

Pattern Reference: Follows LangChain v1 Human-in-the-Loop pattern
https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/add-human-in-the-loop/

Key Principles:
1. Use interrupt() to pause execution and wait for human input
2. Resume data becomes the return value of interrupt()
3. Keep interrupt payloads simple and JSON-serializable
4. Validate resume data before using it
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from langgraph.types import interrupt


class HandoffApprovalMiddleware(AgentMiddleware):
    """Middleware that emits interrupts for handoff approval.

    Pattern Reference: Separation of concerns - HandoffSummarizationMiddleware
    generates summaries, this middleware handles HITL approval.
    https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/add-human-in-the-loop/#approve-or-reject

    This middleware:
    1. Detects handoff proposals in state
    2. Calls interrupt() to pause for human decision
    3. Validates resume data
    4. Updates state with final decision
    """

    def __init__(self) -> None:
        """Initialize approval middleware."""
        super().__init__()

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Emit interrupt for handoff approval.

        Pattern Reference: Uses interrupt() per LangChain v1 HITL pattern
        https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/add-human-in-the-loop/#approve-or-reject

        Key Pattern Points:
        1. interrupt() pauses execution at this exact point
        2. Resume value from Command(resume=...) becomes return value of interrupt()
        3. Node restarts from beginning when resumed (this method re-executes)
        4. Simple, JSON-serializable payloads only

        Args:
            state: Current agent state
            runtime: Runtime context

        Returns:
            State update with approval decision
        """
        import logging

        logger = logging.getLogger(__name__)

        # Check for proposal (Issue #4: underscore prefix for internal state)
        proposal = state.get("_handoff_proposal")
        if not proposal:
            return None

        # Skip if already decided
        if state.get("handoff_decision") or state.get("handoff_approved"):
            return None

        # Validate proposal structure (Issue #3: validate before using)
        if not isinstance(proposal, dict):
            logger.error(f"Invalid handoff proposal type: {type(proposal)}")
            return {
                "_handoff_proposal": None,
                "handoff_decision": {"type": "error", "error": "Invalid proposal structure"},
                "handoff_approved": False,
            }

        required_keys = ["summary_md", "handoff_id", "assistant_id", "parent_thread_id"]
        missing_keys = [key for key in required_keys if key not in proposal]
        if missing_keys:
            logger.error(f"Handoff proposal missing required keys: {missing_keys}")
            return {
                "_handoff_proposal": None,
                "handoff_decision": {
                    "type": "error",
                    "error": f"Missing required keys: {missing_keys}",
                },
                "handoff_approved": False,
            }

        # Emit interrupt for HITL approval
        # Pattern: Simple payload with essential info for UI display
        interrupt_payload = {
            "action": "approve_handoff",
            "summary": proposal.get("summary_md", ""),
            "handoff_id": proposal.get("handoff_id", ""),
            "assistant_id": proposal.get("assistant_id", ""),
            "parent_thread_id": proposal.get("parent_thread_id", ""),
        }

        # Wait for decision - interrupt() returns the resume payload
        # Pattern Reference: https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/add-human-in-the-loop/#resuming-interrupts
        resume_data = interrupt(interrupt_payload)

        # Validate resume data (Issue #3: validate before accessing fields)
        if not isinstance(resume_data, dict):
            logger.warning(f"Invalid resume data type: {type(resume_data)}, defaulting to reject")
            resume_data = {"approved": False}

        # Extract decision with safe defaults
        approved = resume_data.get("approved", False)
        if not isinstance(approved, bool):
            logger.warning(f"Invalid approval type: {type(approved)}, defaulting to False")
            approved = False

        # Build decision dict
        user_decision = {
            "type": "approve" if approved else "reject",
            "approved": approved,
            "resume_data": resume_data,  # Preserve full resume data for debugging
        }

        # Return decision in state
        return {
            "_handoff_proposal": None,  # Clear internal proposal
            "handoff_decision": user_decision,  # Public API
            "handoff_approved": approved,  # Public API
        }


__all__ = ["HandoffApprovalMiddleware"]
