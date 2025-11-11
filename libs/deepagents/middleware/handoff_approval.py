"""Middleware for handoff approval via HITL interrupts with iterative refinement.

Pattern Reference: Follows LangChain v1 Human-in-the-Loop pattern
https://langchain-ai.github.io/langgraph/how-tos/human-in-the-loop/add-human-in-the-loop/

Key Principles:
1. Use interrupt() to pause execution and wait for human input
2. Resume data becomes the return value of interrupt()
3. Support iterative refinement loop for summary improvement
4. Keep interrupt payloads simple and JSON-serializable
5. Validate resume data before using it
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from langsmith import traceable, Client


class HandoffState(AgentState):
    """Extended state schema for handoff middleware.

    Includes internal coordination fields for handoff proposal and approval flow.
    """

    _handoff_proposal: NotRequired[Annotated[dict[str, Any] | None, PrivateStateAttr]]
    handoff_decision: NotRequired[dict[str, Any] | None]
    handoff_approved: NotRequired[bool]


class HandoffApprovalMiddleware(AgentMiddleware[HandoffState]):
    """Middleware that emits interrupts for handoff approval with iterative refinement.

    Pattern Reference: Separation of concerns - HandoffSummarizationMiddleware
    generates initial summaries, this middleware handles HITL approval and refinement.
    https://langchain-ai.github.io/langgraph/how-tos/human-in-the-loop/add-human-in-the-loop/#approve-or-reject

    This middleware:
    1. Detects handoff proposals in state
    2. Calls interrupt() in a loop for human decision
    3. Supports iterative refinement: user can request summary regeneration with feedback
    4. Validates resume data
    5. Updates state with final decision

    Supported user actions:
    - approve: Accept the summary and proceed with handoff
    - refine: Request summary regeneration with feedback (requires model)
    - reject: Cancel the handoff
    """

    state_schema = HandoffState

    def __init__(self, model: BaseChatModel | str | None = None) -> None:
        """Initialize approval middleware.

        Args:
            model: Optional LLM for regenerating summaries during refinement.
                   If None, refinement requests will show an error.
        """
        super().__init__()
        self.model = model

    @traceable(name="handoff.approval.loop", tags=["middleware", "handoff"]) 
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Emit interrupt for handoff approval with iterative refinement loop.

        EXECUTION MODEL (CRITICAL):
        This node re-executes from LINE 1 on every interrupt() call:
        1. First execution: Runs until interrupt() raises GraphInterrupt. State checkpointed.
        2. Resume execution: Re-executes from LINE 1. interrupt() returns resume value.
        3. If refinement requested: Regenerates summary, loops back to interrupt()
        4. If approved/rejected: Returns state update and exits

        ALL CODE BEFORE interrupt() MUST BE IDEMPOTENT (safe to run multiple times).

        Pattern Reference: Iterative validation loop
        https://langchain-ai.github.io/langgraph/how-tos/human-in-the-loop/add-human-in-the-loop/#iterative-validation

        Metadata Emission:
        Emits observability metadata to LangSmith traces for each iteration:
        - handoff.iteration: Current refinement iteration number (0-indexed)
        - handoff.is_replay: Whether this is a replay from checkpoint (bool)
        - handoff.cache_hit: Whether cached summary was used vs LLM regeneration (bool)
        - handoff.refinement_count: Total number of cached refinements (int)
        - handoff.user_action: User's decision (approve/refine/reject) after interrupt
        - handoff.refinement_feedback: User's feedback text when action=refine

        Args:
            state: Current agent state
            runtime: Runtime context

        Returns:
            State update with final approval decision
        """
        import logging

        from langchain_core.callbacks.manager import get_callback_manager_for_config

        logger = logging.getLogger(__name__)

        # Check for proposal (idempotent - safe to run multiple times)
        proposal = state.get("_handoff_proposal")
        if not proposal:
            return None

        # Skip if already decided (idempotent)
        if state.get("handoff_decision") or state.get("handoff_approved"):
            return None

        # Validate proposal structure (idempotent)
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

        # Iterative refinement loop with caching optimization
        # Each iteration presents summary, waits for user decision
        # Loop continues until user approves or rejects

        # Initialize cache for O(N) performance instead of O(N²)
        # Cache persists across node re-executions (idempotent initialization)
        if "_refinement_cache" not in proposal:
            proposal["_refinement_cache"] = []
            proposal["_refinement_iteration"] = 0
            proposal["_refinement_waiting_for_resume"] = False

        proposal.setdefault("_refinement_waiting_for_resume", False)

        refinement_cache = proposal["_refinement_cache"]

        # Start with original summary or last cached iteration
        iteration = proposal["_refinement_iteration"]
        cache_hit = iteration < len(refinement_cache)
        if cache_hit:
            current_summary = refinement_cache[iteration]
        else:
            current_summary = proposal.get("summary_md", "")

        client = None
        try:
            client = Client()
        except Exception:
            client = None

        while True:
            # Refresh iteration to ensure metadata matches current state
            iteration = proposal["_refinement_iteration"]
            is_replay = bool(proposal.get("_refinement_waiting_for_resume", False))

            interrupt_metadata = {
                "iteration": iteration,
                "is_replay": is_replay,
                "cache_hit": cache_hit,
                "refinement_count": len(refinement_cache),
            }

            # Emit metadata to LangSmith trace for observability
            # Use inherit=False to scope metadata to this specific iteration
            config = getattr(runtime, "config", None)
            if config and (callbacks := config.get("callbacks")):
                try:
                    callback_manager = get_callback_manager_for_config(config)
                    if callback_manager:
                        callback_manager.add_metadata(
                            {
                                "handoff.iteration": iteration,
                                "handoff.is_replay": is_replay,
                                "handoff.cache_hit": cache_hit,
                                "handoff.refinement_count": len(refinement_cache),
                            },
                            inherit=False,
                        )
                except Exception as e:
                    logger.debug(f"Failed to emit metadata to LangSmith: {e}")

            # Build interrupt payload with current summary and observability metadata
            interrupt_payload = {
                "action": "approve_handoff",
                "summary": current_summary,
                "handoff_id": proposal.get("handoff_id", ""),
                "assistant_id": proposal.get("assistant_id", ""),
                "parent_thread_id": proposal.get("parent_thread_id", ""),
                "metadata": interrupt_metadata,
            }

            # Mark that we're awaiting resume so replays can be detected
            proposal["_refinement_waiting_for_resume"] = True

            # Create a child span for this approval iteration if client available
            if client is not None:
                iter_trace_ctx = client.trace(
                    name="handoff.approval.iteration",
                    tags=["middleware", "handoff"],
                    metadata={
                        "handoff.iteration": iteration,
                        "handoff.is_replay": is_replay,
                        "handoff.cache_hit": cache_hit,
                        "handoff.refinement_count": len(refinement_cache),
                    },
                )
            else:
                iter_trace_ctx = None

            if iter_trace_ctx is not None:
                with iter_trace_ctx as run:
                    # Wait for user decision - interrupt() returns resume data
                    resume_data = interrupt(interrupt_payload)
                    pass
            else:
                # Fallback: no explicit child span
                resume_data = interrupt(interrupt_payload)

            # Reset replay flag once resume data has been received
            proposal["_refinement_waiting_for_resume"] = False

            # Validate resume data
            if not isinstance(resume_data, dict):
                logger.warning(f"Invalid resume data type: {type(resume_data)}, defaulting to reject")
                resume_data = {"type": "reject"}

            # Extract action type
            action_type = resume_data.get("type", "reject")

            # Emit metadata for user action
            if config and (callbacks := config.get("callbacks")):
                try:
                    callback_manager = get_callback_manager_for_config(config)
                    if callback_manager:
                        user_action_metadata = {"handoff.user_action": action_type}
                        if action_type == "refine" and (feedback := resume_data.get("feedback")):
                            user_action_metadata["handoff.refinement_feedback"] = feedback[:200]  # Truncate
                        callback_manager.add_metadata(user_action_metadata, inherit=False)
                except Exception as e:
                    logger.debug(f"Failed to emit user action metadata: {e}")

            if action_type == "approve":
                # User approved - exit loop with approval
                logger.info("Handoff approved by user")
                # Clear cache for next handoff
                proposal["_refinement_cache"] = []
                proposal["_refinement_iteration"] = 0
                return {
                    "_handoff_proposal": None,
                    "handoff_decision": {
                        "type": "approve",
                        "approved": True,
                        "final_summary": current_summary,
                        "resume_data": resume_data,
                    },
                    "handoff_approved": True,
                }

            if action_type == "refine":
                # User wants refinement - regenerate summary with feedback
                feedback = resume_data.get("feedback", "")

                if not feedback:
                    logger.warning("Refinement requested but no feedback provided")
                    continue  # Loop again with same summary

                if not self.model:
                    logger.error("Refinement requested but no model available")
                    # Loop again with same summary (let user cancel or try again)
                    continue

                logger.info(f"Refining summary with feedback: {feedback[:100]}")

                # Increment iteration counter
                iteration += 1
                proposal["_refinement_iteration"] = iteration

                # Check cache before calling LLM (optimization for replays)
                if iteration < len(refinement_cache):
                    # Use cached summary from previous execution
                    current_summary = refinement_cache[iteration]
                    cache_hit = True
                    logger.info(f"Using cached summary for iteration {iteration}")

                    # Emit cache hit metadata
                    if config and (callbacks := config.get("callbacks")):
                        try:
                            callback_manager = get_callback_manager_for_config(config)
                            if callback_manager:
                                callback_manager.add_metadata(
                                    {"handoff.llm_regeneration": False, "handoff.cache_used": True},
                                    inherit=False,
                                )
                        except Exception as e:
                            logger.debug(f"Failed to emit cache metadata: {e}")
                else:
                    # Generate new summary and cache it
                    try:
                        # Emit LLM call metadata before regeneration
                        if config and (callbacks := config.get("callbacks")):
                            try:
                                callback_manager = get_callback_manager_for_config(config)
                                if callback_manager:
                                    callback_manager.add_metadata(
                                        {"handoff.llm_regeneration": True, "handoff.cache_used": False},
                                        inherit=False,
                                    )
                            except Exception as e:
                                logger.debug(f"Failed to emit LLM call metadata: {e}")

                        # Regenerate summary using LLM with user feedback
                        # This method now includes retry logic with exponential backoff
                        current_summary = self._regenerate_summary_with_feedback(
                            original_summary=current_summary,
                            feedback=feedback,
                            messages=state.get("messages", []),
                        )
                        # Cache the new summary for future replays
                        refinement_cache.append(current_summary)
                        cache_hit = False
                        logger.info(f"Cached new summary for iteration {iteration}")
                    except Exception as e:
                        logger.error(f"Failed to regenerate summary: {e}")
                        # Emit error metadata
                        if config and (callbacks := config.get("callbacks")):
                            try:
                                callback_manager = get_callback_manager_for_config(config)
                                if callback_manager:
                                    callback_manager.add_metadata(
                                        {"handoff.regeneration_error": str(e)[:200]},
                                        inherit=False,
                                    )
                            except Exception as meta_err:
                                logger.debug(f"Failed to emit error metadata: {meta_err}")
                        # Loop again with same summary (let user try again or cancel)
                        continue

                # Loop back to interrupt() with updated summary
                continue

            # reject or unknown
            # User rejected or invalid action - exit loop with rejection
            logger.info(f"Handoff rejected by user (action: {action_type})")
            return {
                "_handoff_proposal": None,
                "handoff_decision": {
                    "type": "reject",
                    "approved": False,
                    "message": resume_data.get("message", "Handoff rejected by user"),
                    "resume_data": resume_data,
                },
                "handoff_approved": False,
            }

    def _regenerate_summary_with_feedback(
        self,
        original_summary: str,
        feedback: str,
        messages: list[Any],
    ) -> str:
        """Regenerate handoff summary incorporating user feedback with retry logic.

        Implements exponential backoff retry strategy following LangChain patterns:
        - Max 3 retries (4 total attempts)
        - Initial delay: 1.0s
        - Backoff factor: 2.0 (1s, 2s, 4s)
        - Graceful fallback to original_summary on total failure

        Args:
            original_summary: The current summary markdown
            feedback: User's refinement instructions
            messages: Conversation history for context

        Returns:
            Regenerated summary markdown, or original_summary if all retries fail

        Raises:
            Exception: Never raises - always returns a valid summary
        """
        import logging
        import time

        # Import here to avoid circular dependency
        from langchain.chat_models import init_chat_model

        from deepagents.middleware.handoff_summarization import (
            _messages_to_prompt,
            _split_sentences,
            render_summary_markdown,
        )

        logger = logging.getLogger(__name__)

        # Ensure we have a model instance
        model = self.model
        if isinstance(model, str):
            model = init_chat_model(model)

        # Build refinement prompt
        messages_text = _messages_to_prompt(messages[-50:])  # Last 50 messages for context

        refinement_prompt = f"""You are refining a conversation handoff summary based on user feedback.

**Original Summary:**
{original_summary}

**User Feedback:**
{feedback}

**Recent Conversation Context (for reference):**
{messages_text}

**Instructions:**
- Refine the summary to incorporate the user's feedback
- Maintain the same format: title, TL;DR, and 3-5 bullet points
- Keep it concise (max 200 tokens)
- Focus on what matters for the next agent/thread to know

Generate the refined summary now:"""

        # Retry configuration following LangChain patterns
        max_retries = 3  # Total of 4 attempts (initial + 3 retries)
        initial_delay = 1.0  # seconds
        backoff_factor = 2.0

        # Attempt LLM invocation with exponential backoff
        for attempt in range(max_retries + 1):
            try:
                # Invoke LLM to regenerate
                response = model.invoke([HumanMessage(content=refinement_prompt)], max_tokens=200)

                # Extract refined text
                raw_content = getattr(response, "content", "")
                if isinstance(raw_content, list):
                    text_parts = [block.get("text", "") for block in raw_content if isinstance(block, dict)]
                    refined_text = "\n".join(part for part in text_parts if part).strip()
                else:
                    refined_text = str(raw_content or "").strip()

                if not refined_text:
                    # Empty response - fall back to original
                    logger.warning("LLM returned empty response, using original summary")
                    return original_summary

                # Reformat into structured markdown
                sentences = _split_sentences(refined_text)
                title = sentences[0][:120]
                tldr = sentences[0][:200]
                body = sentences[1:6] or sentences[:3]

                return render_summary_markdown(title, tldr, body)

            except Exception as e:
                # Log the error
                logger.warning(f"LLM invocation attempt {attempt + 1}/{max_retries + 1} failed: {e}")

                # If this was the last attempt, fall back to original
                if attempt >= max_retries:
                    logger.error(f"All {max_retries + 1} LLM invocation attempts failed. Falling back to original summary.")
                    return original_summary

                # Calculate exponential backoff delay
                delay = initial_delay * (backoff_factor**attempt)
                logger.info(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)

        # Should never reach here, but fallback just in case
        return original_summary


__all__ = ["HandoffApprovalMiddleware"]
