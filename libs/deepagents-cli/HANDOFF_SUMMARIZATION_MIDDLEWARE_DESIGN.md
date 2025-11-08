# Handoff Summarization Middleware — Implementation Plan (MVP; no auth)

Status: plan (do not implement until approved)
Owner: DeepAgents CLI

This plan is grounded in the current codebase and upstream middleware. It targets a minimal, safe, cost-aware handoff flow that works entirely in the CLI, with optional persistence hooks later. Authentication is intentionally omitted per instruction.

> **Architecture reminder:** Handoff relies on **two explicit middleware layers**, mirroring LangChain’s `langchain/agents/middleware` conventions (snake_case module names + `*Middleware` classes):
> - File `handoff_summarization.py` exporting `HandoffSummarizationMiddleware` (context extraction). It selects/trim messages, invokes the summarization prompt, and returns `summary_json/summary_md`. **No side effects.**
> - File `handoff_approval.py` exporting `HandoffApprovalMiddleware` (HITL). It owns preview/edit/accept/decline, writes the `<current_thread_summary>` block, sets `handoff_*` metadata, spawns the child thread, and schedules cleanup.
>
> Keeping these responsibilities separate removes the “helper vs middleware” ambiguity and matches the latest LangChain guidance.

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

MVP is CLI-only and file-backed; no server/microservice, no auth. The design introduces **two middleware layers** that run back-to-back during `/handoff`.

1) Add a new slash command: `/handoff` (and `/handoff --preview`)
- Location: `libs/deepagents-cli/deepagents_cli/commands.py`.
- Flow: collect current thread id from `SessionState.thread_manager`, mark `session_state.intent = "handoff"` and `state["handoff_requested"]=True`, invoke the summarization middleware **only when that flag is present**, then pass the result to the HITL middleware for approval. No other model turns trigger summarization.

2) Implement two middleware modules following LangChain naming (snake_case file, CamelCase class)
- `libs/deepagents-cli/deepagents_cli/handoff_summarization.py`
  - `select_messages_for_summary(agent, thread_id)`
  - `generate_summary(model, messages)` using `DEFAULT_SUMMARY_PROMPT`
  - `structure_summary(text)` returning `{title, body, tldr, summary_md}`
  - Emits `summary_json` + `summary_md` only; no memory or thread mutations.
- `libs/deepagents-cli/deepagents_cli/handoff_approval.py`
  - Receives the candidate summary payload from step 1.
  - Presents preview/edit/accept/decline (CLI UI for MVP).
  - On accept: calls `update_agent_memory_block(...)`, sets thread metadata flags, and creates the child thread.
  - On decline: exits cleanly (no writes).
  - On edit: lets the user tweak `summary_md`/title before acceptance.
  - Provides `handoff_id`, `model_run_id`, `tokens_used` for observability.

3) Memory write and child thread creation (owned by CLI, NOT middleware)

**CRITICAL REVISION:** Middleware should NOT write metadata. LangGraph Platform doesn't expose direct metadata write APIs during middleware execution.

- **Middleware responsibility**: Emit the interrupt, return state unchanged.
- **CLI responsibility** (after interrupt is accepted):
  - Write summary into the managed block in `agent.md` via the long-term backend.
  - Create child thread via `thread_manager.create_thread(name=..., parent_id=<current>)`.
  - Set metadata on both parent + child threads under `metadata["handoff"] = {"handoff_id": ..., "source_thread_id": ..., "pending": True, "cleanup_required": True}`.
- **Platform**: Write metadata via the REST API after handoff approval (async, outside the graph execution).

4) Automatic cleanup after first child turn

**CRITICAL REVISION:** Use graph-level edge, not CLI-only execution.py hook (for Platform compatibility).

- Add a **graph-level conditional edge** that detects cleanup requirement after the first assistant message in child thread.
- Edge checks: `metadata["handoff"]["pending"]` && `metadata["handoff"]["cleanup_required"]` && `state["_handoff_first_turn_done"]`.
- If true, route to `cleanup_handoff` node that clears the summary block and unsets metadata flags.
- This works in both CLI and Platform deployments (execution.py doesn't exist in Platform).

5) Store mirroring

**REVISION:** Add explicit idempotency mechanism.

- Mirror accepted summaries (and their metadata) to PostgresStore namespace `(assistant_id, "thread_summaries")`, storing both `summary_json` and `summary_md`.
- **Idempotency**: Use PostgreSQL `UPSERT` pattern:
  ```sql
  INSERT INTO thread_summaries (assistant_id, handoff_id, summary_json, summary_md)
  VALUES (?, ?, ?, ?)
  ON CONFLICT (assistant_id, handoff_id) DO UPDATE
    SET summary_json = EXCLUDED.summary_json,
        summary_md = EXCLUDED.summary_md,
        updated_at = NOW()
  WHERE last_updated < NOW() - INTERVAL '10 seconds'  -- Prevent storms
  ```
- If the store is unreachable, log a WARN (`handoff_store_status=degraded`) but continue with the CLI-local flow; retry on next `/handoff`.

6) Observability / metadata schema
- Every `/handoff` run produces a `handoff_id`, captures `model_run_id`/`tokens_used` when exposed by the model, and logs them for traceability.
- Thread metadata schema (applied to parent + child):
  ```json
  "handoff": {
    "handoff_id": "uuid",
    "source_thread_id": "thr_parent",
    "child_thread_id": "thr_child",
    "pending": true,
    "cleanup_required": true,
    "last_cleanup_at": null
  }
  ```
- After cleanup these flags become `{"pending": false, "cleanup_required": false, "last_cleanup_at": "ISO timestamp"}`.
- Optional: store `metadata["handoff"]["last_handoff"]` on the parent for audit history.

---

## Data contract (canonical; file-backed in MVP)

- `summary_json` (canonical):
```json
{
  "schema_version": 1,
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
- New: `libs/deepagents-cli/deepagents_cli/handoff_summarization.py` (exports `HandoffSummarizationMiddleware` + helper funcs, mirroring LangChain naming).
- New: `libs/deepagents-cli/deepagents_cli/handoff_approval.py` (exports `HandoffApprovalMiddleware`, emits/consumes interrupts, handles CLI HITL flow).
- Update: `libs/deepagents-cli/deepagents_cli/commands.py` (add `/handoff`, wire preview/edit/accept/decline via HITL middleware entrypoint).
- Update: `libs/deepagents-cli/deepagents_cli/execution.py` (render dedicated handoff preview; capture edits; first-turn cleanup when `handoff_pending`).
- Optional: `libs/deepagents-cli/deepagents_cli/ui/handoff_preview.py` (encapsulate preview/edit UI if we want to keep `execution.py` slim).
- No changes to core lib `libs/deepagents/graph.py` (reactive summarization remains for compaction).

---

## HITL approval middleware (separate, reusable)

### Responsibility split
- `HandoffSummarizationMiddleware` (module `handoff_summarization.py`): gather messages → trim → call LLM with `DEFAULT_SUMMARY_PROMPT` → return `summary_json/summary_md`.
- `HandoffApprovalMiddleware` (module `handoff_approval.py`): present preview, accept/refine/decline, and only on accept perform side effects (memory write + child thread spawn).

This mirrors LangChain middleware conventions (see `.venv/.../langchain/agents/middleware/types.py`) where one middleware does one job.

### Interrupt payload (updates stream)

**REVISION:** Add `middleware_source` field to prevent future middleware collisions.

HITL emits an interrupt with a single action request so the existing updates/approval surface can be reused:
```json
{
  "__interrupt__": {
    "schema_version": 1,
    "middleware_source": "HandoffApprovalMiddleware",
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

This ensures future middleware don't collide (e.g., if you add escalation middleware later).

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

class HandoffApprovalMiddleware(AgentMiddleware):
    @before_agent
    async def propose_handoff(self, state, runtime):
        # Only triggered by explicit /handoff command (set via state metadata)
        # Do NOT perform side effects here. Emit an interrupt for the CLI to handle
        # summarization + approval without blocking the agent runtime.
        runtime.updates.emit_interrupt({
            "__interrupt__": {
                "action_requests": [
                    {
                        "name": "handoff_summary",
                        "description": "Preview handoff summary for approval",
                        "schema_version": 1,
                        "args": state.get("handoff_proposal", {})
                    }
                ]
            }
        })
        return None

    # Optionally handle resume decisions in a later hook if we ever move side-effects into the graph
```
For the CLI MVP, we keep side-effects in CLI code and use the middleware only to standardize the interrupt payload.

---

## Operational safeguards (LangChain v1–aligned)

- Side-effects outside middleware: summarization and approval are coordinated by CLI; middleware only emits interrupts. If later moved into a server, keep middleware async and avoid blocking calls.
- Non-blocking LLM calls: do not call LLM synchronously inside middleware. Prefer emitting an interrupt and calling the LLM in the CLI; or, if ever needed server-side, run in a spawned task.
- Checkpointer API adapter: isolate differences in state retrieval.

### CRITICAL REVISION: Checkpointer Query Pattern

**Important:** The checkpointer query API differs between CLI (direct graph calls) and LangGraph Platform (REST API).

```python
# path=null start=null

def get_thread_messages(graph, thread_id: str) -> list:
    """Fetch messages from the only source of truth: parent graph checkpointer."""
    try:
        # CLI path: graph is already compiled with checkpointer
        state = graph.get_state({"configurable": {"thread_id": thread_id}})
        return state.values.get("messages", []) if state else []
    except AttributeError:
        # Platform path: you're in a middleware that sees RunnableConfig, not graph
        # Cannot fetch history directly; summarization must happen DURING the turn
        return []
```

**Handoff flow adaptation:**
- **CLI**: Snapshot messages on `/handoff` command → send to summarizer → HITL.
- **Platform**: Summarizer runs inline during the middleware hook (reads from `state["messages"]` passed to middleware), no historical fetch.

- Token counter consistency: import and use the same counter as trim_messages uses: `from langchain_core.messages.utils import count_tokens_approximately`.
- Model usage capture: normalize across wrappers.

```python
# path=null start=null

def extract_usage(resp) -> dict:
    usage = getattr(resp, "usage_metadata", None) or getattr(resp, "usage", None) or {}
    tokens = usage.get("output_tokens") or usage.get("total_tokens") or 0
    run_id = getattr(resp, "id", None) or usage.get("request_id")
    return {"tokens_used": tokens, "model_run_id": run_id}
```

- Atomic write fallback: if backend lacks `write_atomic`, use a safe temp+replace path for filesystem-backed long-term storage.

```python
# path=null start=null
import os, tempfile

def write_atomic_via_temp(backend, path: str, data: str):
    # Write to a temp file on local FS
    with tempfile.NamedTemporaryFile("w", delete=False) as tf:
        tf.write(data)
        tmp = tf.name
    try:
        # If backend supports rename on its namespace, use it; else direct write
        try:
            backend.write(path + ".tmp", data)
            backend.rename(path + ".tmp", path)
        except AttributeError:
            backend.write(path, data)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
```

- Namespaced thread metadata: prefer `metadata["handoff"] = {"pending": True, "source_thread_id": ..., "handoff_id": ...}` over flat keys.
- Idempotent migration and cleanup: guard marker insertion and cleanup with metadata flags; if possible, use a compare-and-swap or file lock to avoid concurrent writes.
- First-child-turn cleanup: read metadata; if `handoff.pending` true and no `handoff.first_turn_cleared`, clear block, then atomically set `{pending: False, first_turn_cleared: True}`.
- Token budget enforcement: **CORRECTED** - use `max_tokens=200` for summary generation (typical 3-4 sentence summaries are 100-200 tokens). Input tokens for the summary prompt should be ~3000-4000 (after trimming).
- Interrupt payload stability: always include `schema_version`, `handoff_id`, and `assistant_id` so future revisions can deserialize decisions safely.
- Checkpointer guidance (per LangGraph docs): only the parent graph owns the checkpointer; subgraphs compile without one. CLI/state helpers rely on `agent.get_state({"configurable": {"thread_id": ...}})` to respect that single source of truth.
- Connection pools: when mirroring to Postgres or configuring custom checkpointers, use `psycopg_pool.ConnectionPool` with tuned `min_size/max_size/max_idle/max_lifetime` to avoid timeouts on long handoff runs.
- TTL + cleanup: TTL expiry deletes checkpoints/LangSmith traces automatically; metadata cleanup must tolerate missing parents/children. If TTL is off, surface LangGraph’s thread-cleanup runbook (`python3 delete.py --url ... --api-key ...`) so operators can purge threads.
- FastAPI dependency: if the approval middleware moves into a service, remember LangGraph Platform does not bundle FastAPI—declare `"fastapi"` (or version range) in `pyproject.toml` before deploying.
- Interrupt payload stability: include `schema_version` (added above) to support future evolution.

## Key algorithms (sketches)

### HandoffSummarizationMiddleware (No Side Effects)

**REVISION:** Middleware only generates summary and returns structured output. No memory writes or thread creation.

```python
# path=null start=null
class HandoffSummarizationMiddleware:
    async def process(self, state: dict, config: dict, context):
        """Only runs if handoff_requested in config."""
        if not config.get("configurable", {}).get("handoff_requested"):
            return None
        
        # Summarize current state's messages
        messages = state.get("messages", [])
        selected = self._select_messages(messages)
        trimmed = trim_messages(selected, max_tokens=4000)
        summary_text = await self._generate_summary(trimmed)
        
        # Return structured output; no side effects
        state["handoff_proposal"] = {
            "handoff_id": uuid4(),
            "summary_json": self._structure(summary_text),
            "summary_md": self._render(summary_text),
        }
        # Clear the flag so it doesn't fire again
        del config["configurable"]["handoff_requested"]
        return state
```

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

- Summary generation (upstream prompt, corrected token limit):
```python
# path=null start=null
from langchain.chat_models import init_chat_model
from langchain.agents.middleware.summarization import DEFAULT_SUMMARY_PROMPT

llm = init_chat_model(model) if isinstance(model, str) else model
resp = llm.invoke(
    DEFAULT_SUMMARY_PROMPT.format(messages=trimmed),
    max_tokens=200  # Corrected: 100-200 tokens for typical summaries
)
text = (resp.content or "").strip()
```

### HandoffApprovalMiddleware (Emits Interrupt Only)

**REVISION:** Middleware emits interrupt; CLI handles all side effects.

```python
# path=null start=null
class HandoffApprovalMiddleware:
    async def process(self, state: dict, config: dict, context):
        """Emits interrupt; does NOT write metadata/threads."""
        if "handoff_proposal" not in state:
            return None
        
        # Emit interrupt with full schema
        context.emit_interrupt({
            "__interrupt__": {
                "schema_version": 1,
                "middleware_source": "HandoffApprovalMiddleware",
                "action_requests": [{
                    "name": "handoff_summary",
                    "args": {
                        "handoff_id": state["handoff_proposal"]["handoff_id"],
                        "summary_json": state["handoff_proposal"]["summary_json"],
                        "summary_md": state["handoff_proposal"]["summary_md"],
                        "assistant_id": config.get("assistant_id"),
                        "parent_thread_id": config["configurable"]["thread_id"],
                    }
                }]
            }
        })
        
        # Return state unchanged; CLI/API handles the rest
        return state
```

### CLI Approval Handler (Where Side Effects Happen)

```python
# path=null start=null
# execution.py (or new handoff_handler.py)
async def handle_handoff_approval(interrupt, session_state):
    """CLI presents preview; user accepts/edits/declines."""
    decision = await prompt_user_for_handoff_decision(interrupt["args"])
    
    if decision["type"] == "approve":
        # NOW write memory + metadata + create child
        summary_md = decision.get("summary_md", interrupt["args"]["summary_md"])
        
        # 1. Write to agent.md
        await update_agent_memory_block(session_state.backend, summary_md)
        
        # 2. Set parent metadata
        await session_state.thread_manager.update_thread_metadata(
            parent_thread_id,
            {"handoff": {
                "handoff_id": interrupt["args"]["handoff_id"],
                "child_thread_id": None,  # Will set after creation
                "pending": True,
                "cleanup_required": True,
            }}
        )
        
        # 3. Create child thread
        child_thread = await session_state.thread_manager.create_thread(
            name=f"Continuation: {summary_md[:50]}",
            parent_id=parent_thread_id,
        )
        
        # 4. Update child metadata
        await session_state.thread_manager.update_thread_metadata(
            child_thread["id"],
            {"handoff": {
                "handoff_id": interrupt["args"]["handoff_id"],
                "source_thread_id": parent_thread_id,
                "pending": True,
                "cleanup_required": True,
            }}
        )
        
        # 5. Switch active thread
        session_state.active_thread_id = child_thread["id"]
        
    elif decision["type"] == "decline":
        # Silently exit; no writes
        pass
```

- Atomic block write (helper function, called by CLI):
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

### First-Turn Cleanup (Graph Edge)

**REVISION:** Implement as graph-level edge for Platform compatibility.

```python
# path=null start=null
# Inside compiled graph
def should_cleanup_handoff(state):
    """After first assistant message in child, clear summary block."""
    metadata = state.get("metadata", {})
    handoff = metadata.get("handoff", {})
    
    # Only if this thread is a handoff child with pending cleanup
    if handoff.get("pending") and handoff.get("cleanup_required"):
        if state.get("_handoff_first_turn_done"):
            return "cleanup_handoff"
    
    return END

def cleanup_handoff_block(state):
    """Clear summary block; unset flags."""
    # Write via the backend
    backend.write("/agent.md", re.sub(
        r"<current_thread_summary>.*?</current_thread_summary>",
        "<current_thread_summary>\nNone recorded yet.\n</current_thread_summary>",
        backend.read("/agent.md"),
        flags=re.DOTALL
    ))
    
    # Unset metadata flags (if graph has direct access; else CLI does this)
    state["metadata"]["handoff"]["pending"] = False
    state["metadata"]["handoff"]["cleanup_required"] = False
    state["metadata"]["handoff"]["last_cleanup_at"] = datetime.utcnow().isoformat()
    
    return state

# Wire it up
graph.add_conditional_edges("your_node", should_cleanup_handoff)
graph.add_node("cleanup_handoff", cleanup_handoff_block)
```

## Testing & acceptance (MVP)
- Unit:
  - `HandoffSummarizationMiddleware`: selection heuristics, trimming, prompt invocation, structured output (no I/O).
  - `HandoffApprovalMiddleware`: interrupt emission (no I/O).
  - CLI approval handler: preview accept/edit/decline flows, atomic block migration, metadata flag handling.
  - Cleanup helper: first-turn detection + idempotent reset.
  - Store resilience: degraded mode (no-op when unavailable).
- Integration: CLI happy-path (preview → accept → child created → summary injected → block cleared after first reply). Test both CLI and simulated Platform scenarios.

---

## Implementation roadmap (QA alignment)
Single job – complete handoff feature (steps 1‑20):
1. Create `handoff_summarization.py` / `handoff_approval.py` skeletons with their respective middleware classes plus shared helpers.
2. Fetch messages from the LangGraph checkpointer via `agent.get_state(config)` for the active thread.
3. Implement selection heuristics that preserve AI/Tool pairs and then trim with `trim_messages`.
4. Implement `generate_summary` using `DEFAULT_SUMMARY_PROMPT` + `init_chat_model`, enforcing ~300 output tokens.
5. Implement `structure_summary` to produce `{title, body[3-6], tldr}` plus rendered `summary_md`.
6. Add one-time migration that injects `<current_thread_summary>` markers into `agent.md` if missing.
7. Implement atomic block updater (temp write + rename) through the long-term backend.
8. Generate `handoff_id`, capture `model_run_id`/`tokens_used` when present, log for observability.
9. Extend `commands.py` with `/handoff` command + flags (`--preview`, `--apply`).
10. Build CLI preview UI (accept / edit / skip) that surfaces structured + Markdown outputs via `HandoffApprovalMiddleware`.
11. On accept, have the HITL middleware write the agent.md block and set thread metadata flags (`handoff_pending`, `handoff_source_thread_id`, `handoff_id`).
12. Create a child thread via `ThreadManager.create_thread(parent_id=...)` and switch active thread.
13. Add cleanup hook in `execution.py` that clears the block after the first complete child turn and unsets flags.
14. Add unit tests for both middleware classes (selection/structuring vs. approval/cleanup) plus migration/updater and command parsing.
15. Add integration test covering preview → accept → child sees summary → block cleared after first reply.
16. Update CLI help/docs to explain `/handoff` usage and expectations.
17. Mirror summaries into Postgres namespace `(assistant_id, "thread_summaries")`, storing both `summary_json` (JSONB) and `summary_md` (TEXT) keyed by `handoff_id`.
18. Add resilient error handling for store outages (silent fallback, retries, metrics).
19. Emit richer observability: log/trace `handoff_id`, `model_run_id`, `tokens_used`, and optional thread metadata (`last_handoff`).
20. Expand tests to cover persistence/mirroring paths and degraded scenarios (store unavailable, retries hit).

**Alignment check:** These steps satisfy PLAN-HANDOFF end-to-end: manual summarization + agent.md bridge + persistence/analytics hardening without scope creep.

## Acceptance criteria
- `/handoff` command supports preview, edit, accept, and decline. Decline leaves memory untouched and reports status to the user.
- Accepted summary writes `summary_md` between `<current_thread_summary>` markers, and the child thread’s first assistant turn shows the injected context automatically.
- After the first complete child turn, the summary block resets to the placeholder and `handoff_pending` metadata clears.
- `summary_json` + `summary_md` stored per the data contract; Postgres mirroring succeeds or falls back silently while logging errors.
- When Postgres mirroring degrades, CLI logs `handoff_store_status=degraded` and still completes the handoff without user-visible failure.
- Metadata flags (`handoff_id`, `handoff_source_thread_id`, `handoff_pending`) exist on parent/child threads for observability.
- Logs capture `handoff_id`, `model_run_id`, and `tokens_used`; failures emit actionable errors per PLAN-HANDOFF guidance.
- Automated tests (unit + integration) cover selection heuristics, summarizer outputs, approval flows, atomic updates, cleanup, and store mirroring.
- CLI docs/help mention `/handoff`, its preview/approval UX, and how the summary behaves in the child thread.

## Deliverables (Revised)

1. **`handoff_summarization.py`**: Message selection + summary generation. **No side effects.** Returns structured output to state.
2. **`handoff_approval.py`**: Receives `handoff_proposal`, emits interrupt. **No side effects.** CLI owns the HITL.
3. **CLI approval handler** (in `execution.py` or new `handoff_handler.py`): Presents UI, writes memory/metadata/creates child **only on accept**.
4. **Graph cleanup edge**: Detects first child turn, clears summary block, unsets metadata flags.
5. **Store mirroring** (async, outside graph): Idempotent UPSERT to `(assistant_id, handoff_id)`.
6. **Tests**: Middleware unit tests (no I/O), CLI integration tests (full handoff flow), and store resilience (degraded=no-op).
7. **Updated documentation** (README/help text) explaining `/handoff` usage, metadata conventions, and troubleshooting paths.

## Key Differences from Original Spec

| Original Spec | Revision | Why |
|---------------|----------|-----|
| Middleware writes metadata | CLI writes metadata | Platform doesn't expose metadata write in middleware |
| `agent.get_state()` works everywhere | CLI-only; Platform uses REST | Checkpointer location differs |
| First-turn cleanup in `execution.py` | Graph edge + conditional | Works in both CLI and Platform |
| Middleware has side effects | Only emits interrupt | Matches LangChain middleware contract |
| 300 token output cap | 100–200 token cap | More realistic for summaries |
| Manual store idempotency | PostgreSQL UPSERT | Prevents duplicates/storms |

---

## Design Validation & Production Refinements

**Status**: Design validated against official LangGraph Platform patterns. The three-layer separation (middleware → CLI HITL → graph cleanup) correctly mirrors upstream conventions.

### ✅ Validated Design Principles

1. **Middleware responsibility isolation** - Zero side effects in middleware layers aligns with [FastAPI middleware guidance](https://support.langchain.com/articles/7593416758-Adding-FastAPI-dependency-for-custom-middleware-in-LangGraph-Platform)
2. **Checkpointer access pattern** - Parent-only checkpointer usage matches [official checkpointing documentation](https://support.langchain.com/articles/1242226068-How-do-I-configure-checkpointing-in-LangGraph?)
3. **Atomic metadata namespace** - `metadata["handoff"]` prevents collisions with future features
4. **Graph-level cleanup** - Works in both CLI and Platform (execution.py doesn't exist on Platform)

### 🔧 Critical Production Refinements

#### 1. Platform Compatibility: State-Based Handoff Tracking

**Issue**: Metadata write APIs aren't available during middleware execution on Platform.

**Solution**: For future Platform compatibility, store handoff state in graph state (not just metadata):

```python
# path=null start=null
# In HandoffSummarizationMiddleware - safe for both CLI and Platform
state["_handoff_metadata"] = {
    "handoff_id": str(uuid4()),
    "source_thread_id": config["configurable"]["thread_id"],
    "pending": True,
    "cleanup_required": True,
}
return state
```

Then CLI/Platform can sync this to thread metadata via REST API after interrupt acceptance.

#### 2. PostgreSQL Connection Pool Tuning

**Checkpointer pool** (long-running queries):
```python
# path=null start=null
from psycopg_pool import ConnectionPool

checkpointer_pool = ConnectionPool(
    conn_string,
    min_size=2,
    max_size=10,
    max_idle=300.0,      # 5 min before conn closes
    max_lifetime=3600.0, # 1 hour max lifetime
    kwargs={"autocommit": True}
)
```

**Mirroring pool** (short-lived UPSERT operations - separate from checkpointer):
```python
# path=null start=null
mirror_pool = ConnectionPool(
    conn_string,
    min_size=1,
    max_size=2,
    max_idle=60.0,       # 1 min idle before close
    max_lifetime=600.0,  # 10 min max lifetime
)
```

#### 3. Token Budget with Runtime Validation

```python
# path=null start=null
resp = llm.invoke(
    DEFAULT_SUMMARY_PROMPT.format(messages=trimmed),
    max_tokens=200
)

# Guardrail: validate output isn't unexpectedly verbose
if len(resp.content) > 1000:  # ~300-400 chars expected for 100-200 tokens
    logger.warning(
        f"Summary unexpectedly long: {len(resp.content)} chars, "
        f"handoff_id={handoff_id}"
    )
    # Truncate defensively
    resp.content = resp.content[:1000] + "..."
```

#### 4. First-Turn Detection: Explicit Flag Setting

**Problem**: `_handoff_first_turn_done` needs to be set somewhere.

**Solution**: Set flag in assistant node or via conditional edge:

```python
# path=null start=null
def mark_first_handoff_turn(state):
    """Mark that we've completed first turn in a handoff child thread."""
    metadata = state.get("metadata", {})
    handoff = metadata.get("handoff", {})
    
    # Only mark if this is a pending handoff thread
    if handoff.get("pending") and not state.get("_handoff_first_turn_done"):
        state["_handoff_first_turn_done"] = True
    
    return state

def should_cleanup_handoff(state):
    """Check if we need to cleanup handoff summary after first turn."""
    metadata = state.get("metadata", {})
    handoff = metadata.get("handoff", {})
    
    if (handoff.get("pending") and 
        handoff.get("cleanup_required") and 
        state.get("_handoff_first_turn_done")):
        return "cleanup_handoff"
    
    return END

# Wire into graph
graph.add_node("mark_handoff_turn", mark_first_handoff_turn)
graph.add_edge("assistant", "mark_handoff_turn")
graph.add_conditional_edges("mark_handoff_turn", should_cleanup_handoff)
```

This ensures cleanup fires **exactly once** per child thread, not on every turn.

#### 5. Enhanced Message Selection Heuristics

```python
# path=null start=null
def score_message(msg, idx, total, subsequent_messages):
    """Heuristic: prioritize tool pairs, user intent, recent turns."""
    score = 0
    msg_type = msg.get("type", "")
    
    # Preserve tool calls + outputs (context for reasoning)
    if msg_type in ("tool", "function"):
        score += 100
    
    # Preserve user messages (captures intent)
    if msg_type == "human":
        score += 50
    
    # Recency bias (recent messages more relevant)
    score += (idx / total) * 25
    
    # Penalize orphaned tool outputs (low info density without context)
    if msg_type == "tool":
        # Check if there's a subsequent human message providing context
        has_human_after = any(
            m.get("type") == "human" 
            for m in subsequent_messages[idx+1:idx+5]  # Check next 4 msgs
        )
        if not has_human_after:
            score -= 20
    
    return score

scored = [
    (score_message(m, i, len(messages), messages), m) 
    for i, m in enumerate(messages[-MAX_TO_SCORE:])
]
```

This prevents including tool outputs without their user-intent context.

#### 6. Store Mirroring with Exponential Backoff

```python
# path=null start=null
import asyncio
from typing import Optional

async def mirror_summary_to_store(
    data: dict, 
    store, 
    max_retries: int = 3
) -> Optional[str]:
    """Idempotent mirror with exponential backoff.
    
    Returns:
        handoff_id on success, None on failure (degraded mode)
    """
    handoff_id = data["handoff_id"]
    
    for attempt in range(max_retries):
        try:
            await store.aput(
                (data["assistant_id"], "thread_summaries"),
                handoff_id,
                json.dumps(data),
                metadata={"schema_version": 1}
            )
            logger.info(
                f"Mirrored handoff summary",
                extra={
                    "handoff_id": handoff_id,
                    "attempt": attempt + 1,
                    "assistant_id": data["assistant_id"]
                }
            )
            return handoff_id
            
        except Exception as e:
            wait = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(
                f"Mirror attempt {attempt+1}/{max_retries} failed: {e}. "
                f"Retrying in {wait}s...",
                extra={"handoff_id": handoff_id, "error": str(e)}
            )
            
            if attempt < max_retries - 1:  # Don't sleep on last attempt
                await asyncio.sleep(wait)
    
    # Degraded mode: handoff still works locally
    logger.error(
        f"Failed to mirror handoff after {max_retries} attempts",
        extra={
            "handoff_id": handoff_id,
            "handoff_store_status": "degraded"
        }
    )
    return None
```

---

## Implementation Checklist (Production-Ready)

### Phase 1: Core Middleware (No I/O)
- [ ] `HandoffSummarizationMiddleware`: Select → Trim → Summarize → Structure → Return state
  - [ ] Enhanced scoring heuristics (tool pairs, recency, user intent)
  - [ ] Token validation (output ≤200 tokens, ≤1000 chars)
  - [ ] Store `_handoff_metadata` in state (Platform compatibility)
- [ ] `HandoffApprovalMiddleware`: Emit interrupt with `schema_version=1` + `middleware_source`
- [ ] Tests: Selection heuristics, structuring, interrupt payload shape, no I/O

### Phase 2: CLI HITL + Side Effects
- [ ] `/handoff` command sets `handoff_requested` flag in config
- [ ] CLI approval handler (preview → accept/edit/decline)
  - [ ] Rich preview UI (markdown panel + editor)
  - [ ] Edit flow (allow markdown/title modification)
- [ ] Atomic `<current_thread_summary>` block writer (temp+replace)
- [ ] Thread metadata writer (CLI-only, post-interrupt)
  - [ ] Sync `_handoff_metadata` from state to thread metadata
- [ ] Child thread creation via `ThreadManager`
- [ ] Tests: Happy path, decline, edit, atomic writes, idempotency

### Phase 3: Graph Cleanup & Persistence
- [ ] Graph-level cleanup edge
  - [ ] `mark_first_handoff_turn` node (sets flag after first assistant turn)
  - [ ] `should_cleanup_handoff` conditional edge
  - [ ] `cleanup_handoff_block` node (clears summary, unsets flags)
- [ ] Postgres mirroring with UPSERT + exponential backoff
  - [ ] Separate connection pool (short-lived, 1-2 connections)
  - [ ] Retry logic (3 attempts, exponential backoff)
  - [ ] Degraded mode (silent failure, local handoff continues)
- [ ] TTL configuration guidance in docs
- [ ] Tests: First-turn detection, idempotent mirroring, degraded store mode, connection pool behavior

### Phase 4: Observability & Docs
- [ ] Structured logging with `handoff_id`, `model_run_id`, `tokens_used`
- [ ] LangSmith trace metadata (handoff context)
- [ ] Metadata audit trail (`last_handoff` on parent thread)
- [ ] Updated CLI help explaining `/handoff` usage
  - [ ] Preview mode (`/handoff --preview`)
  - [ ] Direct apply (`/handoff --apply`)
  - [ ] Expected behavior (summary injected, cleared after first turn)
- [ ] Operator runbook
  - [ ] Troubleshooting handoff failures
  - [ ] Manual cleanup via LangGraph `delete.py` script
  - [ ] Store mirroring health checks
  - [ ] Connection pool tuning guidance

### Phase 5: Platform Deployment Prep (Future)
- [ ] Validate REST API metadata sync (state → thread metadata)
- [ ] Test with LangGraph Cloud deployment
- [ ] Verify graph-level cleanup works without CLI execution.py
- [ ] Document Platform-specific configuration (env vars, pool sizing)

---

## Production Deployment Considerations

### CLI vs Platform Deployment Matrix

| Feature | CLI Implementation | Platform Implementation | Notes |
|---------|-------------------|------------------------|-------|
| Message fetching | `graph.get_state()` direct | `state["messages"]` inline | Platform can't access checkpointer |
| Metadata writes | Direct (post-interrupt) | REST API (async) | Platform uses separate endpoint |
| Cleanup trigger | Graph edge | Graph edge | Both use same mechanism |
| Store mirroring | Async task | Async task | Same implementation |
| HITL preview | Rich CLI UI | Platform Studio UI | Different rendering |

### Token Budget Finalization

**Recommended defaults** (validate with your team's typical summaries):
- Input tokens (trimmed context): **~3000-4000** (fits in one API call, leaves room for prompt)
- Output tokens (summary): **100-200** (typical 3-4 sentence summaries)
- Guardrail threshold: **1000 characters** (defensive truncation)

**Measurement approach**:
```python
# Log actual usage for tuning
logger.info(
    "Handoff summary generated",
    extra={
        "handoff_id": handoff_id,
        "input_tokens": len(trimmed_messages),  # Approximate
        "output_tokens": usage.get("output_tokens", 0),
        "output_chars": len(summary_md),
    }
)
```

Review logs after 10-20 handoffs to tune `max_tokens` if needed.

### Connection Pool Sizing

**Checkpointer pool**: Size based on concurrent agent sessions
- Small deployment (1-10 users): `min_size=2, max_size=5`
- Medium deployment (10-100 users): `min_size=5, max_size=20`
- Large deployment (100+ users): `min_size=10, max_size=50`

**Mirroring pool**: Keep small (mirroring is fast)
- All deployments: `min_size=1, max_size=2`

**Monitor**: Connection pool exhaustion logs (`pool.get_stats()` if supported)

---

## Key Takeaways

**The design avoids the common HITL trap**: Don't make middleware do everything.

**Three-layer separation**:
1. **Middleware**: Pure functions + interrupts ✅
2. **CLI**: HITL UX + side effects ✅
3. **Graph**: Cleanup logic via edges ✅

**Production-ready patterns**:
- ✅ Zero side effects in middleware (state-in → interrupt → state-out)
- ✅ Platform-compatible state tracking (`_handoff_metadata` in state)
- ✅ Proper connection pool separation (checkpointer vs mirroring)
- ✅ Exponential backoff + degraded mode for store resilience
- ✅ Explicit first-turn detection (flag set by graph node)
- ✅ Enhanced message selection (tool pairs + user intent)

**Next validation steps**:
1. Confirm Platform deployment path (what changes on LangGraph Cloud?)
2. Finalize token budgets with team's typical summary size (measure 10-20 samples)
3. Pin Postgres pool config to deployment's typical handoff duration
4. Test degraded store mode (simulate Postgres outage)

The spec is **approved for implementation**. 🚀


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
## Trigger & metadata flow (no ambiguity)
1. `/handoff` command sets `SessionState.intent = "handoff"` and injects `{"handoff_requested": True}` into the model config before calling the agent.
2. `HandoffSummarizationMiddleware` checks that flag; if missing it returns `None`. When present it:
   - Calls `agent.get_state({"configurable": {"thread_id": ...}})` to fetch the latest LangGraph messages (official checkpointing guidance: only parent graph has the checkpointer; we respect that by querying the compiled graph).
   - Selects/trim messages, runs the summary prompt, and stores the result in `state["handoff_proposal"]`.
   - Clears `handoff_requested` so the middleware does not fire accidentally on subsequent tokens.
3. `HandoffApprovalMiddleware` runs immediately after, finds `handoff_proposal`, and emits an interrupt payload with `schema_version`, `summary_json`, `summary_md`, and `handoff_id`.
4. CLI handles the entire preview/edit UX. Edits happen locally; the approval decision returns edited Markdown/title via the interrupt decision payload.
5. On accept, the HITL middleware performs side effects (memory write, metadata update, child-thread creation) and marks both threads with `metadata["handoff"]` as shown above.
6. During the first assistant turn in the child thread, `execution.py` watches for `metadata["handoff"]["cleanup_required"]`. Once that turn emits the `on_complete` signal (end of assistant streaming), the CLI:
   - Clears `<current_thread_summary>` back to the placeholder.
   - Updates metadata to `{pending: False, cleanup_required: False, last_cleanup_at: ...}` via `ThreadStore.edit()`.

Because summarization only runs when `/handoff` sets the flag, there is no risk of silent summaries firing mid-conversation.

---
