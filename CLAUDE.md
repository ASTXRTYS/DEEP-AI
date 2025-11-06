# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Repository Overview

**What**: Deep Agents - A general-purpose "deep agent" framework built on LangGraph with planning, file system access, and subagent spawning capabilities. Inspired by Claude Code.

**Location**: `/Users/Jason/astxrtys/DevTools/deepagents`

**Structure**: UV workspace monorepo with two packages:
- `libs/deepagents/` - Core library implementing deep agent primitives
- `libs/deepagents-cli/` - CLI application for interactive coding assistance

**Origin**: Fork of LangChain's `deepagents` repository with custom enhancements (thread management, TTL cleanup, LangSmith metrics)

---

## Git Workflow

### Remotes
```bash
origin   → https://github.com/langchain-ai/deepagents.git  # LangChain upstream (read-only)
upstream → git@github.com:ASTXRTYS/DEEP-AI.git             # Your fork (read-write)
```

### Common Operations

**Pull latest from LangChain**:
```bash
git fetch origin
git merge origin/master  # Review UPSTREAM_SYNC_ANALYSIS.md first
```

**Push your changes**:
```bash
git push upstream <branch-name>
```

**Check for conflicts before merging**:
```bash
git fetch origin
git merge --no-commit --no-ff origin/master
git merge --abort  # If you just wanted to test
```

**Important**: Always check `UPSTREAM_SYNC_ANALYSIS.md` before merging upstream changes to understand what's coming in.

---

## Development Setup

### 1. Install Dependencies

```bash
# Install with all dependency groups
uv sync --all-groups

# Or use pip (from root)
python3.11 -m pip install -e . --break-system-packages
```

### 2. Install CLI Package

```bash
cd libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

### 3. Environment Configuration

Create `libs/deepagents-cli/.env` with:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
TAVILY_API_KEY=tvly-dev-...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=deepagents-cli
DEEPAGENTS_DATABASE_URL=postgresql://localhost/deepagents
```

### 4. PostgreSQL Setup (for CLI long-term memory)

```bash
brew services start postgresql@14
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents
```

---

## Build & Test Commands

### Linting & Formatting

```bash
# Format all Python files
make format

# Lint with ruff and mypy (full)
make lint

# Lint only the deepagents package
make lint_package

# Lint tests only
make lint_tests

# Lint only changed files vs master
make lint_diff
```

### Testing

```bash
# Run unit tests with coverage
make test

# Run integration tests
make integration_test

# Run specific test file
uv run pytest libs/deepagents/tests/unit_tests/test_specific.py

# Run with verbose output
uv run pytest libs/deepagents/tests/unit_tests -v

# Run CLI tests
cd libs/deepagents-cli
uv run pytest tests/
```

### Linting Configuration

**Ruff**: Strict linting with ALL rules enabled, specific ignores for practicality
- Line length: 150 chars (core lib), 100 chars (CLI)
- Docstring format: Google style
- See `pyproject.toml` for specific ignores (COM812, ISC001, etc.)

**Mypy**: Strict type checking for core library, relaxed for CLI
- Core lib: `strict = true`
- CLI: `strict = false` with many disabled checks (pragmatic for CLI code)

---

## Architecture

### Core Concepts

**Deep Agents** = Planning + File System + Subagents + Detailed Prompt

1. **Planning**: TodoListMiddleware provides `write_todos` tool for task tracking
2. **File System**: FilesystemMiddleware provides `ls`, `read_file`, `write_file`, `edit_file`, `glob_search`, `grep_search`
3. **Subagents**: SubAgentMiddleware enables spawning specialized agents via `task` tool
4. **Prompts**: Comprehensive system prompts inspired by Claude Code

### Middleware Stack

Middleware is applied in this order (from `libs/deepagents/graph.py:create_deep_agent()`):

```python
[
    TodoListMiddleware(),                        # Planning tool
    FilesystemMiddleware(backend=backend),       # File operations
    SubAgentMiddleware(...),                     # Subagent spawning
    SummarizationMiddleware(...),               # Context compression
    AnthropicPromptCachingMiddleware(...),      # Prompt caching
    PatchToolCallsMiddleware(),                 # Tool call formatting
    *custom_middleware,                          # Your middleware
    HumanInTheLoopMiddleware(interrupt_on=...),  # HITL (if configured)
]
```

**Key Point**: Middleware order matters! Each middleware wraps the next, so early middleware sees all events.

### Backend Architecture

Backends handle file storage for agents. Three types:

1. **FilesystemBackend**: Stores files on disk (default, used by CLI)
   - Simple, works great for single-user/local deployment
   - CLI uses composite routing: CWD for default, `~/.deepagents/{agent}/` for `/memories/`

2. **StateBackend**: Stores files in LangGraph state (memory)
   - Useful for agents that don't need persistence
   - Files disappear when conversation ends

3. **StoreBackend**: Stores files in LangGraph Store (database)
   - For multi-instance/cloud deployments
   - Requires PostgreSQL
   - Currently not used by CLI but infrastructure is ready

**CompositeBackend**: Routes paths to different backends
```python
CompositeBackend(
    default=FilesystemBackend(),           # Regular file ops in CWD
    routes={
        "/memories/": FilesystemBackend(   # Agent's persistent storage
            root_dir="~/.deepagents/agent/"
        )
    }
)
```

### Persistence Architecture (CLI)

The CLI uses three storage layers:

1. **Checkpointing** (conversation state):
   - Storage: SQLite at `~/.deepagents/{agent_name}/checkpoints.db`
   - Purpose: Resume conversations across sessions
   - Scope: Per-thread (each thread has unique ID)
   - Implementation: `SqliteSaver` from `langgraph.checkpoint.sqlite`

2. **File Backend** (agent memory files):
   - Storage: `~/.deepagents/{agent_name}/` directory
   - Purpose: Persistent files accessible via `/memories/` prefix
   - Scope: Per-agent (shared across all threads of that agent)
   - Implementation: `FilesystemBackend` with routing

3. **Store** (long-term knowledge):
   - Storage: PostgreSQL database (shared across all agents)
   - Purpose: Cross-agent, cross-thread persistent storage
   - Status: Infrastructure ready, not actively used yet
   - Implementation: `PostgresStore` from `langgraph.store.postgres`

**Important**: Use direct construction for long-running apps (CLI/server):
```python
# ✅ Correct for CLI
import sqlite3
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()

# ❌ Wrong - context manager is for scripts only
with SqliteSaver.from_conn_string(db_uri) as checkpointer:
    ...  # CLI would exit when context closes
```

---

## Package Structure

### libs/deepagents/ (Core Library)

```
deepagents/
├── __init__.py           # Exports create_deep_agent
├── graph.py              # Main factory: create_deep_agent()
├── backends/
│   ├── protocol.py       # BackendProtocol interface
│   ├── filesystem.py     # FilesystemBackend
│   ├── state.py          # StateBackend
│   ├── store.py          # StoreBackend
│   ├── composite.py      # CompositeBackend (routing)
│   └── utils.py          # Helper functions
└── middleware/
    ├── filesystem.py     # FilesystemMiddleware (file tools)
    ├── subagents.py      # SubAgentMiddleware (task tool)
    ├── resumable_shell.py # ResumableShellToolMiddleware
    └── patch_tool_calls.py # PatchToolCallsMiddleware
```

### libs/deepagents-cli/ (CLI Application)

```
deepagents_cli/
├── __init__.py           # Exports cli_main
├── __main__.py           # Entry point for `python -m`
├── agent.py              # ⭐ Agent creation (shared by CLI & server)
├── graph.py              # ⭐ LangGraph server export
├── tools.py              # http_request, web_search tools
├── main.py               # CLI main loop
├── execution.py          # Task execution logic
├── ui.py                 # Rich UI rendering
├── input.py              # Prompt handling (prompt_toolkit)
├── commands.py           # Slash command handlers
├── config.py             # Configuration & styling
├── thread_manager.py     # Thread lifecycle management
├── thread_store.py       # Thread metadata persistence
├── agent_memory.py       # AgentMemoryMiddleware
├── resumable_shell_async.py # Async shell middleware
├── file_ops.py           # File operation utilities
├── token_utils.py        # Token counting
├── server_client.py      # LangGraph server client
├── langgraph.json        # Server configuration
├── .env                  # Environment variables (gitignored)
└── default_agent_prompt.md # Default system prompt
```

---

## Critical Implementation Details

### 1. Agent Creation Must Be Shared (CLI & Server)

**Rule**: Both CLI and LangGraph server MUST use the same agent creation logic.

**Why**: Ensures the server runs the EXACT same agent as the CLI, preventing configuration drift.

**Implementation**:
- `agent.py:create_agent_with_config()` - Single source of truth
- `graph.py` imports and wraps this function for server export
- Both paths get identical model, tools, middleware, HITL configuration

**Example**:
```python
# ✅ Correct: Both use create_agent_with_config
# CLI (main.py)
from .agent import create_agent_with_config
agent = create_agent_with_config(assistant_id, ...)

# Server (graph.py)
from deepagents_cli.agent import create_agent_with_config
graph = create_agent_with_config("agent", ...)
```

### 2. Import Rules for graph.py

**Rule**: `graph.py` MUST use ABSOLUTE imports, NOT relative imports.

**Why**: LangGraph's module loader executes `graph.py` outside of package context.

```python
# ✅ Correct
from deepagents_cli.agent import create_agent_with_config
from deepagents_cli.tools import http_request, web_search

# ❌ Wrong - will break LangGraph server
from .agent import create_agent_with_config
from .tools import http_request, web_search
```

**Error if you get it wrong**: `ImportError: attempted relative import with no known parent package`

### 3. Model Configuration

**Core Library Default** (`libs/deepagents/graph.py`):
```python
ChatAnthropic(
    model_name="claude-sonnet-4-5-20250929",
    max_tokens=20000,
)
```

**CLI Configuration** (`libs/deepagents-cli/deepagents_cli/config.py`):
```python
ChatAnthropic(
    model="claude-sonnet-4-5-20250929",
    max_tokens=8000,
    temperature=0,
    timeout=60,
    max_retries=2,
)
```

**Note**: CLI uses lower max_tokens for cost control. Adjust based on your needs.

### 4. Thread Management (CLI Feature)

**Thread ID Format**: Pure UUID (e.g., `a3f0c4d2-1b5e-4a7c-9d8e-2f3b1c4a5d6e`)

**Storage**:
- Thread metadata: `~/.deepagents/{agent_name}/threads.json`
- Checkpoints: `~/.deepagents/{agent_name}/checkpoints.db`

**Commands**:
- `/new [name]` - Create new thread
- `/threads` - Interactive picker (shows name, date, message count, tokens)
- `/threads continue <id>` - Switch to thread
- `/threads fork [name]` - Fork current thread
- `/threads info [id]` - Show thread details
- `/threads rename <id> <name>` - Rename thread

**Implementation**: `thread_manager.py:ThreadManager` class

### 5. Subagent Configuration

**SubAgent Schema**:
```python
{
    "name": str,              # How main agent calls it
    "description": str,        # When to use it
    "prompt": str,            # Subagent system prompt
    "tools": List[...],       # Subagent-specific tools
    "model": Optional[...],   # Override default model
    "middleware": Optional[...], # Additional middleware
    "interrupt_on": Optional[...] # HITL config
}
```

**CompiledSubAgent Schema** (for custom LangGraph graphs):
```python
{
    "name": str,
    "description": str,
    "runnable": Runnable  # Pre-built LangGraph graph
}
```

---

## Testing Strategy

### Unit Tests (`libs/deepagents/tests/unit_tests/`)

- Test individual middleware components
- Test backend implementations
- Mock LangGraph/LangChain dependencies
- Fast execution (<1s per test)

### Integration Tests (`libs/deepagents/tests/integration_tests/`)

- Test full agent workflows
- Test CLI commands end-to-end
- Require API keys (ANTHROPIC_API_KEY)
- Slower execution (seconds to minutes)

### Test Isolation

**Important**: Tests should NOT interfere with each other or user's agent data.

```python
# ✅ Good: Use temporary directories
@pytest.fixture
def tmp_agent_dir(tmp_path):
    return tmp_path / ".deepagents" / "test-agent"

# ❌ Bad: Use real agent directory
def test_agent():
    agent_dir = Path.home() / ".deepagents" / "agent"  # Could destroy user data!
```

### Running Specific Tests

```bash
# Run single test function
uv run pytest libs/deepagents/tests/unit_tests/test_file.py::test_function

# Run with markers
uv run pytest -m "not integration"  # Skip integration tests

# Run with coverage report
uv run pytest --cov=deepagents --cov-report=html

# Debug with print statements
uv run pytest -s  # Disable output capture
```

---

## LangGraph Server Integration

### Configuration (langgraph.json)

```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./deepagents_cli/graph.py:graph"
  },
  "env": ".env"
}
```

**Key Points**:
- **Graph ID**: `agent` - must match CLI's default `assistant_id`
- **Export Path**: `./path/file.py:variable_name` - points to module-level variable
- **Environment**: Loads from `.env` file in CLI directory
- **Auto-reload**: Watches for file changes (but only server reloads, not CLI)

### Server vs CLI Behavior

| Aspect | Server | CLI |
|--------|--------|-----|
| Entry point | `graph.py:graph` | `main.py:cli_main()` |
| Agent creation | `create_agent_with_config()` | `create_agent_with_config()` |
| Thread ID | From request | From ThreadManager |
| Environment | `.env` via langgraph.json | `.env` via dotenv |
| Reload | Auto on file change | Manual restart required |
| Storage | Same SQLite DB | Same SQLite DB |
| Studio UI | Free for local dev | N/A |

**Important**: By default, server and CLI share the same agent storage at `~/.deepagents/agent/`, so conversations are synced.

---

## Common Pitfalls & Solutions

### 1. Relative Imports in graph.py

**Error**: `ImportError: attempted relative import with no known parent package`

**Fix**: Use absolute imports in `graph.py`:
```python
# Change this:
from .agent import create_agent_with_config

# To this:
from deepagents_cli.agent import create_agent_with_config
```

### 2. Missing Dependencies After Upstream Merge

**Error**: `ModuleNotFoundError: No module named 'langchain_anthropic'`

**Fix**: Reinstall package:
```bash
cd libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

### 3. PostgreSQL Connection Errors

**Error**: `could not connect to server` or `database "deepagents" does not exist`

**Fix**:
```bash
# Start PostgreSQL
brew services start postgresql@14

# Create database
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents

# Verify connection
psql -d deepagents -c "SELECT 1"
```

### 4. Context Manager vs Direct Construction

**Error**: `'_GeneratorContextManager' object has no attribute 'get_next_version'`

**Cause**: Using `from_conn_string()` which returns a context manager, not a direct instance.

**Fix**: Use direct construction for long-running apps:
```python
# ❌ Wrong for CLI
checkpointer = SqliteSaver.from_conn_string(db_uri)

# ✅ Correct for CLI
import sqlite3
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()
```

### 5. Agent Storage Location Confusion

**Problem**: Changes not persisting or appearing in wrong place.

**Understanding**:
- CLI storage: `~/.deepagents/{agent_name}/`
- Server storage: Same as CLI (shares by default)
- `/memories/` maps to agent directory, NOT current working directory
- Regular file operations use current working directory

**Check your paths**:
```bash
# Agent storage
ls ~/.deepagents/agent/

# Checkpoints
sqlite3 ~/.deepagents/agent/checkpoints.db ".tables"

# Thread metadata
cat ~/.deepagents/agent/threads.json
```

---

## Contributing to Upstream

### Before Creating PR

1. **Sync with upstream**:
   ```bash
   git fetch origin
   git merge origin/master
   ```

2. **Run full test suite**:
   ```bash
   make test
   make integration_test
   ```

3. **Lint and format**:
   ```bash
   make format
   make lint
   ```

4. **Test CLI manually**:
   ```bash
   cd libs/deepagents-cli
   deepagents
   # Test your changes interactively
   ```

5. **Test LangGraph server**:
   ```bash
   cd libs/deepagents-cli
   langgraph dev
   # Open Studio UI and test
   ```

### PR Guidelines

- PRs go to `langchain-ai/deepagents` (origin), not your fork
- Focus on core library changes for upstream
- CLI-specific features should stay in your fork unless generally useful
- Include tests for new features
- Update relevant documentation
- Keep commits atomic and well-described

### Maintaining Your Fork

**Workflow**:
1. Develop features in your fork branches
2. Merge upstream changes regularly
3. Push to your fork (`upstream` remote)
4. For upstream contributions, create PR to `origin/master`

---

## Debugging & Tracing

### LangSmith Integration

**Setup**:
```bash
# In .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=deepagents-cli
```

**Usage**:
- All agent runs automatically traced
- View at https://smith.langchain.com
- Free for local development
- Includes full message history, tool calls, timing

### LangGraph Studio

**Launch**:
```bash
cd libs/deepagents-cli
langgraph dev
# Open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

**Features**:
- Visual graph execution flow
- Step-by-step debugging
- State inspection at each node
- Time-travel debugging
- Free for local dev server
- No API credits consumed

### CLI Debugging

**Token tracking**:
```bash
# In session
/tokens  # Show usage statistics
```

**Thread debugging**:
```bash
# In session
/threads info  # Current thread details
/threads info <thread-id>  # Specific thread details
```

**Database inspection**:
```bash
# Check checkpoints
sqlite3 ~/.deepagents/agent/checkpoints.db
SELECT thread_id, checkpoint_ns, created_at FROM checkpoints ORDER BY created_at DESC LIMIT 10;

# Check threads
cat ~/.deepagents/agent/threads.json | jq
```

---

## Performance Considerations

### Prompt Caching

**What**: Anthropic's prompt caching reduces costs for repeated context.

**Implementation**: `AnthropicPromptCachingMiddleware` automatically enables it.

**Best Practices**:
- Keep system prompts stable (cache hits)
- Use persistent memory (fewer repeated instructions)
- Avoid dynamically generated prompts when possible

### Token Management

**Summarization**: `SummarizationMiddleware` automatically summarizes old messages when context > 170k tokens.

**Configuration**:
```python
SummarizationMiddleware(
    model=model,
    max_tokens_before_summary=170000,  # Trigger threshold
    messages_to_keep=6,                # Keep recent messages verbatim
)
```

**CLI Token Tracking**: `ui.py:TokenTracker` monitors usage per interaction.

### Subagent Usage

**When to use subagents**:
- ✅ Complex subtasks requiring focus
- ✅ Context isolation (prevent main agent pollution)
- ✅ Specialized tools/prompts
- ✅ Parallel work on independent tasks

**When NOT to use**:
- ❌ Simple single-step operations
- ❌ Tasks requiring main agent context
- ❌ Cost-sensitive operations (spawns new agent)

---

## Quick Reference

### Common File Locations

| What | Path |
|------|------|
| Core library | `libs/deepagents/` |
| CLI package | `libs/deepagents-cli/` |
| CLI config | `libs/deepagents-cli/.env` |
| Agent storage | `~/.deepagents/{agent_name}/` |
| Checkpoints | `~/.deepagents/{agent_name}/checkpoints.db` |
| Threads | `~/.deepagents/{agent_name}/threads.json` |
| Agent prompt | `~/.deepagents/{agent_name}/agent.md` |
| Tests | `libs/deepagents/tests/` |
| Examples | `examples/` |

### Essential Commands

```bash
# Development
make format              # Format code
make lint               # Lint all
make test               # Unit tests
make integration_test   # Integration tests

# CLI Usage
deepagents              # Start CLI
deepagents list         # List agents
deepagents reset --agent myagent  # Reset agent

# Server
cd libs/deepagents-cli
langgraph dev          # Start server

# Git
git fetch origin       # Get upstream changes
git merge origin/master  # Merge upstream
git push upstream <branch>  # Push to fork
```

### Key Files to Understand

1. **libs/deepagents/graph.py** - Core factory, middleware stack
2. **libs/deepagents-cli/deepagents_cli/agent.py** - CLI agent creation
3. **libs/deepagents-cli/deepagents_cli/graph.py** - Server export
4. **libs/deepagents/middleware/filesystem.py** - File system tools
5. **libs/deepagents/middleware/subagents.py** - Subagent logic
6. **libs/deepagents-cli/deepagents_cli/execution.py** - CLI execution loop
7. **libs/deepagents-cli/deepagents_cli/thread_manager.py** - Thread management

---

## Additional Resources

- **Official Docs**: https://docs.langchain.com/oss/python/deepagents/overview
- **API Reference**: https://reference.langchain.com/python/deepagents/
- **LangGraph Docs**: https://langchain-ai.github.io/langgraph/
- **LangSmith**: https://smith.langchain.com
- **Repository**: https://github.com/langchain-ai/deepagents
- **Your Fork**: https://github.com/ASTXRTYS/DEEP-AI

---

**Last Updated**: 2025-11-05
**Maintainer**: Jason (ASTXRTYS)
**Based on**: LangChain deepagents v0.2.5
