# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Commands

### Development Setup
```bash
# Install package in editable mode
python3.11 -m pip install -e . --break-system-packages

# Setup environment
cp .env.example .env  # Create and configure with API keys

# Setup PostgreSQL (required for long-term memory store)
brew services start postgresql@14
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents
```

### Testing
```bash
# Run all tests
make test

# Run specific test file
make test TEST_FILE=tests/test_thread_manager.py

# Run single test
uv run pytest tests/test_thread_manager.py::test_touch_thread_updates_last_used
```

### Linting & Formatting
```bash
# Format code
make format

# Check linting
make lint

# Format only changed files (vs master)
make format_diff
```

### Running the CLI
```bash
# Start LangGraph dev server (terminal 1)
langgraph dev
# or: ./start-dev-server.sh

# Start CLI (terminal 2)
deepagents
# or: deepagents --agent myagent
# or: deepagents --auto-approve

# Start both in tmux split panes
./start-tmux.sh
```

## High-Level Architecture

### Dual Deployment Model

This codebase supports **two distinct deployment modes** with **one shared agent creation function**:

1. **CLI Mode** (`main.py`): Interactive terminal interface with local SQLite persistence
2. **LangGraph Server Mode** (`graph.py`): REST API + Studio UI with server-managed persistence

**Critical Pattern**: Both modes MUST use the same agent creation logic from `agent.py:create_agent_with_config()` to ensure consistency.

### Persistence Architecture: Three Independent Layers

The agent uses three separate persistence systems:

#### 1. Thread Checkpointing (Conversation State)
- **Purpose**: Preserves conversation history and enables resumability
- **CLI Storage**: SQLite at `~/.deepagents/{agent}/checkpoints.db` (via `SqliteSaver`)
- **Server Storage**: Server-managed (LangGraph handles this automatically)
- **Scope**: Per-thread (each conversation has a unique thread_id)

#### 2. Long-Term Memory (Cross-Conversation Data)
- **Purpose**: Knowledge that persists across all conversations
- **Current Implementation**: `FilesystemBackend` at `~/.deepagents/{agent}/` (via `/memories/` virtual path)
- **Ready-but-Unused**: PostgreSQL via `PostgresStore` (infrastructure exists, not currently used)
- **Scope**: Cross-thread, available to all conversations
- **Agent Access**: `ls /memories/`, `write_file /memories/guide.md`, etc.

#### 3. Thread Metadata (Management Info)
- **Purpose**: Thread lifecycle management (creation time, names, parent relationships)
- **Storage**: JSON file at `~/.deepagents/{agent}/threads.json`
- **Managed By**: `ThreadManager` class with atomic file locking via `ThreadStore`
- **Scope**: Per-agent, tracks all threads for an agent

**Key Insight**: These three layers are intentionally separate. CLI and Server use different checkpointing systems by design, but can share the same long-term memory filesystem.

### Middleware Stack

Middleware order is critical. The stack is built in this sequence (from `create_deep_agent()` in DeepAgents library):

**From DeepAgents Library** (in order):
1. `TodoListMiddleware` - Provides `write_todos` tool
2. `FilesystemMiddleware` - File operations (read/write/edit)
3. `SubAgentMiddleware` - Provides `task` tool for spawning subagents
4. `SummarizationMiddleware` - Conversation summarization
5. `AnthropicPromptCachingMiddleware` - Prompt caching optimization
6. `PatchToolCallsMiddleware` - Fixes tool call formatting issues
7. **Custom middleware** (passed as parameter)
8. `HumanInTheLoopMiddleware` - Tool approval prompts (final layer)

**Custom Middleware** (added via `create_agent_with_config()`):
- `HandoffApprovalMiddleware` - Thread handoff approval workflow
- `HandoffSummarizationMiddleware` - Summarizes before handoff
- `HandoffToolMiddleware` - Provides handoff tool
- `HandoffCleanupMiddleware` - Cleans up handoff state
- `AgentMemoryMiddleware` - Manages `/memories/` virtual path routing
- `ResumableShellToolMiddleware` - Shell command execution with approval

Middleware hooks execute in reverse order for `after_*` hooks (see LangChain docs for details).

### Backend Routing: Virtual Paths

The CLI uses `CompositeBackend` to route file operations:

```python
backend = CompositeBackend(
    default=FilesystemBackend(),  # CWD operations (regular files)
    routes={
        "/memories/": long_term_backend  # ~/.deepagents/{agent}/ (persistent)
    }
)
```

**Usage by Agent**:
- `ls /memories/` → Lists `~/.deepagents/{agent}/`
- `read_file /memories/guide.md` → Reads from agent storage
- `write_file /memories/note.txt` → Writes to agent storage
- `ls` → Lists current working directory
- `read_file main.py` → Reads from current working directory

## Critical Implementation Details

### 1. graph.py MUST Use Absolute Imports

**Problem**: LangGraph's module loader executes `graph.py` outside of package context.

**Solution**: Always use absolute imports in `graph.py`:

```python
# ✅ CORRECT
from deepagents_cli.agent import create_agent_with_config
from deepagents_cli.tools import http_request, web_search

# ❌ WRONG - causes ImportError
from .agent import create_agent_with_config
from .tools import http_request, web_search
```

This is the ONLY file with this restriction. All other files can use relative imports normally.

### 2. CLI and Server Have Different Checkpointers

**By Design**: The CLI uses `SqliteSaver` with a local database, while LangGraph Server manages its own checkpointer.

**Do NOT** try to make them share the same checkpointer. This is intentional separation:
- CLI checkpoints: `~/.deepagents/{agent}/checkpoints.db`
- Server checkpoints: Managed by LangGraph Server (separate database)

**LangGraph v0.4.20+ explicitly rejects custom checkpointers** when `graph.py` is loaded by the server. The warning is expected and correct:

```
Your graph includes a custom checkpointer... will be ignored when deployed
```

### 3. Connection Objects vs Context Managers

For long-running applications like the CLI, initialize checkpoint/store with connection objects:

```python
# ✅ CORRECT - for CLI (long-running)
import sqlite3
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()

# ❌ WRONG - for scripts only (short-lived)
with SqliteSaver.from_conn_string(db_uri) as checkpointer:
    # Only for one-off scripts, not persistent CLI
```

The `from_conn_string()` methods return context managers (iterators), not direct instances.

### 4. Thread ID Format

Threads use pure UUIDs (LangGraph standard):
- Format: `"550e8400-e29b-41d4-a716-446655440000"`
- Generated via `create_thread_on_server()` or `fork_thread_on_server()`
- Stored in `threads.json` with metadata (name, parent_id, etc.)

Thread switching is managed by `ThreadManager`, not by creating new agents.

### 5. Tool Approval Flow

Tools requiring HITL approval (configured in `agent.py:create_agent_with_config()`):
- `shell` - Shell command execution
- `write_file` - File writing/overwriting
- `edit_file` - File editing
- `web_search` - Web search (uses Tavily API credits)
- `task` - Subagent spawning
- `handoff` - Thread handoff to another agent

Each has a custom formatting function for rich approval previews (see `file_ops.py`).

Auto-approve mode (`--auto-approve` flag) disables all HITL prompts.

### 6. Environment Configuration

The `.env` file is loaded by both CLI and server (specified in `langgraph.json`):

**Required Variables**:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=deepagents-cli
```

**Optional Variables**:
```bash
TAVILY_API_KEY=tvly-dev-...  # For web_search tool
DEEPAGENTS_DATABASE_URL=postgresql://localhost/deepagents  # For PostgresStore
```

## Testing Patterns

### Test Structure
- Unit tests use `pytest` with fixtures from `conftest.py`
- Socket access disabled by default (`--disable-socket --allow-unix-socket`)
- 10-second timeout per test (`--timeout 10`)
- Mocking via `pytest-mock` and `unittest.mock`

### Common Test Patterns

**Thread Manager Tests** (`test_thread_manager.py`):
```python
# Mock server API calls
@patch("deepagents_cli.server_client.create_thread_on_server")
def test_something(mock_create, tmp_path):
    mock_create.return_value = str(uuid.uuid4())
    manager = ThreadManager(tmp_path / "agent", "test-agent")
    # ...
```

**Checkpointer Interaction**:
```python
# Insert test checkpoints directly
def _insert_checkpoint(db_path, thread_id: str):
    conn = sqlite3.connect(str(db_path))
    saver = SqliteSaver(conn)
    saver.setup()
    # ... insert checkpoint data
```

### Test Isolation

Each test should:
- Use `tmp_path` fixture for isolated file operations
- Mock external API calls (LangGraph server, Anthropic, Tavily)
- Clean up any created threads/checkpoints
- Avoid relying on `~/.deepagents/` (use temp directories)

## Common Development Tasks

### Adding a New Tool

1. Define tool in `tools.py`:
```python
@tool
def my_tool(arg: str) -> str:
    """Tool description."""
    return result
```

2. Add to tool list in `agent.py:create_agent_with_config()`:
```python
tools = [http_request, my_tool]
```

3. Update `graph.py:_get_default_tools()` to match (keep CLI and server in sync)

4. If tool needs approval, add to `interrupt_on` config in `create_agent_with_config()`

### Adding Custom Middleware

1. Create middleware class extending `AgentMiddleware` (see `agent_memory.py` for example)

2. Add to middleware list in `agent.py:create_agent_with_config()`:
```python
agent_middleware = [
    AgentMemoryMiddleware(...),
    MyCustomMiddleware(...),
    shell_middleware,
]
```

3. Update `graph.py` middleware list to match

4. Remember: middleware order matters! Place carefully in the stack.

### Adding a Slash Command

1. Add handler function in `commands.py`:
```python
async def handle_my_command(args: list[str], session_state: SessionState) -> bool:
    # Implementation
    return True  # Continue CLI loop
```

2. Add command to `COMMAND_HANDLERS` dict:
```python
COMMAND_HANDLERS = {
    # ...
    "mycommand": handle_my_command,
}
```

3. Update help text in `ui.py:show_help()`

### Modifying Thread Management

Thread lifecycle is managed by `ThreadManager` class:
- Thread creation: `create_thread(name=None)` → calls server API
- Thread forking: `fork_thread(parent_id, name=None)` → calls server API
- Thread switching: `switch_thread(thread_id)` → updates current_thread_id
- Metadata sync: `sync_with_checkpointer(agent)` → reconciles threads.json with SQLite

All metadata operations go through `ThreadStore` (atomic file locking with `filelock`).

## Known Issues and Gotchas

### Issue: Import Error in graph.py
**Symptom**: `ImportError: attempted relative import with no known parent package`
**Cause**: Relative imports in `graph.py` (LangGraph module loader limitation)
**Solution**: Use absolute imports in `graph.py` only

### Issue: Server Rejects Custom Checkpointer
**Symptom**: Warning about custom checkpointer being ignored
**Cause**: LangGraph Server v0.4.20+ manages its own checkpointer
**Solution**: This is expected behavior. Do NOT pass `checkpointer=` to `create_deep_agent()` in `graph.py`

### Issue: Threads Not Persisting
**Symptom**: Threads disappear after CLI restart
**Cause**: Thread metadata only in memory, not saved
**Solution**: Check `threads.json` exists and `ThreadStore` is working correctly

### Issue: /clear Command Corrupts Persistence
**Symptom**: After `/clear`, agent forgets everything permanently
**Cause**: Old implementation replaced `SqliteSaver` with `InMemorySaver`
**Solution**: Now fixed - `/clear` uses `create_thread()` to start fresh thread

## LangGraph Studio Integration

The dev server provides free visual debugging:

1. Start server: `langgraph dev`
2. Open Studio: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
3. Features:
   - Visual graph execution flow
   - Step-by-step debugging
   - State inspection at each node
   - Time-travel debugging (rewind/replay)
   - Interrupt handling visualization

Studio uses the server's checkpointer (not CLI's SQLite), so threads created in Studio are separate from CLI threads.

## File Structure Quick Reference

| Path | Purpose |
|------|---------|
| `agent.py` | **Core**: Agent creation shared by CLI & server |
| `graph.py` | **Critical**: Server export (absolute imports only) |
| `main.py` | CLI entry point and interactive loop |
| `execution.py` | Task execution, streaming, tool approval logic |
| `thread_manager.py` | Thread lifecycle management |
| `thread_store.py` | Atomic JSON file operations for thread metadata |
| `commands.py` | Slash command handlers (/new, /threads, etc.) |
| `tools.py` | Tool definitions (http_request, web_search) |
| `agent_memory.py` | Memory middleware for /memories/ routing |
| `config.py` | Configuration, styling, model creation |
| `ui.py` | Rich UI rendering and token tracking |
| `input.py` | Prompt session and keybindings |
| `file_ops.py` | File operation preview and approval UI |
| `langgraph.json` | Server config (graph export path, .env path, TTL settings) |
| `~/.deepagents/{agent}/` | Agent storage (checkpoints.db, threads.json, memory files) |

## Architecture Decision Records

### Why Separate CLI and Server Checkpointers?

**Decision**: CLI uses local SQLite (`~/.deepagents/{agent}/checkpoints.db`), Server uses its own managed checkpointer.

**Rationale**:
- CLI needs offline capability and local persistence
- Server needs multi-user isolation and scalability
- Sharing would create file locking conflicts
- LangGraph Server explicitly rejects custom checkpointers in v0.4.20+

**Implication**: Threads created in CLI are separate from threads in Studio. This is by design.

### Why FilesystemBackend for Long-Term Memory?

**Decision**: Use `FilesystemBackend` for `/memories/` instead of `PostgresStore`.

**Rationale**:
- Simple deployment for personal/local use
- No database setup required
- Easy to inspect and debug (plain files)
- PostgresStore ready for future multi-user deployment

**Implication**: For multi-customer deployment, switch to `StoreBackend` wrapping `PostgresStore`.

### Why Middleware for Tool Approval?

**Decision**: Use `HumanInTheLoopMiddleware` + custom formatters instead of tool-level approval logic.

**Rationale**:
- Separation of concerns (tools don't know about approval)
- Consistent approval UX across all tools
- Middleware can be easily disabled (auto-approve mode)
- Centralized approval logic in one place

**Implication**: All tools requiring approval must be listed in `interrupt_on` config in `agent.py`.
