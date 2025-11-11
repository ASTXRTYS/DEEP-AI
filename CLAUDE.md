# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Protocol Reminder:** Before following any instructions here, confirm you have read and acknowledged [`AGENT.md`](AGENT.md); those operating rules are mandatory for every agent session.

## Repository Overview

This is a **UV workspace monorepo** containing the DeepAgents framework - a LangGraph-based system for building "deep" agents with planning, file system access, and subagent spawning capabilities.

**Two main packages:**
1. **`libs/deepagents/`** - Core library implementing the deep agent pattern with middleware
2. **`libs/deepagents-cli/`** - Interactive CLI tool for running deep agents with persistent memory

Both packages share common middleware and are designed to work together, with the CLI being a reference implementation and user-facing tool built on the core library.

## Development Commands

### Setup

```bash
# Install dependencies (run from repository root)
uv sync --all-groups

# Activate virtual environment
source .venv/bin/activate

# Install CLI in development mode
cd libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

### Testing

```bash
# Run unit tests for core library
make test

# Run integration tests
make integration_test

# Run CLI tests
cd libs/deepagents-cli
uv run pytest tests/
```

### Linting & Formatting

```bash
# Format all Python files
make format

# Lint without fixing
make lint

# Format and lint with fixes
make format

# Lint only the core package
make lint_package

# Lint only tests
make lint_tests

# Lint changes since master
make lint_diff format_diff
```

**Note:** The project uses `ruff` for both linting and formatting, with `mypy` for type checking.

## Architecture

### Core Library (`libs/deepagents/`)

**Entry point:** `create_deep_agent()` in `graph.py`

Creates a LangGraph agent with three built-in capabilities via middleware:
1. **Planning** - TodoListMiddleware provides `write_todos` tool
2. **File System** - FilesystemMiddleware provides file operations (ls, read_file, write_file, edit_file, glob_search, grep_search)
3. **Subagents** - SubAgentMiddleware provides `task` tool for spawning specialized agents

**Middleware Stack (order matters):**
```python
[
    TodoListMiddleware(),                    # Planning tool
    handle_filesystem_permissions,           # File operation guards
    FilesystemMiddleware(backend=...),       # File system tools
    SubAgentMiddleware(...),                 # Subagent spawning
    SummarizationMiddleware(...),            # Conversation summarization
    SafeAnthropicPromptCachingMiddleware(), # Prompt caching
    PatchToolCallsMiddleware(),             # Tool call formatting fixes
    *middleware,                            # Custom middleware (user-provided)
    HumanInTheLoopMiddleware(...),          # HITL approvals (if interrupt_on configured)
]
```

**Key insight:** Middleware is composable. You can use individual middleware (TodoListMiddleware, FilesystemMiddleware, SubAgentMiddleware) independently with `create_agent()` if you don't need the full deep agent pattern.

### CLI (`libs/deepagents-cli/`)

**Entry point:** `cli_main()` in `main.py`

Built on top of `create_deep_agent()` with additional features:
- **Persistent memory** - SqliteSaver for checkpointing, FilesystemBackend/PostgresStore for long-term storage
- **Thread management** - Multiple conversation threads with switching/forking
- **LangGraph server integration** - Runs alongside `langgraph dev` for Studio UI debugging
- **Custom middleware** - Adds AgentMemoryMiddleware and ResumableShellToolMiddleware
- **HITL approvals** - Requires approval for shell, write_file, edit_file, web_search, task tools

**Architecture decision:** Both CLI and LangGraph server use the **exact same agent creation logic** from `agent.py:create_agent_with_config()`. This ensures consistency - the server runs the identical agent as the CLI.

**Memory Architecture (3 layers):**
1. **Checkpointing** (thread-level) - SQLite at `~/.deepagents/{agent}/checkpoints.db`
2. **File backend** (cross-thread) - FilesystemBackend at `~/.deepagents/{agent}/` (accessed via `/memories/` virtual path)
3. **Store** (programmatic) - PostgresStore (infrastructure ready but currently file operations go through FilesystemBackend)

### Backend System

The backend system abstracts storage for file operations:

**CompositeBackend pattern:**
```python
backend = CompositeBackend(
    default=FilesystemBackend(),  # Operations in CWD
    routes={
        "/memories/": FilesystemBackend(root_dir=agent_dir)  # Persistent agent storage
    }
)
```

**Available backends:**
- `FilesystemBackend` - Local disk storage (current implementation)
- `StateBackend` - Store in LangGraph state (checkpointed)
- `StoreBackend` - Store in BaseStore (requires PostgresStore)

**For customer deployments:** Switch from FilesystemBackend to StoreBackend for multi-instance/cloud compatibility.

### Middleware Pattern

Middleware provides hooks at different execution points:

**Hook order:**
```python
before_agent()      # Before agent starts
before_model()      # Before each model call
after_model()       # After each model call (reverse order!)
before_tool()       # Before each tool call
after_tool()        # After each tool call
```

**Critical:** `after_model()` hooks execute in **reverse order** - last middleware attached runs first.

**When to use middleware vs custom nodes:**
- ✅ Middleware: Cross-cutting concerns (logging, caching, auth), intercepting all tool/model calls
- ✅ Custom nodes: Complex stateful workflows, multi-step business logic (requires full StateGraph, not available in `create_deep_agent`)

## Common Development Tasks

### Adding Custom Tools

```python
from langchain_core.tools import tool
from deepagents import create_deep_agent

@tool
def my_tool(param: str) -> str:
    """Tool description shown to LLM."""
    return "result"

agent = create_deep_agent(
    tools=[my_tool],
    system_prompt="Use my_tool to..."
)
```

### Adding Custom Middleware

```python
from langchain.agents.middleware import AgentMiddleware

class MyMiddleware(AgentMiddleware):
    tools = [my_tool]  # Optional: add tools

    def after_model(self, messages, agent_input, config, **kwargs):
        # Intercept after model call
        # Modify messages, emit interrupt(), etc.
        yield from messages

agent = create_deep_agent(
    middleware=[MyMiddleware()]
)
```

### Running the CLI Locally

**Two-terminal workflow:**

Terminal 1:
```bash
cd libs/deepagents-cli
langgraph dev  # Starts server on http://127.0.0.1:2024
```

Terminal 2:
```bash
deepagents  # Connects to server
```

**Alternative (tmux):**
```bash
cd libs/deepagents-cli
./start-tmux.sh  # Creates split panes with server + CLI
```

### Debugging with LangGraph Studio

1. Start server: `cd libs/deepagents-cli && langgraph dev`
2. Open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
3. Execute tasks and see step-by-step graph execution
4. Inspect state, time-travel debug

**Note:** Studio UI is free for local dev server (no API credits needed).

## Important Implementation Details

### Graph Export for LangGraph Server

**Critical constraint:** `graph.py` exports must use **absolute imports**, not relative imports.

```python
# ✅ CORRECT (in libs/deepagents-cli/deepagents_cli/graph.py)
from deepagents_cli.agent import create_agent_with_config
from deepagents_cli.tools import http_request

# ❌ WRONG - breaks LangGraph server
from .agent import create_agent_with_config
from .tools import http_request
```

**Reason:** LangGraph's module loader executes graph.py outside of package context.

### Checkpoint and Store Initialization

**For long-running applications (CLI/server)**, use direct construction with connection objects:

```python
import sqlite3
import psycopg

# Checkpointer (conversation state)
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()

# Store (long-term memory)
pg_conn = psycopg.connect(database_url, autocommit=True)
store = PostgresStore(pg_conn)
store.setup()
```

**Never use** `from_conn_string()` context managers for long-running apps - those are for short scripts only.

### Subagent Configuration

Subagents come in two forms:

**1. SubAgent (dict-based config):**
```python
{
    "name": "researcher",
    "description": "Researches topics in depth",
    "prompt": "You are an expert researcher...",
    "tools": [web_search],
    "model": "gpt-4o",  # Optional override
    "middleware": [],   # Optional
}
```

**2. CompiledSubAgent (pre-built graph):**
```python
{
    "name": "analyzer",
    "description": "Analyzes data",
    "runnable": my_custom_graph  # Pre-compiled LangGraph
}
```

Use CompiledSubAgent when you need full control over the subagent's graph structure.

## Testing Strategy

**Unit tests** - Test individual components in isolation:
- Middleware behavior
- Backend implementations
- Tool functionality

**Integration tests** - Test end-to-end agent behavior:
- Full agent execution with real LLM calls
- Checkpointing and memory persistence
- Subagent spawning

**Test organization:**
```
libs/deepagents/tests/
├── unit_tests/        # Fast, mocked, isolated
└── integration_tests/ # Slow, real API calls, end-to-end
```

## Environment Variables

The CLI requires these environment variables (stored in `libs/deepagents-cli/.env`):

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-api03-...
LANGCHAIN_API_KEY=lsv2_pt_...

# Optional
TAVILY_API_KEY=tvly-dev-...              # For web search
DEEPAGENTS_DATABASE_URL=postgresql://... # For PostgresStore
LANGCHAIN_TRACING_V2=true                # Enable LangSmith tracing
LANGCHAIN_PROJECT=deepagents-cli         # LangSmith project name
```

## Git Workflow

This is a fork of `langchain-ai/deepagents` with custom enhancements.

**Remote setup:**
```
origin   → https://github.com/langchain-ai/deepagents.git  # LangChain upstream
upstream → git@github.com:ASTXRTYS/DEEP-AI.git             # Your fork
```

**Sync with LangChain upstream:**
```bash
git fetch origin
git merge origin/master
git push upstream master
```

## Key Principles

1. **Middleware is composable** - Use individual middleware pieces independently
2. **Both CLI and server share agent creation logic** - Consistency via `create_agent_with_config()`
3. **Backend abstraction enables flexibility** - FilesystemBackend for local, StoreBackend for production
4. **UV workspace manages dependencies** - Use `uv sync` not `pip install` for workspace packages
5. **Graph exports must use absolute imports** - LangGraph server limitation

## Package Relationship

```
deepagents (core)
    ├── Exports: create_deep_agent()
    ├── Middleware: TodoList, Filesystem, Subagents
    └── Backends: Filesystem, State, Store
                    ↑
                    │ depends on
                    │
deepagents-cli
    ├── Imports: deepagents==0.2.4 (workspace dependency)
    ├── Adds: Thread management, HITL UI, persistent memory
    └── Exports: graph.py (for langgraph dev)
```

The CLI is both a **user-facing tool** and a **reference implementation** showing how to build production agents with the core library.
