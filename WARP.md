# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

---

## Repository Structure

**UV Workspace Monorepo** with two packages:
- `libs/deepagents/` - Core library implementing deep agent primitives (planning, filesystem, subagents)
- `libs/deepagents-cli/` - CLI application for interactive coding assistance

**Fork Status**: Fork of LangChain's `deepagents` with custom enhancements for thread management, TTL cleanup, and LangSmith metrics.

**Remotes**:
- `origin` → https://github.com/langchain-ai/deepagents.git (LangChain upstream, read-only)
- `upstream` → git@github.com:ASTXRTYS/DEEP-AI.git (Your fork, read-write)

---

## Core Concepts

Deep Agents = **Planning** + **File System** + **Subagents** + **Detailed Prompt**

1. **Planning**: `TodoListMiddleware` provides `write_todos` tool for breaking down complex tasks
2. **File System**: `FilesystemMiddleware` provides `ls`, `read_file`, `write_file`, `edit_file`, `glob_search`, `grep_search`
3. **Subagents**: `SubAgentMiddleware` enables spawning specialized agents via `task` tool for context isolation
4. **Prompts**: Comprehensive system prompts inspired by Claude Code

---

## Essential Commands

### Development Setup
```bash
# Install dependencies (from root)
uv sync --all-groups

# OR with pip (from root)
python3.11 -m pip install -e . --break-system-packages

# Install CLI package
cd libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

### Linting & Formatting
```bash
make format              # Format all Python files
make lint                # Lint with ruff and mypy (full)
make lint_package        # Lint only the deepagents package
make lint_tests          # Lint tests only
make lint_diff           # Lint only changed files vs master
```

**Linting Configuration**:
- **Ruff**: ALL rules enabled, specific ignores for practicality (line length: 150 chars core, 100 chars CLI)
- **Mypy**: Strict type checking for core library (`strict = true`), relaxed for CLI (`strict = false`)
- **Docstring format**: Google style

### Testing
```bash
make test                # Run unit tests with coverage
make integration_test    # Run integration tests

# Run specific test file
uv run pytest libs/deepagents/tests/unit_tests/test_specific.py

# Run with verbose output
uv run pytest libs/deepagents/tests/unit_tests -v

# Run CLI tests
cd libs/deepagents-cli
uv run pytest tests/
```

### Running DeepAgents CLI

**Prerequisites**: CLI requires a LangGraph server for thread management and Studio integration.

```bash
# 1. Start LangGraph dev server (terminal 1)
cd libs/deepagents-cli
langgraph dev

# 2. Run CLI (terminal 2)
deepagents

# Other CLI commands
deepagents list                    # List all agents
deepagents --agent myagent        # Use specific agent
deepagents --auto-approve         # Auto-approve mode
deepagents reset --agent myagent  # Reset agent to default
```

### PostgreSQL Setup (for LangGraph Store)
```bash
# PostgreSQL is used for LangGraph Store feature (cross-agent, cross-conversation storage)
# The agent's file-based memory (/memories/) uses filesystem, not PostgreSQL
brew services start postgresql@14
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents
```

### Git Workflow
```bash
# Pull latest from LangChain
git fetch origin
git merge origin/master  # Review UPSTREAM_SYNC_ANALYSIS.md first

# Push changes to your fork
git push upstream <branch-name>

# Check for conflicts before merging
git fetch origin
git merge --no-commit --no-ff origin/master
git merge --abort  # If you just wanted to test
```

---

## Architecture Deep Dive

### Middleware Stack

Middleware is applied in this order (from `libs/deepagents/graph.py:create_deep_agent()`):
```python
[
    TodoListMiddleware(),                        # Planning tool
    handle_filesystem_permissions,               # Permission handling
    FilesystemMiddleware(backend=backend),       # File operations
    SubAgentMiddleware(...),                     # Subagent spawning
    SummarizationMiddleware(...),               # Context compression
    AnthropicPromptCachingMiddleware(...),      # Prompt caching
    PatchToolCallsMiddleware(),                 # Tool call formatting
    *custom_middleware,                          # Your middleware
    HumanInTheLoopMiddleware(interrupt_on=...),  # HITL (if configured)
]
```

**Important**: Middleware order matters! Each middleware wraps the next.

### Backend Architecture

**Three Backend Types**:
1. **FilesystemBackend**: Stores files on disk (default for CLI)
2. **StateBackend**: Stores files in LangGraph state (memory)
3. **StoreBackend**: Stores files in LangGraph Store (PostgreSQL)

**CompositeBackend** (used by CLI): Routes paths to different backends
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

### CLI Persistence Architecture

**Three Storage Layers**:
1. **Checkpointing** (conversation state): SQLite at `~/.deepagents/{agent_name}/checkpoints.db`
   - Stores conversation history and state for resuming threads
2. **File Backend** (agent memory): Filesystem at `~/.deepagents/{agent_name}/` (accessible via `/memories/` prefix)
   - Uses CompositeBackend that routes `/memories/` paths to FilesystemBackend
   - Agent's long-term memory files (agent.md, notes, guides) stored as regular files on disk
   - NOT stored in PostgreSQL - this is pure filesystem storage
3. **Store** (cross-agent knowledge): PostgreSQL database (LangGraph Store feature)
   - Optional storage layer for sharing data across agents and conversations
   - Different from file-based `/memories/` - this is for structured key-value storage

### Agent Memory Architecture (Critical Understanding)

**How Agent Memory Works:**

The CLI implements a sophisticated agent memory system that gives agents persistent, self-modifiable instructions across sessions. This is implemented via `AgentMemoryMiddleware` and a two-part backend routing system.

**Memory System Components:**

1. **agent.md** - The Agent's Self-Modifiable System Prompt
   - Location: `~/.deepagents/{agent_name}/agent.md`
   - Purpose: Agent's persistent instructions that it can read and modify
   - Loaded at session start by `AgentMemoryMiddleware.before_agent()`
   - Injected into system prompt wrapped in `<agent_memory>` tags
   - Default content from `default_agent_prompt.md` (immutable base template)
   - Agent can update its own behavior by editing this file

2. **Backend Routing** - Two-Layer Filesystem Access
   ```python
   # In agent.py:create_agent_with_config()
   long_term_backend = FilesystemBackend(root_dir=agent_dir, virtual_mode=True)
   backend = CompositeBackend(
       default=FilesystemBackend(),  # CWD access
       routes={"/memories/": long_term_backend}  # Agent directory access
   )
   ```

   **What this means:**
   - Regular file operations (no prefix) → Current working directory
   - `/memories/` prefix → `~/.deepagents/{agent_name}/` directory
   - `virtual_mode=True` → Paths are virtual (sandboxed, no traversal)
   - Agent can `ls /memories/`, `read_file /memories/notes.md`, etc.

3. **AgentMemoryMiddleware** - System Prompt Injection
   - Reads `/agent.md` from the long_term_backend at session start
   - Injects content into system prompt: `<agent_memory>{content}</agent_memory>`
   - Adds instructions about memory system (how to use `/memories/`)
   - Happens in `wrap_model_call()` before every model invocation

**Memory Loading Flow:**

```
1. Agent starts → create_agent_with_config() called
2. Check if agent.md exists at ~/.deepagents/{agent_name}/agent.md
3. If not, create it from default_agent_prompt.md template
4. AgentMemoryMiddleware.before_agent() runs (once per session)
   → Reads /agent.md from long_term_backend
   → Stores in state['agent_memory']
5. AgentMemoryMiddleware.wrap_model_call() runs (every model call)
   → Retrieves state['agent_memory']
   → Wraps in <agent_memory> tags
   → Prepends to system_prompt
   → Appends LONGTERM_MEMORY_SYSTEM_PROMPT instructions
6. Model sees complete system prompt with agent.md content
```

**Key Insight - Dual Backend Usage:**

The agent has TWO ways to access the same physical directory:

```python
# Backend setup in agent.py
long_term_backend = FilesystemBackend(root_dir=agent_dir, virtual_mode=True)
backend = CompositeBackend(
    default=FilesystemBackend(),
    routes={"/memories/": long_term_backend}
)

# AgentMemoryMiddleware uses long_term_backend directly
AgentMemoryMiddleware(backend=long_term_backend, memory_path="/memories/")

# FilesystemMiddleware uses CompositeBackend
FilesystemMiddleware(backend=backend)
```

**Why this matters:**
- `AgentMemoryMiddleware` reads `/agent.md` directly from `long_term_backend` (no `/memories/` prefix needed)
- `FilesystemMiddleware` tools require `/memories/` prefix to access same directory via CompositeBackend routing
- Agent sees: `ls /memories/` shows files in `~/.deepagents/{agent_name}/`
- Agent's `/memories/agent.md` and memory middleware's `/agent.md` point to the same file

**File Operations Behavior:**

```bash
# Agent tool calls and where they operate:
ls /                           # Lists CWD
ls /memories/                  # Lists ~/.deepagents/{agent_name}/
read_file /src/main.py        # Reads {CWD}/src/main.py
read_file /memories/guide.md  # Reads ~/.deepagents/{agent_name}/guide.md
write_file /memories/notes.md # Creates ~/.deepagents/{agent_name}/notes.md
edit_file /memories/agent.md  # Modifies agent's own system prompt!
```

**Virtual Mode Security:**

The `long_term_backend` uses `virtual_mode=True` which provides:
- Path sandboxing (all paths resolved relative to root_dir)
- No traversal (`..` and `~` rejected)
- No symlink following (O_NOFOLLOW flag when available)
- Paths treated as virtual absolute (e.g., `/notes.md` → `{root_dir}/notes.md`)

**Token Counting Implications:**

The complete system prompt includes:
1. `<agent_memory>` section (agent.md content)
2. Base system prompt from `get_system_prompt()`
3. `LONGTERM_MEMORY_SYSTEM_PROMPT` (instructions for using `/memories/`)

`calculate_baseline_tokens()` in `token_utils.py` accurately counts this by:
- Reading agent.md directly from filesystem
- Reconstructing the exact prompt as middleware builds it
- Using model's `get_num_tokens_from_messages()` for accurate count

### Critical Implementation Details

#### 1. Agent Creation Must Be Shared (CLI & Server)

**Rule**: Both CLI and LangGraph server MUST use the same agent creation logic.

**Implementation**: `agent.py:create_agent_with_config()` is the single source of truth. Both `main.py` (CLI) and `graph.py` (server export) use this function.

#### 2. Import Rules for graph.py

**Rule**: `graph.py` MUST use ABSOLUTE imports, NOT relative imports.

**Why**: LangGraph's module loader executes `graph.py` outside of package context.

```python
# ✅ Correct
from deepagents_cli.agent import create_agent_with_config
from deepagents_cli.tools import http_request, web_search

# ❌ Wrong - will break LangGraph server
from .agent import create_agent_with_config
```

#### 3. Context Manager vs Direct Construction

For long-running applications (CLI/server), use **direct construction** for checkpointers and stores:

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

## Key Files

| File | Purpose |
|------|---------|
| `libs/deepagents/graph.py` | Core factory, middleware stack |
| `libs/deepagents-cli/deepagents_cli/agent.py` | CLI agent creation (shared by CLI & server) |
| `libs/deepagents-cli/deepagents_cli/graph.py` | Server export for LangGraph |
| `libs/deepagents/middleware/filesystem.py` | File system tools implementation |
| `libs/deepagents/middleware/subagents.py` | Subagent spawning logic |
| `libs/deepagents-cli/deepagents_cli/agent_memory.py` | Agent memory middleware (loads agent.md into system prompt) |
| `libs/deepagents-cli/deepagents_cli/execution.py` | CLI execution loop |
| `libs/deepagents-cli/deepagents_cli/thread_manager.py` | Thread lifecycle management |
| `libs/deepagents/backends/composite.py` | CompositeBackend (routes `/memories/` to agent directory) |
| `libs/deepagents/backends/filesystem.py` | FilesystemBackend (disk-based file storage) |

---

## Environment Configuration

Create `libs/deepagents-cli/.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
TAVILY_API_KEY=tvly-dev-...              # Optional - for web search
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=deepagents-cli
DEEPAGENTS_DATABASE_URL=postgresql://localhost/deepagents
```

---

## Model Configuration

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

---

## Thread Management (CLI Feature)

**Thread ID Format**: Pure UUID (e.g., `a3f0c4d2-1b5e-4a7c-9d8e-2f3b1c4a5d6e`)

**Storage**:
- Thread metadata: `~/.deepagents/{agent_name}/threads.json`
- Checkpoints: `~/.deepagents/{agent_name}/checkpoints.db`

**In-Session Commands**:
- `/new [name]` - Create new thread
- `/threads` - Interactive picker (shows name, date, message count, tokens)
- `/threads continue <id>` - Switch to thread
- `/threads fork [name]` - Fork current thread
- `/threads info [id]` - Show thread details
- `/threads rename <id> <name>` - Rename thread

**Automatic Cleanup (Server Mode Only)**:
- Threads older than 14 days are automatically deleted when running with LangGraph server
- Cleanup runs every 2 hours in the background
- Standalone CLI does NOT run automatic cleanup

---

## LangGraph Server Integration

**Configuration** (`libs/deepagents-cli/langgraph.json`):
```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./deepagents_cli/graph.py:graph"
  },
  "env": ".env"
}
```

**Launch LangGraph Studio** (free visual debugging):
```bash
cd libs/deepagents-cli
langgraph dev
# Open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

**Features**: Visual graph execution flow, step-by-step debugging, state inspection, time-travel debugging.

---

## Debugging

### LangSmith Tracing
All agent runs automatically traced when `LANGCHAIN_TRACING_V2=true` is set. View at https://smith.langchain.com

### CLI Token Tracking
```bash
/tokens  # In-session command to show usage statistics
```

### Thread Debugging
```bash
/threads info           # Current thread details
/threads info <id>      # Specific thread details
```

### Database Inspection
```bash
# Check checkpoints
sqlite3 ~/.deepagents/agent/checkpoints.db
SELECT thread_id, checkpoint_ns, created_at FROM checkpoints ORDER BY created_at DESC LIMIT 10;

# Check threads
cat ~/.deepagents/agent/threads.json | jq
```

---

## Common Pitfalls

### 1. Relative Imports in graph.py
**Error**: `ImportError: attempted relative import with no known parent package`
**Fix**: Use absolute imports in `graph.py` (see Import Rules above)

### 2. Missing Dependencies After Upstream Merge
**Error**: `ModuleNotFoundError: No module named 'langchain_anthropic'`
**Fix**: Reinstall package: `cd libs/deepagents-cli && python3.11 -m pip install -e . --break-system-packages`

### 3. PostgreSQL Connection Errors
**Error**: `could not connect to server` or `database "deepagents" does not exist`
**Fix**: Start PostgreSQL (`brew services start postgresql@14`) and create database (`/opt/homebrew/opt/postgresql@14/bin/createdb deepagents`)

### 4. Agent Storage Location Confusion
- CLI storage: `~/.deepagents/{agent_name}/`
- `/memories/` maps to agent directory, NOT current working directory
- Regular file operations use current working directory

---

## Testing Guidelines

**Unit Tests** (`libs/deepagents/tests/unit_tests/`):
- Test individual middleware components and backend implementations
- Mock LangGraph/LangChain dependencies
- Fast execution (<1s per test)

**Integration Tests** (`libs/deepagents/tests/integration_tests/`):
- Test full agent workflows and CLI commands end-to-end
- Require API keys (ANTHROPIC_API_KEY)
- Slower execution (seconds to minutes)

**Test Isolation**: Always use temporary directories in tests to avoid interfering with user's agent data.

---

## Performance Considerations

### Prompt Caching
`AnthropicPromptCachingMiddleware` automatically enables Anthropic's prompt caching for repeated context.

**Best Practices**:
- Keep system prompts stable (cache hits)
- Use persistent memory (fewer repeated instructions)
- Avoid dynamically generated prompts when possible

### Token Management
`SummarizationMiddleware` automatically summarizes old messages when context > 170k tokens (keeps 6 most recent messages verbatim).

### Subagent Usage
**When to use**:
- ✅ Complex subtasks requiring focus
- ✅ Context isolation (prevent main agent pollution)
- ✅ Specialized tools/prompts

**When NOT to use**:
- ❌ Simple single-step operations
- ❌ Tasks requiring main agent context
- ❌ Cost-sensitive operations (spawns new agent)

---

## Additional Resources

- **Official Docs**: https://docs.langchain.com/oss/python/deepagents/overview
- **API Reference**: https://reference.langchain.com/python/deepagents/
- **LangGraph Docs**: https://langchain-ai.github.io/langgraph/
- **LangSmith**: https://smith.langchain.com
- **Repository**: https://github.com/langchain-ai/deepagents
- **Your Fork**: https://github.com/ASTXRTYS/DEEP-AI
