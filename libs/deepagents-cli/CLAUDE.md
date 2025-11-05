# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**DeepAgents CLI** - An AI coding assistant powered by Claude Sonnet 4.5 with persistent memory, file operations, and web search capabilities. Built on LangChain's Deep Agents framework (LangGraph).

**Location**: `/Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli`

**Parent Repo**: Part of a monorepo at `/Users/Jason/astxrtys/DevTools/deepagents/`:
- `libs/deepagents/` - Core Deep Agents library
- `libs/deepagents-cli/` - This CLI package

**Fork Status**: This is a fork of [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents) with custom enhancements.

---

## Development Commands

### Testing
```bash
# Run all tests
make test

# Run specific test file
make test TEST_FILE=tests/test_file_ops.py

# Run tests directly with pytest
uv run pytest --disable-socket --allow-unix-socket tests/ --timeout 10
```

**Test Configuration:**
- Socket access disabled to prevent unintended network calls
- Unix sockets allowed for local IPC
- 10-second timeout per test
- Tests located in `tests/` directory

### Linting and Formatting
```bash
# Check code style
make lint

# Auto-format code
make format

# Lint only changed files (vs master)
make lint_diff
make format_diff

# Direct ruff usage
uv run ruff check deepagents_cli/
uv run ruff format deepagents_cli/
```

**Linting Configuration** (`pyproject.toml`):
- Line length: 100 characters
- Ruff with "ALL" rules enabled by default
- Google-style docstrings
- Key ignores: COM812, ISC001, PERF203, SLF001, PLC0415, PLR0913, PLC0414, C901

### Building and Installation
```bash
# Development install (editable mode)
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages

# Or use uv (faster)
uv pip install -e .

# Reinstall dependencies
uv pip install -e . --force-reinstall
```

### Running the CLI
```bash
# Basic usage
deepagents

# With specific agent
deepagents --agent myagent

# Auto-approve mode (no HITL prompts)
deepagents --auto-approve

# Management commands
deepagents list            # List all agents
deepagents reset --agent myagent
deepagents help
```

### LangGraph Server
```bash
# Start dev server only
./start-dev-server.sh
# Or: langgraph dev

# Start server + CLI together (recommended)
./start-dev.sh

# Start in tmux split panes
./start-tmux.sh
```

**Server URLs:**
- API: http://127.0.0.1:2024
- Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
- API Docs: http://127.0.0.1:2024/docs

---

## Critical Architecture Decisions

### 1. Shared Agent Creation Logic

**CRITICAL**: Both CLI and LangGraph server MUST use the exact same agent creation logic.

- **CLI**: Uses `create_agent_with_config()` from `agent.py`
- **Server**: Uses `create_agent_with_config()` from `graph.py` which imports from `agent.py`
- **Why**: Ensures consistency - server runs the EXACT same agent as CLI

### 2. Import Rules for graph.py

**CRITICAL**: `graph.py` MUST use ABSOLUTE imports, NOT relative imports.

```python
# ✅ CORRECT
from deepagents_cli.agent import create_agent_with_config
from deepagents_cli.tools import http_request, web_search

# ❌ WRONG - will break LangGraph server
from .agent import create_agent_with_config
from .tools import http_request, web_search
```

**Reason**: LangGraph's module loader executes `graph.py` outside package context, so relative imports fail with "attempted relative import with no known parent package".

### 3. Persistence Architecture

The agent uses a **three-layer persistence system**:

#### A. Thread-level Checkpointing (Conversation Memory)
- **Storage**: SQLite at `~/.deepagents/{agent_name}/checkpoints.db`
- **Implementation**: `SqliteSaver` from `langgraph.checkpoint.sqlite`
- **Purpose**: Preserves conversation state, allows resuming threads
- **Scope**: Per-thread (each conversation has a unique thread_id)

#### B. File System Backend (Cross-thread Memory Files)
- **Storage**: `~/.deepagents/{agent_name}/` directory
- **Implementation**: `CompositeBackend` with two routes:
  - **Default**: `FilesystemBackend()` - operates in current working directory
  - **/memories/**: `FilesystemBackend(root_dir=agent_dir)` - persistent agent memories
- **Purpose**: Agent saves/reads files in `/memories/` that persist across sessions
- **Example**: `write_file /memories/guide.md`, `read_file /memories/preferences.json`

#### C. Long-term Store (Cross-agent Knowledge - Currently Unused)
- **Storage**: PostgreSQL database via `DEEPAGENTS_DATABASE_URL`
- **Implementation**: `PostgresStore` from `langgraph.store.postgres`
- **Status**: Infrastructure ready but not actively used
- **Future**: For multi-customer deployment, switch from FilesystemBackend to StoreBackend

**Key Understanding**: Current setup uses FilesystemBackend (disk) for cross-thread persistence, which works perfectly for local/personal use.

### 4. Environment Configuration

**Location**: `.env` file in project root (NOT `~/.zshrc`)

**Required Variables**:
```bash
# API Keys
ANTHROPIC_API_KEY=sk-ant-api03-...
TAVILY_API_KEY=tvly-dev-...  # Optional - for web search

# LangSmith Tracing (free for local dev server)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=deepagents-cli

# PostgreSQL (optional - defaults to localhost)
DEEPAGENTS_DATABASE_URL=postgresql://localhost/deepagents
```

**Why .env**: Better portability, LangGraph server compatibility, cleaner separation.

### 5. Checkpoint/Store Initialization Pattern

**CRITICAL**: For long-running applications (CLI/server), use direct construction:

```python
# Checkpointer
import sqlite3
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()

# Store
import psycopg
pg_conn = psycopg.connect(database_url, autocommit=True)
store = PostgresStore(pg_conn)
store.setup()
```

**NEVER use** `from_conn_string()` which returns a context manager:
```python
# ❌ WRONG - returns Iterator/context manager
checkpointer = SqliteSaver.from_conn_string(...)
```

Context managers are only for short-lived scripts.

### 6. Checkpoint Time-to-Live (TTL) Configuration

**Purpose**: Automatically clean up old checkpoints to prevent unbounded database growth.

**Configuration Location**: `langgraph.json`

**Current Settings** (as of 2025-01-03):
```json
{
  "checkpointer": {
    "ttl": {
      "strategy": "delete",
      "sweep_interval_minutes": 120,
      "default_ttl": 20160
    }
  },
  "store": {
    "ttl": {
      "refresh_on_read": true,
      "sweep_interval_minutes": 120,
      "default_ttl": 20160
    }
  }
}
```

**Settings Explanation**:
- `default_ttl: 20160` = 14 days (in minutes)
- `sweep_interval_minutes: 120` = Check for expired data every 2 hours
- `strategy: "delete"` = Only available strategy (deletes all checkpoints in expired threads)
- `refresh_on_read: true` = Accessing store items resets their expiration timer

**CRITICAL: TTL Only Works in Server Mode** 🚨

**Automatic TTL cleanup requires running LangGraph server:**
- ✅ **Server mode** (`langgraph dev` or `./start-dev.sh`): TTL cleanup runs every 2 hours in background
- ❌ **CLI-only mode** (`deepagents`): TTL cleanup does **NOT** run automatically

**Why**: TTL sweep is a background process in LangGraph Server. The standalone CLI doesn't run this background task.

**Recommendation**:
- For **development with automatic cleanup**: Use `./start-dev.sh` (server + CLI)
- For **CLI-only usage**: Run `/threads cleanup` manually to clean old threads

**Important Limitations**:
- TTL **only affects NEW data** created after the configuration is deployed
- Existing threads/checkpoints are NOT retroactively affected
- Requires server restart (`langgraph dev`) to take effect
- Thread-level deletion (all checkpoints in a thread deleted together, not individual checkpoints)
- TTL creates **orphaned metadata**: Checkpoints are deleted but `threads.json` entries remain (use `/threads cleanup` to sync)

**Manual Cleanup Commands**:

The CLI provides commands for manual checkpoint management:

```bash
# List all threads
/threads

# Delete specific thread
/threads delete <id>

# Bulk cleanup (delete threads older than N days)
/threads cleanup --days 30

# Reclaim disk space after deletions
/threads vacuum

# View database statistics
/threads stats
```

**ThreadManager Methods** (for programmatic cleanup):
```python
# Delete specific thread
thread_manager.delete_thread(thread_id, agent)

# Bulk cleanup with preview
count, names = thread_manager.cleanup_old_threads(days_old=30, agent, dry_run=True)
count, names = thread_manager.cleanup_old_threads(days_old=30, agent, dry_run=False)

# Vacuum database
result = thread_manager.vacuum_database()
# Returns: {'size_before': bytes, 'size_after': bytes}

# Get statistics
stats = thread_manager.get_database_stats()
# Returns: {thread_count, checkpoint_count, db_size_bytes, oldest_thread, newest_thread}
```

**Best Practices**:
- **CLI-only users**: Run `/threads cleanup --days 14` every 1-2 weeks (manual equivalent of TTL)
- **Server users**: TTL runs automatically, but run `/threads cleanup` to clean pre-TTL threads
- Run `/threads vacuum` after bulk deletions to reclaim disk space
- Monitor database size with `/threads stats`
- Repair orphaned metadata after TTL by running `/threads sync`
- Consider longer TTL for important conversations (14-90 days)
- Document TTL policy for users (data retention period)

**Reference**: https://docs.langchain.com/langsmith/configure-ttl

---

## File Structure & Key Components

```
deepagents-cli/
├── .env                          # Environment variables (gitignored)
├── langgraph.json               # LangGraph server config
├── Makefile                     # Development commands
├── pyproject.toml               # Dependencies & build config
├── start-dev-server.sh          # Launch server only
├── start-dev.sh                 # Launch server + CLI
├── start-tmux.sh                # Launch in tmux split
│
├── deepagents_cli/
│   ├── agent.py                 # ⭐ CORE: Agent creation & config
│   │   └── create_agent_with_config()  # Shared by CLI & server
│   │   └── get_system_prompt()         # Base system prompt
│   │   └── list_agents()               # Agent management
│   │   └── reset_agent()               # Agent reset/copy
│   │
│   ├── graph.py                 # ⭐ CRITICAL: Server export
│   │   └── graph                       # Module-level variable
│   │   └── _get_default_model()
│   │   └── _get_default_tools()
│   │
│   ├── tools.py                 # Tool definitions
│   │   └── http_request()              # HTTP tool
│   │   └── web_search()                # Tavily search
│   │
│   ├── main.py                  # ⭐ CLI entry point & loop
│   │   └── simple_cli()                # Interactive loop
│   │   └── check_cli_dependencies()
│   │
│   ├── cli.py                   # Stub (unused, just prints "I'm alive!")
│   │
│   ├── execution.py             # Task execution
│   │   └── execute_task()              # Runs agent
│   │
│   ├── agent_memory.py          # Memory middleware
│   │   └── AgentMemoryMiddleware
│   │
│   ├── resumable_shell_async.py # Async shell execution
│   │   └── ResumableShellToolMiddleware
│   │
│   ├── config.py                # Configuration & styling
│   │   └── create_model()              # ChatAnthropic instance
│   │   └── SessionState                # Session state
│   │   └── console                     # Rich Console singleton
│   │
│   ├── ui.py                    # UI rendering & token tracking
│   ├── input.py                 # Prompt session (prompt_toolkit)
│   ├── commands.py              # Slash command handlers
│   ├── file_ops.py              # File operation utilities
│   ├── token_utils.py           # Token counting
│   └── thread_manager.py        # Thread management
│
└── tests/
    ├── test_file_ops.py
    └── test_placeholder.py
```

### Key File Responsibilities

| File | Purpose | Critical Notes |
|------|---------|----------------|
| `agent.py` | Agent creation logic | Shared by CLI & server |
| `graph.py` | LangGraph server export | MUST use absolute imports |
| `main.py` | CLI implementation | Actual entry point |
| `cli.py` | Console script stub | Placeholder only |
| `execution.py` | Task execution | Contains streaming logic |
| `config.py` | Configuration | Console singleton at line 76 |

---

## System Prompt Structure

The final system prompt is composed of:

1. **Base System Prompt** (`agent.py:get_system_prompt()`):
   - Current working directory info
   - Memory system usage (`/memories/`)
   - Human-in-the-loop guidelines
   - Web search tool instructions
   - Todo list management

2. **Agent-Specific Prompt** (`~/.deepagents/{agent_name}/agent.md`):
   - Custom instructions per agent
   - Defaults to `config.get_default_coding_instructions()` if missing

3. **Deep Agent Base Prompt** (from `deepagents` library):
   - Standard Deep Agent instructions
   - Added automatically by `create_deep_agent()`

---

## Middleware Stack

**Order matters!** Middleware is applied in this exact order:

### From create_deep_agent() (libs/deepagents/graph.py):
1. `TodoListMiddleware()` - Provides write_todos tool
2. `FilesystemMiddleware(backend=backend)` - File operations
3. `SubAgentMiddleware(...)` - Task tool (spawn subagents)
4. `SummarizationMiddleware(...)` - Conversation summarization
5. `AnthropicPromptCachingMiddleware(...)` - Prompt caching
6. `PatchToolCallsMiddleware()` - Tool call formatting fixes
7. **Custom middleware** (passed via parameter)
8. `HumanInTheLoopMiddleware(interrupt_on=...)` - HITL approvals

### Custom Middleware (from agent.py):
1. `AgentMemoryMiddleware(backend=long_term_backend, memory_path="/memories/")`
2. `ResumableShellToolMiddleware(workspace_root=os.getcwd(), ...)`

---

## Human-in-the-Loop (HITL) Configuration

**Location**: `agent.py:create_agent_with_config()` ~line 254-296

**Tools requiring approval**:
1. `shell` - Shell command execution
2. `write_file` - File writing/overwriting
3. `edit_file` - File editing
4. `web_search` - Web search (uses API credits)
5. `task` - Subagent spawning

Each has a custom formatting function showing relevant details.

**Auto-Approve Mode**: `deepagents --auto-approve` disables HITL.

---

## Thread Management

**Location**: `thread_manager.py` + `execution.py`

**Current Implementation**:
```python
thread_id = assistant_id or "main"
if session_state and session_state.thread_manager:
    thread_id = session_state.thread_manager.get_current_thread_id()

config = {"configurable": {"thread_id": thread_id}}
```

**Features**:
- Pure UUID format (LangGraph standard)
- Thread metadata stored in `~/.deepagents/{agent_name}/threads.json`
- Conversations persist across CLI sessions

**Thread Commands**:
- `/new` - Create new thread
- `/threads` - List all threads
- `/threads continue <id>` - Switch to thread
- `/threads fork [name]` - Fork current thread
- `/threads info [id]` - Show thread details
- `/threads rename <id> <name>` - Rename thread
- `/threads sync` - Reconcile metadata with checkpoints

---

## Git Workflow

**Repository**: https://github.com/ASTXRTYS/DEEP-AI (fork of langchain-ai/deepagents)

### Remote Configuration
```bash
origin   → https://github.com/langchain-ai/deepagents.git  # LangChain upstream
upstream → git@github.com:ASTXRTYS/DEEP-AI.git             # Your repo
```

### Sync with LangChain Upstream
```bash
cd /Users/Jason/astxrtys/DevTools/deepagents

# Fetch latest from LangChain
git fetch origin

# Merge into your master
git checkout master
git merge origin/master

# Push to your repo
git push upstream master
```

### Feature Branch Workflow
```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes, commit
git add .
git commit -m "Implement feature"

# Push to your repo
git push upstream feature/my-feature

# Merge when ready
git checkout master
git merge feature/my-feature
git push upstream master
```

---

## Known Issues & Solutions

### Issue 1: Relative Import Error in graph.py
**Error**: `ImportError: attempted relative import with no known parent package`

**Solution**: Use absolute imports in `graph.py`
```python
from deepagents_cli.agent import create_agent_with_config  # ✅
from .agent import create_agent_with_config  # ❌
```

### Issue 2: Missing Dependencies
**Error**: `ModuleNotFoundError: No module named 'langchain_anthropic'`

**Solution**: Reinstall
```bash
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

### Issue 3: PostgreSQL Connection Error
**Error**: `could not connect to server` or `database "deepagents" does not exist`

**Solution**:
```bash
# Start PostgreSQL
brew services start postgresql@14

# Create database
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents
```

### Issue 4: Server Won't Start
**Check**:
```bash
# Verify .env exists
cat .env

# Check logs
langgraph dev  # See full error output
```

---

## Dependencies

**Core Dependencies** (from `pyproject.toml`):
- `deepagents==0.2.4` - Core library (workspace dependency)
- `langchain-anthropic>=0.1.0` - Anthropic integration
- `langchain-community>=0.1.0` - Community integrations
- `langchain-openai>=0.1.0` - OpenAI integration
- `langgraph-checkpoint-sqlite>=3.0.0` - SQLite checkpointing
- `langgraph-checkpoint-postgres>=3.0.0` - PostgreSQL checkpointing
- `psycopg[binary,pool]>=3.0.0` - PostgreSQL driver
- `tavily-python` - Web search
- `rich>=13.0.0` - Terminal UI
- `prompt-toolkit>=3.0.52` - Interactive input
- `python-dotenv` - Environment variable loading
- `requests` - HTTP client

**Dev Dependencies**:
- `pytest` + ecosystem (pytest-asyncio, pytest-cov, pytest-mock, etc.)
- `ruff` - Linting and formatting
- `mypy` - Type checking

---

## Model Configuration

**Model**: `claude-sonnet-4-5-20250929`

### Server (graph.py)
```python
ChatAnthropic(
    model="claude-sonnet-4-5-20250929",
    max_tokens=8000,
    temperature=0,
    timeout=60,
    max_retries=2,
)
```

### CLI (config.py - create_model())
- Same model configuration
- API key loaded from environment
- Includes validation

---

## Testing Checklist

Before committing changes:

- [ ] Tests pass: `make test`
- [ ] Code formatted: `make format`
- [ ] Code linted: `make lint`
- [ ] LangGraph server starts: `langgraph dev`
- [ ] Server registers graph (look for "Registering graph with id 'agent'")
- [ ] CLI starts: `deepagents`
- [ ] Both server and CLI execute tasks
- [ ] Memory persists across sessions
- [ ] HITL prompts work
- [ ] Web search works (if TAVILY_API_KEY set)
- [ ] File operations work in CWD and /memories/
- [ ] Auto-approve mode works: `deepagents --auto-approve`
- [ ] Thread commands work: `/new`, `/threads`

---

## Quick Reference

| Component | Location | Purpose |
|-----------|----------|---------|
| Agent creation | `agent.py:create_agent_with_config()` | Shared logic |
| Server export | `graph.py:graph` | Module-level variable |
| Tools | `tools.py` | http_request, web_search |
| Environment | `.env` | API keys, config |
| Server config | `langgraph.json` | Points to graph.py |
| CLI entry | `main.py:simple_cli()` | Interactive loop |
| Execution | `execution.py:execute_task()` | Task runner |
| Checkpoints | `~/.deepagents/{agent}/checkpoints.db` | SQLite |
| Threads | `~/.deepagents/{agent}/threads.json` | Metadata |
| Memory files | `~/.deepagents/{agent}/` | Via /memories/ |

---

## Important Implementation Notes

### 1. create_deep_agent() Signature
**Location**: `/Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/graph.py:40`

**Key Parameters**:
- `store: BaseStore | None = None` - Enables long-term memory (NOT `use_longterm_memory`)
- `backend: BackendProtocol | BackendFactory | None = None` - File operations backend
- `checkpointer: Checkpointer | None = None` - Conversation state persistence
- `middleware: Sequence[AgentMiddleware] = ()` - Custom middleware
- `interrupt_on: dict[str, bool | InterruptOnConfig] | None = None` - HITL config

### 2. Agent Storage Locations
- **Checkpoints**: `~/.deepagents/{agent_name}/checkpoints.db`
- **Thread Metadata**: `~/.deepagents/{agent_name}/threads.json`
- **Agent Prompt**: `~/.deepagents/{agent_name}/agent.md`
- **Memory Files**: `~/.deepagents/{agent_name}/*` (accessed via `/memories/` prefix)

### 3. CompositeBackend Routes
```python
backend = CompositeBackend(
    default=FilesystemBackend(),  # CWD
    routes={
        "/memories/": FilesystemBackend(root_dir=agent_dir)  # Persistent
    }
)
```

**Usage**:
- `ls /memories/` - List persistent files
- `read_file /memories/guide.md` - Read from agent storage
- `write_file /memories/note.txt` - Write to agent storage
- `ls` - List CWD files
- `read_file main.py` - Read from CWD

---

## LangGraph Studio

**Free visual debugging** for local dev server:

1. Start server: `./start-dev-server.sh`
2. Open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
3. Features:
   - Visual graph execution
   - Step-by-step debugging
   - State inspection
   - Time travel debugging

**LangSmith Tracing**:
- Enabled: `LANGCHAIN_TRACING_V2=true`
- Project: `deepagents-cli`
- Access: https://smith.langchain.com
- Cost: Free for local dev

---

## Key Takeaways

1. **Never use relative imports in graph.py** - Always absolute
2. **create_deep_agent() has NO use_longterm_memory parameter** - Use `store=`
3. **CLI and server MUST share create_agent_with_config()** - Consistency
4. **Environment in .env, not .zshrc** - Portability
5. **PostgreSQL for store (unused), SQLite for checkpointing** - Different purposes
6. **Memory system has two parts**: Checkpointing + FilesystemBackend
7. **/memories/ is virtual path** to `~/.deepagents/{agent_name}/`
8. **Server auto-reloads, CLI doesn't** - Restart CLI for changes
9. **Studio UI is free** for local server
10. **Current persistence setup perfect for local use** - FilesystemBackend works great

---

**Last Updated**: 2025-11-03
**By**: Claude Code (claude.ai/code)
