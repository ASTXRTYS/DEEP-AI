I’ll base the design doc explicitly on the three DeepWiki Q&A files you created (T1, T2, T3) plus the current handoff implementation. Then I’ll propose a short design doc you can drop into the repo, followed by three concrete GitHub issue drafts. For each issue I’ll also sketch high‑signal “Questions for DeepWiki” sections that reference the design doc, so future contributors know what to ask if they need to go deeper.

Yes, I’ll treat [T1](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/T1:0:0-0:0), [T2](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/T2:0:0-0:0), and [T3](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/T3:0:0-0:0) as the primary source references plus the current handoff code. Below is:

1. A **design doc draft** you can drop into `docs/handoff_refinement_loop.md` (or similar).
2. **Three GitHub issue drafts**, each with:
   - Clear scope.
   - Acceptance criteria.
   - A short “Questions for DeepWiki” section that references the design doc (for future deep research).

You can tweak names/paths to taste.

---

## 1. Design doc draft – Handoff Refinement Loop

```markdown
# Handoff Refinement Loop: LLM-in-the-Loop + Interrupt + Tracing

## Status

- Stage: Design
- Owners: Jason + DeepAgents core
- Related research:
  - T1/T2/T3 DeepWiki Q&A (local notes)
  - Existing issues #97, #98, #99 (handoff command, summarization, metadata/cleanup)

## Overview

We already have a handoff system that:

- Generates a **handoff summary** via a separate LLM call.
- Uses **HITL interrupts** for agent-initiated handoffs.
- Persists summaries and thread wiring via `handoff_persistence` and [ThreadManager](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/thread_manager.py:56:0-596:25).
- Cleans up via [HandoffCleanupMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_cleanup.py:15:0-67:9) and CLI logic.

Today, **editing** a handoff summary is primarily manual: the CLI lets the user edit title/TL;DR/body fields inline. The LLM is not involved in refinement.

This doc defines a new **model-in-the-loop refinement loop**:

- Users can choose **“Refine”** and provide **natural-language feedback**.
- That feedback routes back through **[HandoffSummarizationMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:347:0-498:20)**, which:
  - Mutates the summarization prompt,
  - Calls the LLM again,
  - Emits another interrupt with a refined draft.
- This can repeat for multiple iterations until the user approves.
- Every iteration is **observable in LangSmith** (prompts, feedback, iterations).

The goal is a system that is:

- Architecturally clean (CLI vs middleware vs persistence).
- Idiomatic for LangGraph/LangChain/DeepAgents.
- Highly traceable and debuggable in LangSmith.

---

## Current behavior (baseline)

### Manual `/handoff` (CLI-owned)

Files:

- [deepagents_cli/commands.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/commands.py:0:0-0:0)
- [deepagents_cli/handoff_ui.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:0:0-0:0)
- [deepagents_cli/handoff_persistence.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_persistence.py:0:0-0:0)
- [deepagents_cli/thread_manager.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/thread_manager.py:0:0-0:0)
- [deepagents_cli/execution.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:0:0-0:0) (for cleanup side-effects)

Flow:

1. User types:

   ```text
   /handoff [--preview] [--messages N]
   ```

2. [handle_command](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/commands.py:681:0-776:15) routes to [handle_handoff_command](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/commands.py:540:0-678:15).

3. [handle_handoff_command](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/commands.py:540:0-678:15):

   - Reads state via [agent.aget_state(configurable={"thread_id": current_id, "assistant_id": ...})](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/tests/test_execution_handoff.py:165:4-166:32).
   - Selects a window of messages using [select_messages_for_summary](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:213:0-246:17) + [_limit_messages_for_summary](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/commands.py:519:0-537:18).
   - Calls [generate_handoff_summary(model, messages, assistant_id, parent_thread_id)](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:285:0-344:98).
   - Wraps result into [HandoffProposal](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:14:0-22:21).
   - Calls [prompt_handoff_decision(proposal, preview_only=...)](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:72:0-121:79).

4. [prompt_handoff_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:72:0-121:79):

   - Renders Markdown summary.
   - Supports Accept / Edit (inline fields) / Decline / Preview.

5. On Accept:

   - Constructs [HandoffSummary](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:41:0-47:19).
   - Calls [apply_handoff_acceptance(session_state, summary, summary_md, summary_json, parent_thread_id)](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_persistence.py:151:0-205:26).
   - Switches the CLI to the new child thread.

6. Cleanup (later):

   - [HandoffCleanupMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_cleanup.py:15:0-67:9) + CLI detect `_handoff_cleanup_pending` and clear `<current_thread_summary>` in `agent.md`, update `metadata["handoff"]`.

**No interrupts are used in this path today.**

---

### Agent-initiated handoff (tool + middleware + HITL)

Files:

- [deepagents/middleware/handoff_tool.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:0:0-0:0) (conceptually; tool wiring)
- [deepagents/middleware/handoff_summarization.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:0:0-0:0)
- [deepagents/middleware/handoff_cleanup.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_cleanup.py:0:0-0:0)
- [deepagents_cli/execution.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:0:0-0:0)
- [deepagents_cli/handoff_ui.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:0:0-0:0)
- [deepagents_cli/handoff_persistence.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_persistence.py:0:0-0:0)

Flow:

1. The agent calls [request_handoff(...)](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:13:0-32:5) tool.

2. [HandoffToolMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:35:0-58:19) sets flags in state:

   - `handoff_requested = True`
   - `preview_only` (optional).

3. [HandoffSummarizationMiddleware.after_model](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:378:4-474:9):

   - Detects `handoff_requested`.
   - Calls [generate_handoff_summary(model, messages, assistant_id, parent_thread_id)](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:285:0-344:98) (using LangChain’s `DEFAULT_SUMMARY_PROMPT`).
   - Builds [HandoffActionArgs](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:50:0-58:22) and HITL payload (`ActionRequest`, `ReviewConfig`).
   - Calls `interrupt(interrupt_payload)`.

4. CLI [execute_task](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:273:0-1047:13):

   - Receives `__interrupt__` with HITL payload.
   - Uses [is_handoff_request](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:134:0-149:5) + [_resolve_handoff_action](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:103:0-131:25) to identify handoff.
   - Builds [HandoffProposal](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:14:0-22:21) and calls [prompt_handoff_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:72:0-121:79).
   - Maps decision to a HITL `decisions` payload (approve / edit / reject / preview).
   - Resumes the graph via `Command(resume={interrupt_id: {"decisions": [...]}})`.

5. [HandoffSummarizationMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:347:0-498:20) resume:

   - [_normalize_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:117:0-164:21) converts resume payload into [HandoffDecisionRecord](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:69:0-81:35).
   - Returns state update:

     - `handoff_requested = False`
     - `handoff_decision = {...}`
     - `handoff_approved = (decision.type == "approve")`.

6. On approval, CLI calls [apply_handoff_acceptance](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_persistence.py:151:0-205:26) and the cleanup cycle runs as above.

**There is only one summarization pass per handoff attempt. “Edit” mostly means manual edits in CLI, not a second LLM pass.**

---

## Goals

- **G1 – Model-in-the-loop refinement**  
  When a user chooses to refine a handoff summary, they should be able to:

  - Provide natural-language feedback.
  - Let the summarization LLM generate a new draft that incorporates that feedback.
  - Repeat until they approve, or stop.

- **G2 – Single canonical refinement loop**  
  The refinement logic should live in **one place** (the summarization middleware + helper), not split across ad hoc CLI code.

- **G3 – LangSmith observability**  

  For each handoff attempt, we should be able to see in LangSmith:

  - Each summarization/refinement iteration as a distinct LLM call with:

    - Clear prompt including feedback context.
    - Metadata (`handoff_iteration`, `feedback`, etc.).
    - Tags for filtering.

  - Each interrupt + resume pair and its associated feedback.

- **G4 – Minimal surface area change for external APIs**  
  Do not change external CLI commands or public tool signatures more than necessary.

- **G5 – Preserve /handoff ergonomics**  
  `/handoff` remains simple to use, but may become a better UX over time (optional: reuse the same refinement loop).

---

## Non-goals

- Designing a generic multi-prompt “prompt-editor” UI.
- Changing the long-term memory format beyond the existing `<current_thread_summary>` block and [HandoffMetadata](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_persistence.py:33:0-44:44).
- Changing how handoffs are surfaced in external UIs beyond CLI & LangSmith.

---

## Target architecture

### Key idea

Turn “Edit/Refine” into a **loop between CLI and [HandoffSummarizationMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:347:0-498:20)**, with the LLM in the middle:

1. Summarization middleware generates a draft (initial or refined) and calls `interrupt(...)`.
2. CLI shows draft and asks for **feedback**.
3. CLI sends feedback back via `Command(resume=...)`.
4. Middleware sees feedback and decides whether to:
   - Call the LLM again with a refined prompt → new interrupt.
   - Or finalize (`handoff_approved` / rejected).

This loop can run multiple times and is fully captured in LangSmith.

---

## Data contracts

### [HandoffActionArgs](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:50:0-58:22) (interrupt payload args)

Extend the existing typed dict:

```python
class HandoffActionArgs(TypedDict):
    handoff_id: str
    assistant_id: str
    parent_thread_id: str
    summary_json: dict[str, Any]
    summary_md: str
    preview_only: bool

    # NEW: refinement metadata
    iteration: int               # 0 = initial summary, >0 = refinements
    feedback: NotRequired[str]   # current feedback, if any
    feedback_history: NotRequired[list[str]]  # prior feedback entries
```

### [HandoffDecisionRecord](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:69:0-81:35) (normalized decision)

Extend to capture feedback:

```python
class HandoffDecisionRecord(TypedDict, total=False):
    type: Literal["approve", "reject", "edit", "preview"]
    message: NotRequired[str]
    edited_action: NotRequired[ActionRequest]

    summary_json: NotRequired[dict[str, Any]]
    summary_md: NotRequired[str]

    feedback: NotRequired[str]
    handoff_id: NotRequired[str]
    assistant_id: NotRequired[str]
    parent_thread_id: NotRequired[str]
    preview_only: NotRequired[bool]

    # NEW
    iteration: NotRequired[int]
    feedback_history: NotRequired[list[str]]
```

### Middleware state keys (internal)

In [HandoffSummarizationMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:347:0-498:20), we maintain refinement state via **private** attributes (using `PrivateStateAttr` semantics conceptually):

- `_handoff_iteration: int`  
  Current iteration count for this handoff (0-based).

- `_handoff_feedback: str | None`  
  Feedback for the *current* refinement pass.

- `_handoff_previous_summary: str | None`  
  Markdown of the summary from the previous iteration.

- `_handoff_refinement_history: list[dict]`  
  History of `{iteration, feedback, summary_md, timestamp}` for audit / debugging.

These are **internal** to the middleware and not part of the public state schema. They are set/updated via the state updates returned from [after_model](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:52:4-58:19).

---

## Summarization + refinement API

We extend [generate_handoff_summary](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:285:0-344:98):

```python
def generate_handoff_summary(
    *,
    model: BaseChatModel | str,
    messages: Sequence[BaseMessage],
    assistant_id: str,
    parent_thread_id: str,

    # NEW:
    feedback: str | None = None,
    previous_summary_md: str | None = None,
    iteration: int = 0,
) -> HandoffSummary:
    ...
```

**Behavior:**

- **Initial pass** (`iteration == 0`, `feedback is None`):

  - Use `DEFAULT_SUMMARY_PROMPT` as today.
  - Prompt contains conversation messages only.

- **Refinement pass** (`iteration > 0` and `feedback` present):

  - Wrap the base summarization prompt with a “refine” layer:

    - Show `previous_summary_md`.
    - Include `feedback` in a dedicated section.
    - Re-include relevant messages as context (or rely on previous summary if message window is large).

---

## Prompt structure (refinement)

Refinement prompt shape (conceptual):

```text
<role>
Context Extraction Assistant
</role>

<primary_objective>
Refine an existing handoff summary based on explicit user feedback.
</primary_objective>

<existing_summary>
{previous_summary_md}
</existing_summary>

<user_feedback>
{feedback}
</user_feedback>

<instructions>
- Preserve factual correctness and important context from the existing summary.
- Prioritize changes that address the user's feedback.
- Do not hallucinate details that are not supported by the conversation.
- If the feedback is not applicable or would degrade the summary, explain briefly in your own internal reasoning but still output the best possible summary.
</instructions>

<messages>
Messages to summarize:
{messages_slice}
</messages>
```

Implementation details can follow LangChain’s refine summarization pattern (T1/T2/T3 references).

---

## Interrupt + loop behavior

### Initial call (iteration 0)

In [after_model](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:52:4-58:19):

1. If `handoff_requested` is false, return `None`.
2. Compute `iteration = state.get("_handoff_iteration", 0)` (default 0).
3. Call [generate_handoff_summary(..., feedback=None, previous_summary_md=None, iteration=iteration)](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:285:0-344:98).
4. Build [HandoffActionArgs](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:50:0-58:22) including:

   - `iteration`
   - `feedback=None`
   - `feedback_history=[]` (or existing history).

5. Build `ActionRequest` and `ReviewConfig(allowed_decisions=["approve", "reject", "edit", "preview"])`.
6. Call `interrupt(payload)`.

### Resume handling

`resume_data` contains `{"decisions": [decision]}`.

We normalize via [_normalize_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:117:0-164:21) to a [HandoffDecisionRecord](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:69:0-81:35) including `feedback` and `iteration` if present.

We then branch:

- **Approve**:

  - `handoff_requested = False`
  - `handoff_decision = decision_record`
  - `handoff_approved = True`
  - Clear `_handoff_*` refinement keys.

- **Reject**:

  - `handoff_requested = False`
  - `handoff_decision = decision_record`
  - `handoff_approved = False`
  - Clear `_handoff_*`.

- **Preview**:

  - No persistence; `handoff_requested = False`.
  - Clear `_handoff_*`.

- **Edit/Refine with feedback**:

  - We expect `decision_record["feedback"]` (from `edited_action.args.feedback`).
  - We construct an updated refinement state:

    ```python
    new_iteration = iteration + 1
    new_history = old_history + [{
        "iteration": iteration,
        "feedback": feedback,
        "summary_md": previous_summary_md,
        "timestamp": now_iso(),
    }]
    ```

  - We return a state update:

    ```python
    {
        "_handoff_iteration": new_iteration,
        "_handoff_feedback": feedback,
        "_handoff_previous_summary": previous_summary_md,
        "_handoff_refinement_history": new_history,
        "handoff_requested": True,   # keep loop alive
        "handoff_decision": decision_record,  # optional
        "handoff_approved": False,
    }
    ```

  - This causes [after_model](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:52:4-58:19) to be invoked again on the next agent step, and the loop repeats.

We may optionally impose a safety cap `MAX_REFINEMENT_ITERATIONS`.

---

## CLI behavior

### [prompt_handoff_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:72:0-121:79)

We extend the UX:

- Options: **Accept**, **Refine**, **Edit (manual)**, **Decline**, **Preview**.
- On **Refine**:

  - Prompt user:

    - “Describe how you want this summary changed (natural language).”
  - Return a decision object that encodes feedback in `edited_action.args.feedback`.

- On **Edit (manual)**:

  - Keep current inline editing behavior (title/TL;DR/bullets).
  - This can still map to a `type="approve"` decision with edited summaries; we are not removing manual edit.

### [execute_task](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:273:0-1047:13) HITL handling

- When we detect a handoff interrupt:

  - We call [prompt_handoff_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:72:0-121:79).
  - We map:

    - Accept → `{"type": "approve"}`
    - Decline → `{"type": "reject", "message": ...}`
    - Preview → `{"type": "preview"}`
    - Refine → `{"type": "edit", "edited_action": {"name": HANDOFF_ACTION_NAME, "args": {..., "feedback": user_feedback}}}`
    - Manual edit → either:
      - `type="approve"` with updated `summary_json/summary_md`, or
      - `type="edit"` with `edited_action.args.summary_json` / `summary_md`.

- We construct `hitl_response = {interrupt_id: {"decisions": [decision_payload]}}` and call `Command(resume=hitl_response)`.

Manual `/handoff` can:

- Either keep its current direct CLI-only behavior for now, or
- In a follow-up, set `handoff_requested=True` and delegate to the same middleware+interrupt loop for consistency.

---

## Tracing & observability (LangSmith)

We want each iteration to be obvious in LangSmith:

- Each call to [generate_handoff_summary](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:285:0-344:98) is a distinct run:
  - `run_name="generate_handoff_summary_iter_{iteration}"`.
- Each LLM call carries metadata:

  - `handoff_iteration`
  - `has_feedback`
  - `feedback_preview` (truncated)
  - `summary_type` (`"initial"` vs `"refinement"`)
  - `parent_thread_id`, `assistant_id`
  - Optional `handoff_id`.

- Tags:

  - `"handoff-summary"`, `"handoff-refinement"`, `"iteration-N"`.

On the LangSmith trace, we should see:

- A single agent run.
- Nested runs for each summarization iteration.
- Interrupt → resume edges between [HandoffSummarizationMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:347:0-498:20) and CLI.

---

## Open questions / future work

- Whether to fully unify manual `/handoff` with the middleware loop (vs keeping a simpler local flow).
- Whether to store `refinement_history` in long-term storage (e.g., a separate file or LangGraph store) for cross-session learning.
- Optional: use structured feedback (Pydantic model) for `feedback`, not just free text.
- Optional: provide a richer TUI for reviewing previous iterations and their feedback.

```

---

## 2. GitHub issue drafts

### Issue 1 – Middleware refinement loop

**Title:** Implement feedback-aware handoff refinement loop in [HandoffSummarizationMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:347:0-498:20)

**Summary**

Extend [HandoffSummarizationMiddleware](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:347:0-498:20) so that handoff summaries can be iteratively refined based on user feedback, using a LangGraph `interrupt` loop and multiple LLM passes. This implements the middleware side of the design in `docs/handoff_refinement_loop.md`.

**Context**

- Current behavior:

  - One summarization pass per handoff attempt.
  - “Edit” is primarily manual CLI editing.

- Target behavior:

  - Middleware can handle multiple iterations:

    - Generate draft → interrupt → resume with feedback → generate refined draft → interrupt → … → approve/reject.

- See design doc: `docs/handoff_refinement_loop.md`.

**Proposed Changes**

- **Extend [HandoffActionArgs](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:50:0-58:22) and [HandoffDecisionRecord](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:69:0-81:35):**

  - Add `iteration`, optional `feedback`, optional `feedback_history`.
  - Ensure [_normalize_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:117:0-164:21) extracts `feedback` from `edited_action.args.feedback` when present.

- **Augment [generate_handoff_summary](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:285:0-344:98):**

  - New params: `feedback`, `previous_summary_md`, `iteration`.
  - Implement two modes:
    - Initial summary (current behavior).
    - Refinement summary (refine prompt that includes previous summary + feedback).

- **Implement refinement loop in [after_model](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:52:4-58:19):**

  - Maintain internal state keys:

    - `_handoff_iteration`
    - `_handoff_feedback`
    - `_handoff_previous_summary`
    - `_handoff_refinement_history`

  - Behavior:

    - If `handoff_requested` and no feedback → generate initial summary, interrupt.
    - On resume with `edit` + feedback → update refinement state and set `handoff_requested=True` to trigger another pass.
    - On approve/reject/preview → finalize, set `handoff_requested=False`, set `handoff_approved`, clear refinement state.

  - Add a safety cap `MAX_REFINEMENT_ITERATIONS` with a reasonable default (e.g. 3).

- **Update tests in [tests/unit_tests/test_handoff_summarization.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/tests/unit_tests/test_handoff_summarization.py:0:0-0:0):**

  - Test:

    - Initial interrupt payload includes `iteration=0`.
    - Second pass refines using feedback and increments `iteration`.
    - Loop stops on approve or after reaching max iterations.

**Acceptance Criteria**

- Given a handoff initiated via [request_handoff](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:13:0-32:5):

  - First interrupt includes `iteration=0` and no `feedback`.
  - If the CLI returns a decision with `type="edit"` and `edited_action.args.feedback="..."`:

    - [after_model](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:52:4-58:19) runs again with `iteration=1`.
    - A new summary is generated using a prompt that includes both the previous summary and the feedback.
    - A new interrupt is raised.

- [HandoffDecisionRecord](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:69:0-81:35) captures feedback and iteration where applicable.

- The loop terminates correctly on approve/reject, and `handoff_requested` is reset to `False`.

- Existing behavior for single-pass handoff (no refine) remains unchanged.

**Questions for DeepWiki (Required Before Implementation)**

Before implementing, the developer should review the design doc and ask DeepWiki (ASTXRTYS/index):

- Whether implementing multiple `interrupt()` calls from a single middleware [after_model](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_tool.py:52:4-58:19) hook is idiomatic, or if upstream prefers modeling refinement as multiple graph turns.
- Whether using internal state keys with `PrivateStateAttr` semantics for `_handoff_iteration` / `_handoff_feedback` aligns with upstream middleware patterns.
- Whether there are upstream examples of refinement loops in summarization middleware that we should mirror for edge cases (e.g., failure modes, timeouts).

---

### Issue 2 – CLI handoff UX: natural-language refinement

**Title:** Upgrade CLI handoff UX to support natural-language refinement and align with middleware loop

**Summary**

Extend the CLI handoff UI so users can refine summaries using natural-language feedback (“Refine”), not only manual field edits. Wire this to the middleware refinement loop defined in `docs/handoff_refinement_loop.md`.

**Context**

- Current CLI behavior:

  - [prompt_handoff_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:72:0-121:79) supports Accept / Edit (manual) / Decline / Preview.
  - “Edit” performs direct inline edits to `summary_json`/`summary_md` and typically maps to `approve`.

- Target behavior:

  - Users can choose “Refine”.
  - CLI collects free-form feedback and encodes it into an `edit`/`refine` decision that the middleware uses to run another summarization pass.

**Proposed Changes**

- **Update [handoff_ui.prompt_handoff_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:72:0-121:79):**

  - Add explicit **Refine** option in the menu.
  - On Refine:

    - Prompt:

      - “Describe how you want this summary changed (natural language).”
    - Return a [HandoffDecision](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:25:0-31:62)-compatible object where:

      - `status` yields a decision kind recognized by [execute_task](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:273:0-1047:13) (e.g., `"refine"` or `"edit"`).
      - Include `feedback` text as an attribute (e.g., `decision.feedback`).

- **Update HITL handling in [deepagents_cli/execution.py](cci:7://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:0:0-0:0):**

  - In handoff-specific branch:

    - Detect when `decision_kind` is refine/edit-with-feedback.
    - Build HITL `decision_payload` as:

      ```python
      {
          "type": "edit",
          "edited_action": {
              "name": HANDOFF_ACTION_NAME,
              "args": {
                  **handoff_args,
                  "feedback": decision_result.feedback,
                  # keep existing fields (handoff_id, parent_thread_id, summary_json/md, etc.)
              },
          },
      }
      ```

  - Ensure backward compatibility with existing “Edit” (manual) behavior.

- **(Optional / stretch)**: For manual `/handoff`:

  - Consider using the same [prompt_handoff_decision](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/handoff_ui.py:72:0-121:79) refine path to keep UX consistent.

**Acceptance Criteria**

- CLI handoff UI presents a **Refine** option and prompts for natural-language feedback.
- When the user chooses Refine:

  - [execute_task](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/deepagents_cli/execution.py:273:0-1047:13) constructs a HITL decision with `type="edit"` and `edited_action.args.feedback` set to the entered feedback.

- When this decision is sent back via `Command(resume=...)`, the middleware’s refinement loop (Issue 1) is able to pick up `feedback` and run a second summarization pass.

- Existing Accept / Decline / Preview behavior remains unchanged.
- Manual field editing (current Edit) still works and either:

  - maps to `approve` with edited summaries, or
  - maps to `edit` with updated `summary_json`/`summary_md` (documented in code/docstrings).

**Questions for DeepWiki (Required Before Implementation)**

Before implementing, the developer should ask DeepWiki (ASTXRTYS/index):

- If there are recommended UX patterns from upstream CLIs or HITL UIs for collecting natural-language feedback for summarization/refinement.
- If there is a preferred mapping between UI-level decisions (Accept/Refine/Edit/Preview) and HITL `Decision` types (`approve` / `edit` / `reject` / `preview`) to keep interoperability with future tooling or UIs.
- If any upstream patterns exist for mixing manual edits and LLM-backed refinements in a single flow (and how to represent that in decisions).

---

### Issue 3 – LangSmith tracing for handoff refinement

**Title:** Add LangSmith tracing & metadata for handoff summarization/refinement iterations

**Summary**

Instrument handoff summarization and refinement so every iteration is clearly visible in LangSmith, with rich metadata and tags. This supports debugging and analytics for the new refinement loop.

**Context**

- Current tracing:

  - Summarization LLM calls are traced, but not strongly annotated with iteration or feedback metadata.

- Target tracing:

  - Each [generate_handoff_summary](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:285:0-344:98) call gets a distinct run name, metadata, and tags.
  - Interrupt/resume cycles can be correlated with iteration numbers and feedback.

- See design doc `docs/handoff_refinement_loop.md` (Tracing & observability section).

**Proposed Changes**

- **Instrument [generate_handoff_summary](cci:1://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:285:0-344:98):**

  - Wrap LLM calls with a tracing config (or `@traceable`) that:

    - Sets `run_name="generate_handoff_summary_iter_{iteration}"`.
    - Attaches metadata:

      ```python
      {
          "handoff_iteration": iteration,
          "has_feedback": bool(feedback),
          "feedback_preview": (feedback[:100] if feedback else None),
          "summary_type": "initial" if iteration == 0 else "refinement",
          "parent_thread_id": parent_thread_id,
          "assistant_id": assistant_id,
          "handoff_id": handoff_id,  # if available
      }
      ```

    - Adds tags like `["handoff-summary", f"iteration-{iteration}", "refinement" if feedback else "initial"]`.

- **Annotate interrupt payloads (optional but nice):**

  - Include `iteration` and `feedback_history` in [HandoffActionArgs](cci:2://file:///Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/deepagents/middleware/handoff_summarization.py:50:0-58:22) for visibility when inspecting the interrupt payload in traces.

- **Document tracing fields:**

  - Add a short section to `docs/handoff_refinement_loop.md` specifying:

    - Which metadata keys are used.
    - How to filter handoff traces by iteration.
    - How to correlate summaries, feedback, and decisions.

- **Tests:**

  - If possible in test harness, assert that:

    - Multiple iterations produce multiple summarization runs.
    - Metadata includes correct `handoff_iteration` and `has_feedback`.

**Acceptance Criteria**

- For a handoff with two refinement iterations:

  - LangSmith shows three runs named:

    - `generate_handoff_summary_iter_0`
    - `generate_handoff_summary_iter_1`
    - `generate_handoff_summary_iter_2`

  - Each run has:

    - `metadata["handoff_iteration"]` set to 0/1/2 respectively.
    - `metadata["summary_type"]` equal to `"initial"` or `"refinement"`.

- Tags on those runs include:

  - `"handoff-summary"`.
  - `"iteration-0"` / `"iteration-1"` etc.

- It is possible to filter or group traces in LangSmith by `handoff_iteration` or `summary_type` to see how prompts and outputs evolve.

- No regressions to existing tracing; non-handoff flows remain unaffected.

**Questions for DeepWiki (Required Before Implementation)**

Before implementing, the developer should ask DeepWiki (ASTXRTYS/index):

- Whether there are recommended conventions for `run_name`, `tags`, and `metadata` for interrupt-driven loops in the LangGraph/LangSmith ecosystem (e.g., prefixing with node/middleware names).
- Whether there are upstream examples of summarization/refinement workflows that use metadata to drive dashboards or quality analysis in LangSmith.
- Whether we should record any additional fields (e.g., iteration counts in the parent run, or linkage between interrupt IDs and summarization runs) to make future analytics easier.

---

### How this answers your questions

- **“Should we reflect on what should be included in each issue?”**  
  Yes: each issue above is scoped to a single responsibility (middleware loop, CLI UX, tracing), with explicit acceptance criteria and targeted DeepWiki questions.

- **“Will you be using T1/T2/T3 as the source reference?”**  
  Yes: the design doc and issues are built directly from the patterns and recommendations distilled from those three DeepWiki Q&A threads, plus your current handoff implementation.

If you like this structure, next step would be for you to:

- Add the design doc file to the repo (or I can implement it with an edit).
- Open the three issues (you can copy-paste and tweak wording/labels).
- Then we can pick one issue—most likely the middleware loop—and start implementing it incrementally.