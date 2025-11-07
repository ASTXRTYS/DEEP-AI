# PLAN-HANDOFF.md — Seamless Thread Handoff Summaries

Status: proposal (do not implement until approved)
Owner: DeepAgents CLI

## Problem (why this exists)
- Long-running threads eventually hit token-compaction limits; users open a new thread and lose continuity.
- We want a lightweight, reliable way to “carry forward” just what matters so a new thread feels like a continuation.
- Upstream CLI UI recently removed the collapsible conversation-summary panel; we will own our own handoff UX.

## Current state (what’s true in code now)

1) Deep Agent core attaches SummarizationMiddleware by default

- The library wires summarization both for the main agent and default subagents:

```python
# libs/deepagents/graph.py
# Summarization is active at ~170k tokens, keeps last 6 messages verbatim
...
 deepagent_middleware = [
     TodoListMiddleware(),
     handle_filesystem_permissions,
     FilesystemMiddleware(backend=backend),
     SubAgentMiddleware(
         default_model=model,
         default_tools=tools,
         subagents=subagents if subagents is not None else [],
         default_middleware=[
             TodoListMiddleware(),
             handle_filesystem_permissions,
             FilesystemMiddleware(backend=backend),
             SummarizationMiddleware(
                 model=model,
                 max_tokens_before_summary=170000,
                 messages_to_keep=6,
             ),
             AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
             PatchToolCallsMiddleware(),
         ],
         ...
     ),
     SummarizationMiddleware(
         model=model,
         max_tokens_before_summary=170000,
         messages_to_keep=6,
     ),
     AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
     PatchToolCallsMiddleware(),
 ]
```

2) Agent memory is injected from ~/.deepagents/{agent}/agent.md on every call

- The CLI injects agent.md via AgentMemoryMiddleware using a dedicated backend route.

```python
# libs/deepagents-cli/deepagents_cli/agent.py
agent_dir = Path.home() / ".deepagents" / assistant_id
long_term_backend = FilesystemBackend(root_dir=agent_dir, virtual_mode=True)
backend = CompositeBackend(
    default=FilesystemBackend(), routes={"/memories/": long_term_backend}
)
agent_middleware = [
    AgentMemoryMiddleware(backend=long_term_backend, memory_path="/memories/"),
    shell_middleware,
]
```

- AgentMemoryMiddleware prepends the file into the system prompt:

```python
# libs/deepagents-cli/deepagents_cli/agent_memory.py
AGENT_MEMORY_FILE_PATH = "/agent.md"
...
memory_section = self.system_prompt_template.format(agent_memory=agent_memory)
if request.system_prompt:
    request.system_prompt = memory_section + "\n\n" + request.system_prompt
else:
    request.system_prompt = memory_section
request.system_prompt = (
    request.system_prompt
    + "\n\n"
    + LONGTERM_MEMORY_SYSTEM_PROMPT.format(memory_path=self.memory_path)
)
```

3) CLI stream loop has no summary panel now

- After upstream changes, the CLI streaming loop renders only human/assistant text and tool calls (no summary panel). We will add our own HITL preview for handoff.

```python
# libs/deepagents-cli/deepagents_cli/execution.py (streaming skeleton)
async for chunk in agent.astream(..., stream_mode=["messages", "updates"], subgraphs=True, ...):
    if current_stream_mode == "messages":
        # Render assistant text
        ...
    elif current_stream_mode == "updates":
        # HITL, todos, etc.
        ...
```

4) Thread manager

- Creating a new thread yields a blank timeline; forking copies the full state.

```python
# libs/deepagents-cli/deepagents_cli/thread_manager.py (fork)
new_thread_id = fork_thread_on_server(source_thread_id)
source_config = {"configurable": {"thread_id": source_thread_id}}
state = agent.get_state(source_config)
new_config = {"configurable": {"thread_id": new_thread_id}}
agent.update_state(new_config, state.values)
```

5) Store & checkpointing

- CLI enables SqliteSaver checkpoints (per-thread resume) and PostgresStore (cross-conversation storage) already.

```python
# libs/deepagents-cli/deepagents_cli/agent.py
# SqliteSaver for checkpoints
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()

# Postgres store (present but not yet used by handoff flow)
pg_conn = psycopg.connect(database_url, autocommit=True)
store = PostgresStore(pg_conn)
store.setup()
```

## Proposed change (what we’ll implement)

Design: “handoff summary” in agent.md
- Add a single, managed block at the top of agent.md:

```markdown
## Recent Thread Snapshot
<current_thread_summary>
None recorded yet.
</current_thread_summary>
```

- On handoff, overwrite the block with a short summary of the current thread (approved by the user). The child thread reads it on the very first turn via AgentMemoryMiddleware. After the first response, reset the block to the placeholder.

User experience
- New CLI command: `/threads handoff` (or a confirmation step in `/new`).
  - Present a preview from a manual summarization call (reuse SummarizationMiddleware prompt/logic).
  - User can accept/edit/skip.
  - If accepted: write to agent.md block atomically, create child thread (parent_id set), switch.
  - If skipped: create fresh thread without handoff.

Why not inject as an assistant message?
- Putting the summary in agent.md guarantees highest prompt salience using the existing AgentMemoryMiddleware. No extra state seeding needed.

Avoid full-state fork for handoff
- Use create_thread (blank state) for handoff continuity. Forking copies the entire prior context, defeating the purpose.

Optional (later)
- Mirror the accepted summary into Postgres under namespace `(assistant_id, "thread_summaries")` for history/analytics.

## Implementation plan (high signal)

1) Agent prompt template and migration
- On agent initialization, ensure agent.md contains the managed block; if missing, insert once.

2) Atomic updater helper
- Write a small function that replaces text between `<current_thread_summary>` and `</current_thread_summary>` atomically (temp file + replace). If the markers are missing, fail fast or run the one-time migration.

3) Manual summarization on demand
- Fetch the current thread state (via checkpointer or agent.get_state) and run a single summarization call that reuses the SummarizationMiddleware prompt/logic, but is invoked explicitly (do NOT rely on the 170k-token trigger).
- Scope: summarize the MAIN agent thread; do not attempt to pull subagent-local summaries (future enhancement may aggregate subagent final reports).
- Output budget: cap to ~200–300 tokens, structured as short bullets: Objective (1 line), Progress (2–3 bullets), Next Steps (1–2 bullets), Blockers (optional, 1 line), and Key Artifacts/Paths.

4) HITL preview and command
- Add `/threads handoff` to prompt the preview. Accept/edit/skip. On accept: write block, create child thread with parent_id, switch.

5) Cleanup after first reply
- In the streaming loop, after the first assistant response in the new thread, reset the block to the placeholder to avoid lingering context. (Alternative: a tiny middleware that clears once per thread when `handoff_pending=True` in metadata.)

## Nuances & risks
- Do not mutate the rest of agent.md; writes must be atomic.
- Avoid stale summaries: we call summarization at handoff-time (not relying on the rolling compactor).
- Don’t use `fork_thread` for handoff continuity; that clones full state. Prefer `create_thread(..., parent_id=...)`.
- Keep the summary tight so the prompt stays high-signal; structured bullets over long prose.
- If Postgres is unavailable, the feature still works (pure filesystem). Store mirroring is optional.

## Success criteria
- New thread’s first answer reflects prior context (objective/progress/next steps) with no manual prodding.
- The summary block is cleared after the first reply (or on the next user action), preventing prompt bloat.
- No corruption of agent.md even under interruption.

## References (filepaths)
- Summarization wiring: `libs/deepagents/graph.py`
- Memory injection: `libs/deepagents-cli/deepagents_cli/agent_memory.py`
- CLI agent setup: `libs/deepagents-cli/deepagents_cli/agent.py`
- Stream loop integration point: `libs/deepagents-cli/deepagents_cli/execution.py`
- Thread lifecycle: `libs/deepagents-cli/deepagents_cli/thread_manager.py`
- Composite backend routing: `libs/deepagents/backends/composite.py`

## Critical nuances & conventions

- Middleware order and on-demand summarization
  - SummarizationMiddleware is reactive (fires at ~170k). For handoff, call a one-shot summarizer explicitly.
  - Keep the default middleware as-is for compaction; handoff uses a separate manual call.

- Backend-aware, atomic writes to agent.md
  - Treat `/memories/agent.md` as canonical and use the long-term backend to read/write (backend-agnostic helper). Ensure atomicity: write to a temp and replace.
  - Virtual paths: with `virtual_mode=True`, do not use raw absolute paths; operate via backend methods.
  - **Race condition mitigation:** Use backend's atomic semantics (FilesystemBackend has OS-level temp+rename; verify TTL/eviction doesn't corrupt mid-write). Consider read-modify-write locks if concurrent CLI+server access is possible.

- Thread metadata and cleanup signal
  - When creating the child thread, set metadata: `handoff_pending=True`, `handoff_source_thread_id=<parent>`.
  - Clear the summary block after the first **complete turn** in the child thread (not first token/message). In the CLI loop, detect end-of-turn (when `next` is empty or graph is idle) and then reset the block.
  - Custom metadata flags: Use snake_case with `handoff_` prefix (e.g., `handoff_pending`, `handoff_source_thread_id`) for consistency.
  - LangGraph threading model: child threads are logically related but state-independent; no auto-pull from parent.

- Subagent context policy
  - Summarize the main agent thread only. Optionally note recent subagent outcomes at a sentence level; do not attempt to merge subagent-local summaries.
  - Subagents have their own SummarizationMiddleware instances (170k threshold each); subagent summaries are local to subagent state, not visible to parent.
  - For continuity: if recent messages show subagent results, mention high-level contribution (e.g., "web-researcher subagent found 3 sources") but avoid full subagent state capture.

- Summary budget & template
  - Cap to ~200–300 tokens. Prefer structured bullets for scannability.

  Example block:
  ```markdown
  ## Recent Thread Snapshot
  <current_thread_summary>
  Objective: Implement /threads handoff to keep continuity across threads.

  Progress:
  - Added AgentMemoryMiddleware injection; validated prompt ordering
  - Designed atomic updater for /memories/agent.md block
  - Confirmed SummarizationMiddleware integration points

  Next Steps:
  - Add /threads handoff with HITL preview (accept/edit/skip)
  - Reset summary block after first turn in child thread

  Blockers: None currently.
  </current_thread_summary>
  ```

- Error handling & UX
  - If summarization fails: Log error, show user "Failed to generate summary. Continue without handoff? (Y/n)", create blank child thread if they skip.
  - If user rejects summary: Don't write the block; create a fresh thread instead.
  - Provide a dry-run: `/threads handoff --preview` (no write), `/threads handoff --apply` (commit).
  - **AgentMemoryMiddleware safety:** Test blank/malformed summary blocks don't break middleware; add fallback logic (inject "No recent context." placeholder).
  - **Idempotency:** Resetting the block must be idempotent; if cleanup fails, next thread invocation shouldn't reuse stale summary.

- Postgres mirroring (phase 2)
  - Namespace: `(assistant_id, "thread_summaries")`, key: `source_thread_id`.
  - Value payload: `{ summary, plain_text, timestamp, source_thread_id, target_thread_id, model_used }`.
  - Silent fallback if store unavailable.

## Implementation checklist

PHASE 1: Core handoff
- [ ] Atomic updater for `/memories/agent.md` handoff block (backend-agnostic, temp-write + replace, race-condition safe)
- [ ] One-time migration: insert the placeholder block if missing on agent initialization
- [ ] On-demand summarization helper (extract SummarizationMiddleware prompt template; explicit call, not 170k-trigger; 200–300 token cap)
- [ ] `/threads handoff` command with HITL preview (accept/edit/skip flow)
- [ ] Create child thread with `parent_id` and metadata flags (`handoff_pending=True`, `handoff_source_thread_id=<parent>`)
- [ ] Cleanup hook to reset block after first **complete turn** in child thread (detect graph idle, not first token)
- [ ] Streaming tests: verify block is present on turn 1 and cleared after turn 1 completes
- [ ] Failure paths: summarization error, user rejection, store unavailable, malformed block handling
- [ ] AgentMemoryMiddleware fallback logic for blank/missing summary blocks

PHASE 2: Robustness
- [ ] Concurrent write test for atomicity/race mitigation (CLI + server simultaneous handoff)
- [ ] Migration test for missing block (agent.md without placeholder → auto-insert on first use)
- [ ] Dry-run mode coverage (`--preview` vs `--apply`)
- [ ] Verify CompositeBackend + virtual_mode behavior end-to-end
- [ ] First-turn detection accuracy (complete turn vs first message vs first token)
- [ ] AgentMemoryMiddleware ordering and middleware execution sequence validation

PHASE 3: Enhancements
- [ ] Postgres mirroring (namespace/schema) with silent fallback
- [ ] Optional subagent outcome note in summary (inspect recent message metadata for subagent results)
- [ ] Auto-rotation heuristics (token-based handoff trigger when approaching 170k threshold)
- [ ] CLI help documentation (explain context bridge vs full fork to users)
- [ ] Historical handoff analytics via Postgres store queries

## Conventions & best practices

- **Variable naming:** Use `current_thread_summary` (not `summary_block` or `handoff_text`) for clarity across codebase.
- **Metadata keys:** Use snake_case and prefix with `handoff_` (e.g., `handoff_pending`, `handoff_source_thread_id`) for consistency.
- **Error messages:** Be specific: `"SummarizationMiddleware call failed: {exception}. Creating blank thread instead."` (not generic "Failed to handoff").
- **Logging levels:** INFO when handoff succeeds, DEBUG when middleware is skipped, WARN when block reset fails.
- **Documentation:** Add CLI help section explaining feature—users should understand they're getting a context bridge, not a full fork.

## Why this matters for the team

- **DeepAgents middleware is composable but order-dependent:** AgentMemoryMiddleware runs first every turn; essential for design.
- **Summarization is reactive by default, not on-demand:** Need explicit triggering for predictable handoff timing.
- **File atomicity is your responsibility:** Plan correctly identifies this; verify backend-level race protection.
- **Subagents introduce late complexity:** Start without it; design summary structure to accommodate future aggregation.

## External documentation references

- [Deep Agents Middleware](https://docs.langchain.com/oss/python/deepagents/middleware) - Composable middleware patterns and execution order
- [Deep Agents Harness Capabilities](https://docs.langchain.com/oss/python/deepagents/harness) - Planning, filesystem, and subagent capabilities
- [Context Engineering in Agents](https://docs.langchain.com/oss/python/langchain/context-engineering) - Managing context windows and memory
- [Memory Overview](https://docs.langchain.com/oss/python/concepts/memory) - LangChain memory concepts and patterns
- [Persistence & Checkpointing](https://docs.langchain.com/oss/python/langgraph/persistence) - LangGraph state management and resumption
- [Streaming from Subgraphs](https://docs.langchain.com/oss/python/langgraph/streaming#stream-subgraph-outputs) - Stream handling and turn detection
- [LangGraph Checkpointing Configuration](https://support.langchain.com/articles/1242226068-How-do-I-configure-checkpointing-in-LangGraph) - Checkpointer setup and thread management

---

Notes
- This plan is intentionally minimal: one file block, one command, one cleanup hook. We can later add auto-rotation heuristics (trigger handoff when token count exceeds a threshold) and Postgres mirroring without changing the user-facing flow.
- **Confidence boost:** Plan is architecturally sound and avoids major pitfalls. Execute Phase 1 cleanly, test Phases 2 & 3 separately. This solves a real problem (token limits + continuity) with a lightweight, filesystem-native approach that fits DeepAgents' architecture.
