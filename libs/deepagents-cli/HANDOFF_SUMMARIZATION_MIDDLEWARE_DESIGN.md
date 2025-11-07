# Handoff Summarization Middleware — Implementation Plan (MVP; no auth)

Status: plan (do not implement until approved)
Owner: DeepAgents CLI

This plan is grounded in the current codebase and upstream middleware. It targets a minimal, safe, cost-aware handoff flow that works entirely in the CLI, with optional persistence hooks later. Authentication is intentionally omitted per instruction.

---

## Problem statement (brief)
- Long threads exceed context; new threads lose continuity and require re-orientation.
- We need an explicit, on-demand handoff summary that captures just the high-signal context and seeds the child thread immediately.
- Summary must be user-approved, cheap to generate, and automatically cleared after the first child turn to avoid prompt bloat.

---

## Current state (what’s true now, with filepaths/snippets)

1) Summarization is reactive (token-triggered), not on-demand

- The core library wires `SummarizationMiddleware` at ~170k tokens for both main agent and subagents:

```python
# libs/deepagents/graph.py
# Summarization threshold + 6 most recent messages preserved
SummarizationMiddleware(
    model=model,
    max_tokens_before_summary=170000,
    messages_to_keep=6,
)
```

2) Agent memory (agent.md) is injected on every call

- CLI uses a long-term backend and `AgentMemoryMiddleware` to prepend `agent.md` to the system prompt:

```python
# libs/deepagents-cli/deepagents_cli/agent.py
long_term_backend = FilesystemBackend(root_dir=agent_dir, virtual_mode=True)
backend = CompositeBackend(default=FilesystemBackend(), routes={"/memories/": long_term_backend})
agent_middleware = [AgentMemoryMiddleware(backend=long_term_backend, memory_path="/memories/"), ...]
```

```python
# libs/deepagents-cli/deepagents_cli/agent_memory.py
AGENT_MEMORY_FILE_PATH = "/agent.md"
...
request.system_prompt = (
    memory_section + ("\n\n" + request.system_prompt if request.system_prompt else "")
    + "\n\n" + LONGTERM_MEMORY_SYSTEM_PROMPT.format(memory_path=self.memory_path)
)
```

3) CLI streaming supports updates/HITL but has no summary feature

```python
# libs/deepagents-cli/deepagents_cli/execution.py (dual-stream)
async for chunk in agent.astream(..., stream_mode=["messages", "updates"], subgraphs=True, ...):
    if current_stream_mode == "updates":
        # HITL, todos, etc.
        ...
```

4) Thread lifecycle utilities exist

```python
# libs/deepagents-cli/deepagents_cli/thread_manager.py
new_id = thread_manager.create_thread(name=name, parent_id=parent)
# fork_thread(...) copies full state (not desired for handoff)
```

5) Upstream summarizer prompt and trimming utilities are available

```python
# .venv/.../langchain/agents/middleware/summarization.py
DEFAULT_SUMMARY_PROMPT = """<role>Context Extraction Assistant</role> ... {messages} ..."""
# Uses count_tokens_approximately + trim_messages(..., max_tokens=4000)
```

---

## Proposed changes (concise)

MVP is CLI-only and file-backed; no server/microservice, no auth.

1) Add a new slash command: `/handoff` (and `/handoff --preview`)
- Location: `libs/deepagents-cli/deepagents_cli/commands.py` (extend `handle_command`).
- Flow: collect current thread id from `SessionState.thread_manager`, generate preview, prompt accept/edit/skip.

2) Implement a small helper module for handoff
- New: `libs/deepagents-cli/deepagents_cli/handoff.py`
  - `select_messages_for_summary(agent, thread_id) -> list[AnyMessage]`: pull messages from checkpointer via `agent.get_state(config)`; score+limit; then use `trim_messages(..., max_tokens=4000)`.
  - `generate_summary(model, messages) -> str`: call upstream `DEFAULT_SUMMARY_PROMPT` using `init_chat_model` if needed; enforce token cap (≈250-300 output tokens).
  - `structure_summary(text) -> dict`: return `{title, body: [..], tldr}`; also compute `summary_md`.
  - `update_agent_memory_block(backend, new_md)`: atomically replace text between `<current_thread_summary>` markers in `/memories/agent.md` (temp file + `os.replace`). If markers missing, insert a default scaffold once.

3) Memory write and child thread creation (on accept)
- Write summary into the managed block in `agent.md` via long-term backend.
- Create child thread: `thread_manager.create_thread(name=..., parent_id=<current>)`.
- Set metadata flags in `threads.json` (via ThreadStore) if needed later: `handoff_pending=True`, `handoff_source_thread_id=<parent>`.

4) Automatic cleanup after first child turn
- Hook: in CLI streaming loop, after the first complete turn in the new thread, clear the block back to a placeholder. Minimal approach: add a small check in `execute_task` that detects the first assistant completion when `handoff_pending` is set; then reset the block and clear the flag.

5) (Optional, Phase 2) Store mirroring
- Mirror accepted summaries to PostgresStore under namespace `(assistant_id, "thread_summaries")` with canonical JSON (`summary_json`) and `summary_md`. Idempotency via `handoff_id`.

6) Observability (no auth)
- Generate `handoff_id = uuid4()` per run; log to console; include `tokens_used` if available from model usage metadata; optionally stash `last_handoff` metadata on the parent thread via `ThreadStore` for debug.

---

## Data contract (canonical; file-backed in MVP)

- `summary_json` (canonical):
```json
{
  "handoff_id": "uuid",
  "assistant_id": "agent",
  "parent_thread_id": "thr_parent",
  "child_thread_id": "thr_child",  
  "title": "...",
  "body": ["..."],
  "tldr": "...",
  "model": "claude-sonnet-4-5-20250929",
  "tokens_used": 0,
  "created_at": "2025-..Z"
}
```
- `summary_md`: rendered panel that goes inside `<current_thread_summary>`.

---

## File changes (planned locations)
- New: `libs/deepagents-cli/deepagents_cli/handoff.py` (summarization slice only)
- New: `libs/deepagents-cli/deepagents_cli/handoff_hitl.py` (HITL approval coordinator; emits/consumes interrupts; CLI-only in MVP)
- Update: `libs/deepagents-cli/deepagents_cli/commands.py` (add `/handoff`, wire preview/edit/accept/decline via HITL)
- Update: `libs/deepagents-cli/deepagents_cli/execution.py` (render dedicated handoff preview; capture edits; first-turn cleanup when `handoff_pending`)
- Optional: `libs/deepagents-cli/deepagents_cli/ui/handoff_preview.py` (encapsulate preview/edit UI if we want to keep `execution.py` slim)
- No changes to core lib `libs/deepagents/graph.py` (reactive summarization remains for compaction)

---

## HITL approval middleware (separate, reusable)

### Responsibility split
- Summarization (handoff.py): gather messages → trim → call LLM with `DEFAULT_SUMMARY_PROMPT` → return `summary_json/summary_md`.
- HITL (handoff_hitl.py): present preview, accept/refine/decline, and only on accept perform side effects (memory write + child thread spawn).

This mirrors LangChain middleware conventions (see `.venv/.../langchain/agents/middleware/types.py`) where one middleware does one job.

### Interrupt payload (updates stream)
HITL emits an interrupt with a single action request so the existing updates/approval surface can be reused:
```json
{
  "__interrupt__": {
    "action_requests": [
      {
        "name": "handoff_summary",
        "description": "Preview handoff summary for approval",
        "args": {
          "handoff_id": "uuid",
          "summary_json": {"title": "...", "body": ["..."], "tldr": "..."},
          "summary_md": "## Recent Thread Snapshot...",
          "assistant_id": "agent",
          "parent_thread_id": "thr_parent"
        }
      }
    ]
  }
}
```

### Decision schema (resume payload)
Allow three outcomes while remaining compatible with existing approval flow:
```json
{
  "decisions": [
    {"type": "approve", "args": {"summary_md": "(optional edited md)", "title": "(optional)"}},
    {"type": "reject"},
    {"type": "edit", "args": {"summary_md": "(edited md)", "title": "(optional)"}}
  ]
}
```
Rules:
- `approve` without args → accept as-is.
- `approve` with args → accept with edits (preferred over a third type if we want to keep two-option UI).
- If we support `edit` explicitly, treat it as `approve` with edits on the coordinator.

### CLI integration
- `execution.py` detects `name == "handoff_summary"` and renders a dedicated preview/editor (rich markdown panel, small text editor); on submit, build the appropriate decision payload.
- `commands.py` adds `/handoff` to trigger the summarization slice and then defers to HITL for approval.
- On `approve`: call `update_agent_memory_block(...)`, create child thread via `ThreadManager.create_thread(parent_id=...)`, set `handoff_pending=True` metadata and switch.
- Cleanup: after first complete child turn, clear the block and unset `handoff_pending`.

### Middleware hooks (naming/conventions)
If we later factor HITL into a formal middleware, follow LangChain naming/shape:
```python
# path=null start=null
from langchain.agents.middleware.types import AgentMiddleware, before_agent

class HandoffHitlMiddleware(AgentMiddleware):
    @before_agent
    def propose_handoff(self, state, runtime):
        # Only triggered by explicit /handoff command (set via state metadata)
        # 1) select+summarize (call handoff.py helpers)
        # 2) emit interrupt payload as above (runtime.updates stream)
        return None

    # Optionally handle resume decisions in a later hook if we ever move side-effects into the graph
```
For the CLI MVP, we keep side-effects in CLI code and use the middleware only to standardize the interrupt payload.

## Key algorithms (sketches)

- Message selection (reuse upstream trims; minimal heuristics):
```python
# path=null start=null
from langchain_core.messages.utils import count_tokens_approximately, trim_messages

MAX_TO_SCORE = 120
TOP_N = 25

scored = score(messages[-MAX_TO_SCORE:])  # prefer user/assistant, recent, pair tool calls
subset = [m for _, m in sorted(scored, key=lambda x: x[0], reverse=True)[:TOP_N]]
subset.sort(key=lambda m: m.additional_kwargs.get("timestamp", 0))
trimmed = trim_messages(subset, max_tokens=4000, token_counter=count_tokens_approximately,
                        start_on="human", strategy="last", allow_partial=True, include_system=True)
```

- Summary generation (upstream prompt):
```python
# path=null start=null
from langchain.chat_models import init_chat_model
from langchain.agents.middleware.summarization import DEFAULT_SUMMARY_PROMPT

llm = init_chat_model(model) if isinstance(model, str) else model
resp = llm.invoke(DEFAULT_SUMMARY_PROMPT.format(messages=trimmed))
text = (resp.content or "").strip()
```

- Atomic block write:
```python
# path=null start=null
START, END = "<current_thread_summary>", "</current_thread_summary>"
md = backend.read("/agent.md")
if START not in md or END not in md:
    md = md + f"\n\n## Recent Thread Snapshot\n{START}\nNone recorded yet.\n{END}\n"
new_md = md.split(START)[0] + START + "\n" + summary_md + "\n" + md.split(END,1)[1]
backend.write_atomic("/agent.md", new_md)  # temp+replace helper
```

---

## Testing & acceptance (MVP)
- Unit: selection/formatting; block migration/atomic write; `/handoff --preview|--apply` flows; first-turn cleanup idempotency.
- Integration: CLI happy-path (preview → accept → child created → block visible on first turn → cleared after reply). No server or Postgres required.

---

## Implementation roadmap (QA alignment)
MVP scope is 16 steps, followed by 4 Phase-2 hardening steps. This ordering matches the intended spec (CLI-only bridge first, persistence/observability second).

**MVP (steps 1-16)**
1. Create `handoff.py` skeleton with public helpers (message fetch, selectors, summarizer, block writer).
2. Fetch messages from LangGraph checkpointer via `agent.get_state(config)` for the active thread.
3. Implement selection heuristics that preserve AI/Tool pairs and then trim with `trim_messages`.
4. Implement `generate_summary` using `DEFAULT_SUMMARY_PROMPT` + `init_chat_model`, enforcing ~300 output tokens.
5. Implement `structure_summary` to produce `{title, body[3-6], tldr}` plus rendered `summary_md`.
6. Add one-time migration that injects `<current_thread_summary>` markers into `agent.md` if missing.
7. Implement atomic block updater (temp write + rename) through the long-term backend.
8. Generate `handoff_id`, capture `model_run_id`/`tokens_used` when present, log for observability.
9. Extend `commands.py` with `/handoff` command + flags (`--preview`, `--apply`).
10. Build CLI preview UI (accept / edit / skip) that surfaces structured + Markdown outputs.
11. On accept, write the agent.md block and set thread metadata flags (`handoff_pending`, `handoff_source_thread_id`).
12. Create a child thread via `ThreadManager.create_thread(parent_id=...)` and switch active thread.
13. Add cleanup hook in `execution.py` that clears the block after the first complete child turn and unsets flags.
14. Add unit tests for selection, structuring, migration/updater, and command parsing.
15. Add integration test covering preview → accept → child sees summary → block cleared after first reply.
16. Update CLI help/docs to explain `/handoff` usage and expectations.

**Phase 2 (steps 17-20)**
17. Mirror summaries into Postgres namespace `(assistant_id, "thread_summaries")`, storing both `summary_json` (JSONB) and `summary_md` (TEXT) keyed by `handoff_id`.
18. Add resilient error handling for store outages (silent fallback, retries, metrics).
19. Emit richer observability: log/trace `handoff_id`, `model_run_id`, `tokens_used`, and optional thread metadata (`last_handoff`).
20. Expand tests to cover persistence/mirroring paths and degraded scenarios (store unavailable, retries hit).

**Alignment check:** These steps fulfill PLAN-HANDOFF’s intent—manual summarization + agent.md bridge in MVP, followed by persistence/analytics hardening. No scope creep beyond the approved spec.


## Out of scope (this pass)
- AuthN/Z, webhook/event bus, subagent aggregation, automated token-based handoff triggers, analytics dashboards.

---

## References (verified)
- Summarization wiring: `libs/deepagents/graph.py`
- Memory injection: `libs/deepagents-cli/deepagents_cli/agent_memory.py`, `.../agent.py`
- CLI command router: `libs/deepagents-cli/deepagents_cli/commands.py`
- Streaming loop: `libs/deepagents-cli/deepagents_cli/execution.py`
- Thread lifecycle: `libs/deepagents-cli/deepagents_cli/thread_manager.py`
- Upstream summarizer + middleware conventions: `.venv/lib/python3.11/site-packages/langchain/agents/middleware/`
- External docs to stay aligned with LangGraph/LangSmith guidance:
  - [Adding FastAPI dependency for custom middleware in LangGraph Platform](https://support.langchain.com/articles/7593416758-Adding-FastAPI-dependency-for-custom-middleware-in-LangGraph-Platform)
  - [LangGraph Thread Deletion Runbook](https://support.langchain.com/articles/1013695957-LangGraph-Thread-Deletion-Runbook)
  - [How do I configure checkpointing in LangGraph?](https://support.langchain.com/articles/1242226068-How-do-I-configure-checkpointing-in-LangGraph?)
  - [LangSmith Data Migration Guide: Traces, Datasets, and Experiments](https://support.langchain.com/articles/5829492596-LangSmith-Data-Migration-Guide:-Traces,-Datasets,-and-Experiments)

> **Important:** Summarization middleware is only responsible for generating `summary_json/summary_md`. A separate HITL approval layer (CLI UX now, future middleware later) must handle accept/refine/decline before any memory writes or child-thread creation. This keeps us in line with LangChain middleware patterns and the docs above.
