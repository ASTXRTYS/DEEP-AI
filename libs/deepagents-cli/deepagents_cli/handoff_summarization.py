"""Thread handoff summarization for DeepAgents CLI.

This module provides specialized summarization prompts designed for thread handoffs,
distinct from the context compaction approach in LangChain's DEFAULT_SUMMARY_PROMPT.

Handoff summaries capture the immediate session context - what you were just working on
and where you're headed next - to maintain continuity when switching between threads.
They complement the three-layer memory system:
- Long-term memory (/memories/) - persists high-signal facts across all threads
- Handoff summaries - captures last few conversational turns for session continuity
- Checkpoints - full conversation state
"""

# Approach 1: Session Continuity Prompt
# Focuses on immediate context without invading agent's long-term memory
HANDOFF_SUMMARY_PROMPT = """<role>
Thread Handoff Assistant
</role>

<primary_objective>
Create a brief handoff summary capturing the immediate session context from the recent conversation turns below.
</primary_objective>

<context>
You are preparing a summary for when this conversation thread is resumed after the user has worked on other tasks.
This is NOT a comprehensive project summary - the agent has long-term memory (/memories/) for that.
Instead, focus on session continuity: what were we just doing, what's the immediate status, and what comes next?
</context>

<instructions>
Read the recent conversation turns carefully and create a concise handoff summary (150-200 words max) that answers:

1. **Current Objectives**: What specific task or goal were we actively working on?
   - Be concrete about the immediate focus, not the overall project

2. **Recent Accomplishments**: What did we just complete or make progress on?
   - Focus on the last few actions taken, not everything in the conversation
   - Mention specific files, functions, or features if relevant

3. **Next Steps**: What were we about to do next?
   - Capture the immediate next action or decision point
   - Note if waiting for user input or approval

4. **Blockers**: Are there any immediate issues blocking progress?
   - Only mention active blockers, not past issues already resolved
   - Note if investigation is needed

Format your response as a natural summary paragraph, not a rigid outline.
Use specific details (file names, function names, error messages) rather than vague descriptions.
Write as if you're briefing someone who needs to continue where you left off.

IMPORTANT: Respond ONLY with the handoff summary. No preamble, no meta-commentary.
</instructions>

<messages>
Recent conversation turns:
{messages}
</messages>"""


def get_handoff_prompt(version: str = "default") -> str:
    """Get the handoff summarization prompt.

    Args:
        version: Prompt version identifier. Currently only "default" (approach 1) is available.
            Reserved for future A/B testing with additional prompt variants.

    Returns:
        The handoff summarization prompt template string.

    Raises:
        ValueError: If an unknown version is requested.
    """
    if version == "default":
        return HANDOFF_SUMMARY_PROMPT

    msg = f"Unknown handoff prompt version: {version}"
    raise ValueError(msg)
