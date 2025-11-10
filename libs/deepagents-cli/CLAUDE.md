# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Overview

DeepAgents CLI is an interactive AI coding assistant built on LangGraph with persistent memory, file operations, and web search. The architecture is designed for both standalone CLI use and LangGraph server deployment with Studio debugging.

**Key Characteristic**: The same agent code runs in two modes (CLI and server) with different persistence layers but identical behavior.

---

## 🔬 MCP Research Workflow (MANDATORY FOR THIS CODEBASE)

**See `/Users/Jason/.claude/CLAUDE.md` for complete MCP workflow details.**

This CLI is built on LangGraph/LangChain with complex middleware patterns. **NEVER guess** based on general knowledge - use the research tools:

### Step 1: DeepWiki Index (PRIMARY - Interconnected Knowledge)
**Tool:** `mcp__deepwiki__ask_question` with repo `ASTXRTYS/index`

**Why critical for this codebase:**
- This CLI uses LangGraph execution patterns, LangChain middleware, and DeepAgents extensions
- The Index contains ALL THREE repos indexed together
- Questions get answers that understand how these systems interconnect

**Use for:**
- Middleware execution order and composition
- Interrupt patterns (HITL, handoff approval, refinement loops)
- State management and checkpointing
- How DeepAgents extends base LangChain patterns

### Step 2: LangChain Docs MCP (Verification)
**Tool:** `mcp__docs-langchain__SearchDocsByLangChain`

**Use for:**
- API signatures and parameters
- Official examples
- Latest method signatures

### The Workflow:
1. **DeepWiki FIRST** → Architectural understanding
2. **LangChain Docs** → API verification
3. **Implement** → With confidence
4. **Document** → Save to `/Users/Jason/.claude/memories/`

**Example:** Before implementing handoff refinement loop:
- DeepWiki: "How do interrupt() loops work for iterative refinement?"
- LangChain Docs: "Verify interrupt() signature and Command usage"
- Implement based on interconnected knowledge

---

## Development Commands

### Installation
```bash
# Install in editable mode (changes reflect immediately)
python3.11 -m pip install -e . --break-system-packages

# Verify installation
deepagents --help
```

### Running the CLI
```bash
# Standalone CLI (most common for development)
deepagents

# With specific agent profile
deepagents --agent myagent

# Auto-approve mode (no HITL prompts)
deepagents --auto-approve
```

### LangGraph Server (for Studio debugging)
```bash
# Terminal 1: Start server
langgraph dev

# Terminal 2: Use CLI (connects to server)
deepagents

# Or use helper scripts:
./start-dev.sh        # Server + CLI together
./start-dev-server.sh # Server only
./start-tmux.sh       # Split panes in tmux
```

### Studio UI
- URL: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
- Free for local development
- Provides visual graph execution, state inspection, time-travel debugging

### Testing
```bash
# Run tests (when test suite exists)
pytest

# Type checking
mypy deepagents_cli

# Linting
ruff check deepagents_cli
```

---

## Architecture Deep Dive

### The Dual-Mode Execution Pattern

**Location**: `execution.py:256-368`

**Critical Understanding**: The agent streams in dual mode (`["messages", "updates"]`) to handle both content and HITL interrupts in a single stream. This is NOT obvious from reading the code once.

```python
async for chunk in agent.astream(
    stream_input,
    stream_mode=["messages", "updates"],  # ← Dual mode is critical
    subgraphs=True,
    config=config,
):
    namespace, current_stream_mode, data = chunk  # ← 3-tuple unpacking

    if current_stream_mode == "updates":
        # Handle interrupts and todos here
        if "__interrupt__" in data:
            interrupt_occurred = True

    elif current_stream_mode == "messages":
        # Handle content streaming here
```

**Why This Matters**:
- `updates` stream contains interrupts (HITL) and state updates (todos)
- `messages` stream contains AI responses and tool calls
- Both must be processed in the same loop
- Breaking this pattern will break HITL functionality

### Tool Call Buffering Architecture

**Location**: `execution.py:224-492`

**The Problem**: Streaming tool calls arrive as partial chunks that must be assembled before display.

**The Solution**: A buffer keyed by chunk index that accumulates pieces:

```python
tool_call_buffers: dict[str | int, dict] = {}

# Each chunk updates the buffer
buffer = tool_call_buffers.setdefault(
    buffer_key,
    {"name": None, "id": None, "args": None, "args_parts": []},
)

# When complete, display once and remove from buffer
if buffer_complete:
    displayed_tool_ids.add(buffer_id)
    tool_call_buffers.pop(buffer_key, None)
    console.print(format_tool_display(...))
```

**Critical**:
- Tool calls must only be displayed ONCE (track with `displayed_tool_ids`)
- Args may come as JSON string chunks that need parsing
- Invalid JSON chunks are silently skipped (waiting for more data)

### Agent Creation: CLI vs Server

**Critical Architecture Decision**: The same `create_agent_with_config()` function serves both CLI and server, but they differ in persistence handling.

**CLI Mode** (`main.py:229`):
```python
# CLI creates agent WITH custom persistence
agent = create_agent_with_config(model, assistant_id, tools)
# This includes SqliteSaver checkpointer and PostgresStore
```

**Server Mode** (`graph.py:82-93`):
```python
# Server creates agent WITHOUT checkpointer/store
graph = create_deep_agent(
    model=model,
    system_prompt=_get_system_prompt(),
    tools=tools,
    backend=backend,
    middleware=agent_middleware,
    # NO checkpointer or store - server provides these
)
```

**Why**: LangGraph server v0.4.20+ explicitly rejects custom checkpointers. The server manages its own persistence for multi-instance deployments, while CLI uses local SQLite for single-user scenarios.

**Implication**: You CANNOT use the same graph instance for both CLI and server. They must be created separately.

### Three-Layer Persistence System

Understanding the persistence architecture requires reading `agent.py`, `graph.py`, and the `deepagents` library together.

**Layer 1: Thread-Level Checkpoints** (Conversation State)
- **Storage**: `~/.deepagents/{agent}/checkpoints.db` (SQLite)
- **Owned by**: `SqliteSaver` (CLI) or server's checkpointer
- **Contains**: Message history, agent state per thread
- **Scope**: Per conversation thread

**Layer 2: Cross-Thread File Storage** (/memories/)
- **Storage**: `~/.deepagents/{agent}/` (filesystem)
- **Owned by**: `FilesystemBackend` routed via `CompositeBackend`
- **Contains**: agent.md, memory files, persistent documents
- **Scope**: Shared across all threads for one agent

**Layer 3: Programmatic Store** (Long-term Memory)
- **Storage**: PostgreSQL database (`deepagents` db)
- **Owned by**: `PostgresStore`
- **Contains**: Structured data for cross-agent/cross-session memory
- **Scope**: Global, all agents share (currently underutilized)

**The Routing** (`agent.py:194-206`):
```python
# Long-term backend rooted at agent directory
long_term_backend = FilesystemBackend(root_dir=agent_dir, virtual_mode=True)

# Composite backend routes /memories/ to agent dir, rest to CWD
backend = CompositeBackend(
    default=FilesystemBackend(),  # Current working directory
    routes={"/memories/": long_term_backend}  # Agent's persistent storage
)
```

**Key Insight**: `/memories/` is a virtual path. When the agent calls `read_file("/memories/guide.md")`, it actually reads `~/.deepagents/{agent}/guide.md`.

### Middleware Stack Order

**Location**: `agent.py:204-307` (custom middleware) and `deepagents/graph.py` (base middleware)

**Critical**: Middleware order matters because each wraps the next in the chain.

**Order** (inside-out):
1. `TodoListMiddleware` - Adds write_todos tool
2. `FilesystemMiddleware` - Adds file operation tools
3. `SubAgentMiddleware` - Adds task tool
4. `SummarizationMiddleware` - Handles long conversations
5. `AnthropicPromptCachingMiddleware` - Enables caching
6. `PatchToolCallsMiddleware` - Fixes tool formatting
7. **Custom**: `AgentMemoryMiddleware` - Loads agent.md into system prompt
8. **Custom**: `ResumableShellToolMiddleware` - Adds shell tool
9. `HumanInTheLoopMiddleware` - HITL approvals (MUST BE LAST)

**Why HITL Must Be Last**: It needs to intercept tool calls AFTER all other middleware has processed them, so it sees the final tool call format.

**Critical Code Pattern** (`agent.py:292-307`):
```python
return create_deep_agent(
    model=model,
    system_prompt=system_prompt,
    tools=tools,
    backend=backend,
    middleware=agent_middleware,  # ← Our custom middleware goes here
    checkpointer=checkpointer,
    store=store,
    interrupt_on={...},  # ← HITL config (applied as final middleware)
)
```

### Thread Management Architecture

**The Three Systems That Must Stay in Sync**:

1. **Metadata** (`threads.json` via `ThreadStore`)
   - Owned by: `ThreadManager`
   - Contains: Thread names, timestamps, parent relationships, token counts
   - File: `~/.deepagents/{agent}/threads.json`

2. **Checkpoint Data** (conversation state)
   - Owned by: `SqliteSaver` (CLI) or LangGraph server
   - Contains: Message history, agent state
   - File: `~/.deepagents/{agent}/checkpoints.db` (CLI only)

3. **Server State** (when using LangGraph server)
   - Owned by: LangGraph server API
   - Contains: Server-managed threads
   - Accessed via: `/threads` API endpoints

**Reconciliation** (`thread_manager.py:460-542`):
- `reconcile_with_checkpointer()` syncs metadata with checkpoint reality
- Removes metadata for deleted checkpoints (with grace period)
- Adds metadata for orphaned checkpoints

**Critical**: When creating or forking threads, both local metadata AND server state must be updated:

```python
def create_thread(self, name: str | None = None) -> str:
    # 1. Create on server FIRST
    thread_id = create_thread_on_server(name=name)

    # 2. Then update local metadata
    with self.store.edit() as data:
        data.threads.append(metadata)
        data.current_thread_id = thread_id
```

### Human-in-the-Loop (HITL) System

**Architecture** (`agent.py:263-306` + `execution.py:40-156`):

1. **Config** (agent.py): Define which tools require approval and how to format them
   ```python
   interrupt_on={
       "shell": shell_interrupt_config,
       "write_file": write_file_interrupt_config,
       # ... more tools
   }
   ```

2. **Detection** (execution.py): Detect interrupts in updates stream
   ```python
   if "__interrupt__" in data:
       hitl_request = interrupt_data[0].value
       interrupt_occurred = True
   ```

3. **Approval UI** (execution.py:40-156): Arrow-key selector with preview
   - Shows custom-formatted description
   - For file operations: shows diff preview
   - User selects approve/reject with arrow keys or A/R keys

4. **Resumption** (execution.py:544-560): Resume agent with decision
   ```python
   stream_input = Command(resume=hitl_response)
   # Loop continues, restreaming from interrupt point
   ```

**Auto-Approve Mode**: Bypasses approval UI, auto-accepts all (session_state.auto_approve)

### File Operation Tracking

**Purpose**: Correlate tool calls with results, compute diffs, track metrics for display.

**Flow** (`file_ops.py` + `execution.py:222-365`):

1. **Start** (when tool call is displayed):
   ```python
   file_op_tracker.start_operation(buffer_name, parsed_args, buffer_id)
   # Captures "before" state if write/edit
   ```

2. **Complete** (when ToolMessage arrives):
   ```python
   record = file_op_tracker.complete_with_message(message)
   # Captures "after" state, computes diff, metrics
   ```

3. **Render** (if record complete):
   ```python
   render_file_operation(record)  # Shows concise summary + diff
   ```

**Key Insight**: Tracking happens DURING streaming, not after. The tracker correlates async tool calls with their eventual results.

### Server-CLI Communication

**Server API** (`server_client.py`):
- `is_server_available()` - Health check
- `create_thread_on_server()` - Create thread via API
- `fork_thread_on_server()` - Fork existing thread
- `get_thread_data()` - Fetch thread state/messages
- `start_server_if_needed()` - Auto-start server

**Integration Points**:
1. **Thread creation** - Always creates via server API when server available
2. **Thread metadata** - Enriches local metadata with server data (/threads command)
3. **Fallback** - CLI works without server, but thread features are limited

**Critical**: Server URLs are configurable via `LANGGRAPH_SERVER_URL` env var (default: `http://127.0.0.1:2024`)

### Input System Architecture

**Location**: `input.py`

**Components**:
1. **FilePathCompleter** - Activates on `@` prefix, provides path autocomplete
2. **CommandCompleter** - Activates on `/` prefix, provides slash command autocomplete
3. **Key Bindings**:
   - `Enter` - Submit (or apply completion if menu active)
   - `Alt+Enter` (ESC+Enter) - Insert newline
   - `Ctrl+E` - Open in external editor (nano)
   - `Ctrl+T` - Toggle auto-approve mode
   - `Backspace` - Retrigger completion if in @ or / context

**File Mention Parsing** (`input.py:100-124`):
- Pattern: `@file/path` (supports escaped spaces: `@file\ with\ spaces.txt`)
- Resolves relative to CWD
- Injects file contents into prompt automatically

**Bottom Toolbar** (`input.py:127-159`):
- Shows auto-approve status (color-coded)
- Shows "BASH MODE" when input starts with `!`
- Updates reactively when Ctrl+T pressed

---

## Critical Patterns and Conventions

### Pattern: Direct Object Construction for Long-Running Apps

**Anti-Pattern** (Don't Do This):
```python
# Context manager pattern is for scripts, NOT long-running apps
checkpointer = SqliteSaver.from_conn_string(db_path)  # Returns Iterator!
store = PostgresStore.from_conn_string(db_uri)        # Returns Iterator!
```

**Correct Pattern** (Do This):
```python
# Direct construction for CLI/server
import sqlite3
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()  # Initialize schema

import psycopg
pg_conn = psycopg.connect(database_url, autocommit=True)
store = PostgresStore(pg_conn)
store.setup()  # Initialize schema
```

**Why**: `from_conn_string()` returns a context manager (Iterator) designed for short-lived scripts. Long-running apps need direct connections.

### Pattern: Absolute Imports in graph.py

**Critical Rule**: `graph.py` MUST use absolute imports, not relative.

**Why**: LangGraph's module loader executes `graph.py` outside of package context, so relative imports fail.

```python
# ✅ CORRECT
from deepagents_cli.agent import create_agent_with_config
from deepagents_cli.tools import http_request, web_search

# ❌ WRONG - will break server
from .agent import create_agent_with_config
from .tools import http_request, web_search
```

### Pattern: Rich Console Singleton

**Location**: `config.py:59`

**Rule**: Always use the singleton console instance, never create new ones.

```python
# ✅ CORRECT
from .config import console
console.print("Hello")

# ❌ WRONG - creates separate console, breaks rendering
from rich.console import Console
Console().print("Hello")
```

**Why**: Multiple consoles interfere with spinner/status rendering, terminal state.

### Pattern: Tool Argument Formatting

**Location**: `ui.py:25-145`

**Rule**: Show users the MOST RELEVANT info, not all arguments.

```python
# read_file(file_path="/very/long/path/to/file.py", offset=100, limit=50)
# Displays as:
# read_file(file.py)  ← Just the filename

# web_search(query="how to use langgraph", max_results=5)
# Displays as:
# web_search("how to use langgraph")  ← Just the query
```

**Implementation**: `format_tool_display()` has custom logic per tool type.

### Pattern: Thread State Updates

**Rule**: Always update BOTH timestamp and current_thread_id when switching threads.

```python
# ✅ CORRECT
with self.store.edit() as data:
    thread["last_used"] = now          # Update timestamp
    data.current_thread_id = thread_id # Update current
```

**Why**: Ensures thread sorting and TTL cleanup work correctly.

---

## Common Gotchas and Pitfalls

### Gotcha: Forgetting to Flush Text Buffer

**Location**: `execution.py:231-244`

**Problem**: AI text accumulates in `pending_text` buffer, must be flushed before showing tool calls or diffs.

**Solution**: Always call `flush_text_buffer(final=True)` before rendering non-text content:

```python
# Before showing tool calls
flush_text_buffer(final=True)
console.print(f"  {icon} {display_str}")

# Before showing diffs
flush_text_buffer(final=True)
render_file_operation(record)
```

### Gotcha: Tool Call Deduplication

**Location**: `execution.py:224-492`

**Problem**: Same tool call can appear multiple times in chunks.

**Solution**: Track displayed IDs to prevent duplicates:

```python
displayed_tool_ids = set()

if buffer_id in displayed_tool_ids:
    continue  # Already shown

displayed_tool_ids.add(buffer_id)  # Mark as shown
```

### Gotcha: Server vs CLI Persistence Confusion

**Problem**: Expecting CLI checkpointer to work with server mode, or vice versa.

**Reality**: They use DIFFERENT persistence:
- CLI: Local SQLite (`checkpoints.db`)
- Server: Server-managed (API-based)

**Implication**: Threads created in CLI won't appear in server UI unless server is running during creation.

### Gotcha: Modifying checkpointer After Creation

**Anti-Pattern**:
```python
# This is what the broken /clear command did:
agent.checkpointer = InMemorySaver()  # ❌ DESTROYS PERSISTENCE
```

**Correct Approach**:
```python
# Create new thread instead
thread_manager.create_thread(name="New conversation")
thread_manager.switch_thread(new_thread_id)
```

**Why**: Replacing the checkpointer breaks all existing threads and their history.

### Gotcha: Async Event Loop Conflicts

**Location**: `commands.py:416-429`

**Problem**: Can't use `asyncio.run()` from inside a running event loop.

**Solution**: Check for existing loop and handle appropriately:

```python
try:
    loop = asyncio.get_running_loop()
    # Already in loop - run in thread pool
    with ThreadPoolExecutor() as executor:
        return executor.submit(asyncio.run, async_function()).result()
except RuntimeError:
    # No loop - safe to use asyncio.run()
    return asyncio.run(async_function())
```

---

## Key Files Reference

**Core Agent Logic**:
- `agent.py` - Agent creation, system prompts, HITL config (SHARED by CLI and server)
- `graph.py` - Server export (absolute imports only)
- `execution.py` - Dual-mode streaming, tool buffering, HITL flow

**User Interface**:
- `ui.py` - Rendering, formatting, token tracking
- `input.py` - Prompt session, completers, key bindings
- `commands.py` - Slash command handlers

**Persistence**:
- `thread_manager.py` - Thread lifecycle, metadata management
- `thread_store.py` - Atomic JSON file operations (used by ThreadManager)
- `agent_memory.py` - Memory middleware, loads agent.md

**Server Integration**:
- `server_client.py` - LangGraph API client
- `main.py` - CLI entry point, server detection

**Tools & Operations**:
- `tools.py` - http_request, web_search definitions
- `file_ops.py` - File operation tracking, diff computation

**Configuration**:
- `config.py` - Constants, colors, model creation, SessionState
- `.env` - API keys, database URLs (NOT in repo)
- `langgraph.json` - Server configuration

---

## Environment Variables

Required in `.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-...     # Claude API key
TAVILY_API_KEY=tvly-dev-...            # Optional - web search
LANGCHAIN_TRACING_V2=true              # LangSmith tracing
LANGCHAIN_API_KEY=lsv2_pt_...          # LangSmith API
LANGCHAIN_PROJECT=deepagents-cli       # LangSmith project
DEEPAGENTS_DATABASE_URL=postgresql://localhost/deepagents  # Optional - store
```

Optional:
```bash
LANGGRAPH_SERVER_URL=http://127.0.0.1:2024  # Server URL (default shown)
LANGGRAPH_SERVER_TIMEOUT=5.0                 # Server request timeout (seconds)
OPENAI_API_KEY=sk-...                        # Alternative to Anthropic
OPENAI_MODEL=gpt-5-mini                      # If using OpenAI
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929   # Override default Claude model
EDITOR=nano                                   # External editor (default: nano)
```

---

## Testing & Debugging

### Manual Testing Checklist

After making changes, verify:

- [ ] CLI starts without errors: `deepagents`
- [ ] Server starts and registers graph: `langgraph dev`
- [ ] Both can execute tasks (try a simple prompt)
- [ ] HITL prompts work (try `shell ls`)
- [ ] File operations work: `read_file`, `write_file`, `edit_file`
- [ ] `/memories/` path works: `ls /memories/`
- [ ] Thread commands: `/new`, `/threads`
- [ ] Token tracking: `/tokens`
- [ ] Auto-approve toggle: `Ctrl+T`
- [ ] File mentions: `@README.md what does this file explain?`
- [ ] Slash commands: `/help`, `/clear`

### Debugging Tips

**Agent not responding**:
- Check `.env` has `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- Check API key is valid (try in another context)
- Look for network errors in console output

**Server won't start**:
- Check port 2024 is available: `lsof -i :2024`
- Verify `.env` exists and is readable
- Check for import errors: `python -c "from deepagents_cli.graph import graph"`

**Persistence issues**:
- Check `~/.deepagents/{agent}/` directory exists
- Verify `checkpoints.db` has content: `sqlite3 ~/.deepagents/agent/checkpoints.db ".tables"`
- Check PostgreSQL is running: `brew services list | grep postgresql`

**Thread confusion**:
- Run reconciliation: Check `thread_manager.reconcile_with_checkpointer()`
- Verify threads.json is valid JSON
- Look for thread_id mismatches in logs

---

## Design Principles

1. **Simplicity**: Prefer straightforward implementations over clever abstractions
2. **Observability**: All important actions should be visible in the UI
3. **Fault Tolerance**: Gracefully handle missing files, network errors, corrupt data
4. **User Control**: HITL for potentially destructive operations (unless auto-approve)
5. **Performance**: Async I/O, concurrent API calls (LangSmith metrics), caching where appropriate
6. **Compatibility**: Same agent code runs in CLI and server contexts

---

## Future Considerations

**When Adding New Tools**:
1. Add to `tools.py` with docstring
2. Update `_get_default_tools()` in both `main.py` and `graph.py`
3. Add HITL config in `agent.py` if tool is destructive
4. Add custom formatting in `ui.py:format_tool_display()`
5. Add icon in `execution.py:tool_icons` dict

**When Adding New Middleware**:
1. Consider ORDER in middleware stack
2. Test with both CLI and server modes
3. Document any state additions
4. Verify HITL still works (middleware order matters)

**When Modifying Persistence**:
1. Consider migration path for existing users
2. Test thread reconciliation
3. Update backup/restore logic if applicable
4. Document database schema changes

**When Changing Streaming Logic**:
1. Test HITL flow thoroughly (easy to break)
2. Verify tool call buffering still works
3. Check spinner/status updates still render
4. Ensure text buffer flushing happens correctly

---

## Summary

This CLI is built around a **dual-mode streaming pattern** that handles both content and interrupts, with **three-layer persistence** (checkpoints, filesystem, store), a **carefully ordered middleware stack**, and **two deployment modes** (CLI and server) using the same core agent code. Understanding the **tool call buffering**, **HITL interrupt flow**, and **thread management synchronization** is critical to working effectively with this codebase.
