# DeepAgents CLI - Development Guide

This document contains critical information for working with the deepagents-cli codebase. Read this carefully before making changes.

## Project Overview

**Location**: `/Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli`

**What it is**: A CLI tool for running Deep Agents (LangChain's agent framework built on LangGraph). It provides:
- Interactive CLI for coding tasks with AI assistance
- Persistent memory across sessions (checkpointing + long-term storage)
- File system operations, shell commands, web search
- Human-in-the-loop approval for sensitive operations
- LangGraph dev server for free Studio debugging

**Parent Repo**: This is part of a monorepo at `/Users/Jason/astxrtys/DevTools/deepagents/` which includes:
- `libs/deepagents/` - Core Deep Agents library
- `libs/deepagents-cli/` - This CLI package

## Git Workflow

**Repository**: https://github.com/ASTXRTYS/DEEP-AI

This is a fork of LangChain's `deepagents` repository with custom enhancements. The git remote setup allows you to:
- Pull upstream updates from LangChain
- Push your changes to your own repository

### Remote Configuration

```bash
origin   → https://github.com/langchain-ai/deepagents.git  # LangChain upstream
upstream → git@github.com:ASTXRTYS/DEEP-AI.git             # Your repository
```

### Common Workflows

**Pull Latest Updates from LangChain**:
```bash
cd /Users/Jason/astxrtys/DevTools/deepagents

# Fetch latest from LangChain
git fetch origin

# Merge LangChain updates into your master branch
git checkout master
git merge origin/master

# Push merged updates to your repo
git push upstream master
```

**Make Changes and Push to Your Repo**:
```bash
# Make your changes
git add .
git commit -m "Your commit message"

# Push to your repository
git push upstream master
```

**Sync Your Repo with LangChain (Keep Fork Updated)**:
```bash
# Pull LangChain updates
git pull origin master

# Resolve any conflicts if they arise
# Then push to your repo
git push upstream master
```

**Create Feature Branches** (Recommended for large changes):
```bash
# Create feature branch from master
git checkout -b feature/my-feature

# Make changes and commit
git add .
git commit -m "Implement my feature"

# Push to your repo
git push upstream feature/my-feature

# When ready, merge to master
git checkout master
git merge feature/my-feature
git push upstream master
```

### Important Notes

- **origin** = LangChain's official repository (read-only for you, pull updates from here)
- **upstream** = Your DEEP-AI repository (read-write, push your changes here)
- Always test after merging LangChain updates to ensure compatibility
- Your custom enhancements (thread management, etc.) are in your repo only

---

## 🚨 MANDATORY: UI Development Guardrails

**CRITICAL**: Before making ANY changes to the CLI user interface, rendering, input handling, execution flow, or command system, you MUST read:

**`docs/ui-architecture-and-guardrails.md`**

This 600+ line document contains:
- Complete UI architecture map (Rich library, prompt_toolkit, LangGraph streaming)
- Critical code sections that MUST NOT be modified
- Safe patterns for extending the UI
- Known bugs and their fixes
- Thread management implementation requirements

### Non-Negotiable Rules

**🚫 DO NOT**:
1. **Create new Console instances** - Use the singleton from `config.py:76`
2. **Modify dual-mode streaming** in `execution.py:292-608` - You will break HITL
3. **Change tool call buffering** in `execution.py:491-574` - Streaming will break
4. **Break existing key bindings** - Ctrl+T, Alt+Enter, Ctrl+E are sacred
5. **Modify TokenTracker internals** without checking all 5+ usage sites
6. **Touch the HITL interrupt logic** in `execution.py:311-366`
7. **Mutate `agent.checkpointer` directly** - This is what breaks `/clear`!

### Critical Bug Alert

**⚠️ `/clear` command is BROKEN** (`commands.py:21`):
```python
# ❌ CURRENT CODE (DESTROYS PERSISTENCE):
agent.checkpointer = InMemorySaver()

# ✅ CORRECT FIX (use thread switching):
new_thread_id = thread_manager.create_thread()
thread_manager.switch_thread(new_thread_id)
```

The current implementation replaces SqliteSaver with InMemorySaver, **permanently destroying the persistent checkpointer**. This MUST be fixed as part of thread management implementation.

### When to Read the Guardrails

**Read `docs/ui-architecture-and-guardrails.md` if you need to**:
- Add new slash commands
- Modify rendering or output
- Change input handling or key bindings
- Alter execution flow or streaming
- Extend SessionState or TokenTracker
- Add UI elements (panels, tables, toolbars)
- Implement thread management features
- Fix the `/clear` bug

**Summary**: The guardrails document is your safety net. Read it first, code second. Violating these rules will break the CLI in subtle, hard-to-debug ways.

---

## Critical Architecture Decisions

### 1. Shared Agent Creation Logic

**CRITICAL**: Both the CLI and LangGraph server MUST use the exact same agent creation logic.

- **CLI**: Uses `create_agent_with_config()` from `deepagents_cli/agent.py`
- **Server**: Uses `create_agent_with_config()` from `deepagents_cli/graph.py` which imports from agent.py
- **Why**: Ensures consistency - server runs the EXACT same agent as CLI

### 2. Import Rules for graph.py

**CRITICAL**: `graph.py` MUST use ABSOLUTE imports, NOT relative imports.

```python
# ✅ CORRECT
from deepagents_cli.agent import create_agent_with_config
from deepagents_cli.tools import http_request, tavily_client, web_search

# ❌ WRONG - will break LangGraph server
from .agent import create_agent_with_config
from .tools import http_request, tavily_client, web_search
```

**Reason**: LangGraph's module loader executes graph.py outside of package context, so relative imports fail with "attempted relative import with no known parent package".

### 3. Memory Architecture

The agent has TWO types of persistent storage:

#### A. Checkpointing (Thread-level conversation memory)
- **Storage**: SQLite database at `~/.deepagents/{agent_name}/checkpoints.db`
- **Implementation**: `SqliteSaver` from `langgraph.checkpoint.sqlite`
- **Purpose**: Preserves conversation state, allows resuming threads
- **Scope**: Per-thread (each conversation has a thread_id)

#### B. Long-term Memory (Cross-conversation persistent storage)
- **Storage**: PostgreSQL database configured via `DEEPAGENTS_DATABASE_URL`
- **Implementation**: `PostgresStore` from `langgraph.store.postgres`
- **Purpose**: Knowledge that persists across all conversations
- **Scope**: Cross-thread, available to all conversations
- **Also**: Agent-specific files in `~/.deepagents/{agent_name}/`

#### C. File System Backend (Memory files)
- **Storage**: `~/.deepagents/{agent_name}/` directory
- **Implementation**: `CompositeBackend` with two routes:
  - **Default**: `FilesystemBackend()` - operates in current working directory
  - **/memories/**: `FilesystemBackend(root_dir=agent_dir)` - persistent agent memories
- **Purpose**: Agent can save/read files in `/memories/` that persist across sessions
- **Example**: Agent saves guides, preferences, or learned patterns in `/memories/guide.md`

### 4. Environment Configuration

**Location**: `.env` file in `/Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli/.env`

**IMPORTANT**: Environment variables were migrated from `~/.zshrc` to local `.env` for:
- Better portability
- LangGraph server compatibility (loads from .env via langgraph.json)
- Cleaner separation of concerns

**Required Variables**:
```bash
# API Keys
ANTHROPIC_API_KEY=sk-ant-api03-...
TAVILY_API_KEY=tvly-dev-...  # Optional - for web search

# LangSmith Tracing (free for local dev server)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=deepagents-cli

# PostgreSQL for long-term memory
DEEPAGENTS_DATABASE_URL=postgresql://localhost/deepagents
```

### 5. Tools Configuration

**Location**: `deepagents_cli/tools.py`

**Available Tools**:
1. `http_request` - Always available, makes HTTP requests
2. `web_search` - Only available if `TAVILY_API_KEY` is set

**Tool Loading Logic** (replicated in both CLI and server):
```python
tools = [http_request]
if tavily_client is not None:
    tools.append(web_search)
```

**CRITICAL**: Both `main.py` (CLI) and `graph.py` (server) use this EXACT same logic to ensure consistency.

## File Structure & Responsibilities

```
deepagents-cli/
├── .env                          # Environment variables (LOCAL, gitignored)
├── langgraph.json               # LangGraph server config (points to graph.py)
├── pyproject.toml               # Package dependencies & build config
├── start-dev-server.sh          # Launch LangGraph dev server only
├── start-dev.sh                 # Launch server + CLI together
├── start-tmux.sh                # Launch in tmux split panes
│
├── deepagents_cli/
│   ├── __init__.py
│   ├── __main__.py
│   │
│   ├── agent.py                 # ⭐ CORE: Agent creation & configuration
│   │   └── create_agent_with_config()  # Shared by CLI & server
│   │   └── get_system_prompt()         # Base system prompt
│   │   └── list_agents()               # Agent management
│   │   └── reset_agent()               # Agent reset/copy
│   │
│   ├── graph.py                 # ⭐ CRITICAL: LangGraph server export
│   │   └── graph                       # Module-level variable exported to server
│   │   └── _get_default_model()        # Model config for server
│   │   └── _get_default_tools()        # Tool config for server
│   │
│   ├── tools.py                 # Tool definitions
│   │   └── http_request()              # HTTP request tool
│   │   └── web_search()                # Tavily web search tool
│   │   └── tavily_client               # Tavily client instance
│   │
│   ├── main.py                  # CLI entry point & loop
│   │   └── cli_main()                  # Console script entry
│   │   └── simple_cli()                # Interactive loop
│   │
│   ├── execution.py             # Task execution logic
│   │   └── execute_task()              # Runs agent on user input
│   │
│   ├── agent_memory.py          # Memory middleware
│   │   └── AgentMemoryMiddleware       # Manages /memories/ access
│   │
│   ├── config.py                # Configuration & styling
│   │   └── create_model()              # Creates ChatAnthropic instance
│   │   └── get_default_coding_instructions()  # Default agent prompt
│   │
│   ├── ui.py                    # UI rendering & token tracking
│   ├── input.py                 # Prompt session handling
│   ├── commands.py              # Slash command handlers
│   ├── file_ops.py              # File operation utilities
│   └── token_utils.py           # Token counting utilities
│
└── ~/.deepagents/{agent_name}/  # Per-agent storage (user home dir)
    ├── checkpoints.db           # SQLite checkpointer database
    ├── agent.md                 # Agent-specific system prompt
    └── (various memory files)   # Long-term memory files
```

## Model Configuration

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
- Same model: claude-sonnet-4-5-20250929
- Configured via environment variables
- Includes API key validation

## System Prompt Structure

The final system prompt is composed of:

1. **Base System Prompt** (`agent.py:get_system_prompt()`):
   - Current working directory info
   - Memory system reminder (`/memories/` usage)
   - Human-in-the-loop tool approval guidelines
   - Web search tool usage instructions
   - Todo list management guidelines

2. **Agent-Specific Prompt** (`~/.deepagents/{agent_name}/agent.md`):
   - Custom instructions for this specific agent
   - Defaults to `config.get_default_coding_instructions()` if not exists

3. **Deep Agent Base Prompt** (from `deepagents` library):
   - Standard Deep Agent instructions
   - Added automatically by `create_deep_agent()`

## Middleware Stack

**Order matters!** The middleware is applied in this exact order:

### From create_deep_agent() (libs/deepagents/graph.py):
1. `TodoListMiddleware()` - Provides write_todos tool
2. `FilesystemMiddleware(backend=backend)` - Provides file operations
3. `SubAgentMiddleware(...)` - Provides task tool (spawn subagents)
4. `SummarizationMiddleware(...)` - Summarizes long conversations
5. `AnthropicPromptCachingMiddleware(...)` - Enables prompt caching
6. `PatchToolCallsMiddleware()` - Fixes tool call formatting
7. **Custom middleware** (passed via parameter)
8. `HumanInTheLoopMiddleware(interrupt_on=...)` - HITL approvals

### Custom Middleware (from agent.py):
1. `AgentMemoryMiddleware(backend=long_term_backend, memory_path="/memories/")` - Memory access
2. `ResumableShellToolMiddleware(workspace_root=os.getcwd(), ...)` - Shell commands

## Human-in-the-Loop (HITL) Configuration

**Location**: `agent.py:create_agent_with_config()` around line 254-296

**Tools requiring approval**:
1. `shell` - Shell command execution
2. `write_file` - File writing/overwriting
3. `edit_file` - File editing
4. `web_search` - Web search (uses Tavily API credits)
5. `task` - Subagent spawning

Each has a custom formatting function:
- `format_write_file_description()` - Shows file path, action, line count, size
- `format_edit_file_description()` - Shows file path, snippet delta
- `format_web_search_description()` - Shows query, max results, credit warning
- `format_task_description()` - Shows task description, subagent instructions

**Auto-Approve Mode**: `deepagents --auto-approve` disables HITL (not passed to agent creation)

## Dependencies

**Critical Dependencies** (added during server setup):
- `langchain-anthropic>=0.1.0` - Was missing, added to pyproject.toml
- `langchain-community>=0.1.0` - Was missing, added to pyproject.toml

**Core Dependencies**:
- `deepagents==0.2.4` - Core library (workspace dependency)
- `langgraph-checkpoint-sqlite>=3.0.0` - Checkpointing
- `langgraph-checkpoint-postgres>=3.0.0` - Not actually used yet, but installed
- `psycopg[binary,pool]>=3.0.0` - PostgreSQL driver (for store, not checkpointing)
- `tavily-python` - Web search
- `rich>=13.0.0` - Terminal UI
- `prompt-toolkit>=3.0.52` - Interactive input

## PostgreSQL Setup

**Database**: `deepagents`

**Creation** (if not exists):
```bash
# On macOS with Homebrew PostgreSQL 14
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents
```

**Connection**: `postgresql://localhost/deepagents`

**Schema Initialization**: Automatic on first run via `store.setup()` in agent.py

**Important**: This is for the `PostgresStore` (long-term memory), NOT for checkpointing. Checkpointing uses SQLite.

## LangGraph Server

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

### Key Points:
- **Graph ID**: `agent` - hardcoded as default assistant_id in graph.py
- **Export Format**: `./path/file.py:variable_name` - points to module-level `graph` variable
- **Environment**: Loads from `.env` file (specified in langgraph.json)
- **Auto-reload**: Watches for file changes and reloads automatically
- **Studio UI**: Free for local dev server (no API credits needed)

### URLs:
- **API**: http://127.0.0.1:2024
- **Studio UI**: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
- **API Docs**: http://127.0.0.1:2024/docs

### Server vs CLI:
- **Server**: Uses `assistant_id="agent"` (hardcoded in graph.py)
- **CLI**: Uses `assistant_id` from `--agent` flag (defaults to "agent")
- **Result**: By default, they share the same agent storage!

## Common Commands

### Server Management
```bash
# Start LangGraph dev server
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
langgraph dev

# Or use helper script
./start-dev-server.sh
```

### CLI Usage
```bash
# Start interactive CLI (default agent)
deepagents

# Use specific agent
deepagents --agent myagent

# Auto-approve mode (no HITL prompts)
deepagents --auto-approve

# List all agents
deepagents list

# Reset agent to default
deepagents reset --agent myagent

# Copy from another agent
deepagents reset --agent newagent --target existingagent

# Show help
deepagents help
```

### Development Workflow
```bash
# Start both server and CLI together
./start-dev.sh

# Or use tmux for split panes
./start-tmux.sh
```

## Helper Scripts

### 1. start-dev-server.sh
**Purpose**: Just start the LangGraph dev server
**Usage**: `./start-dev-server.sh`
**When**: When you only want to use Studio UI for debugging

### 2. start-dev.sh
**Purpose**: Start server in background, then CLI
**Usage**: `./start-dev.sh`
**Behavior**:
- Starts langgraph dev server in background
- Waits for server to be ready
- Launches CLI
- When CLI exits, automatically kills server

### 3. start-tmux.sh
**Purpose**: Create tmux session with split panes
**Usage**: `./start-tmux.sh`
**Layout**:
- Left pane: LangGraph dev server
- Right pane: CLI
**Controls**:
- `Ctrl+b, arrow keys` - Navigate panes
- `Ctrl+b, d` - Detach from session
- `tmux attach -t deepagents-dev` - Reattach

## Known Issues & Solutions

### Issue 1: Relative Import Error in graph.py
**Error**: `ImportError: attempted relative import with no known parent package`

**Cause**: LangGraph's module loader executes graph.py outside package context

**Solution**: Use absolute imports in graph.py
```python
from deepagents_cli.agent import create_agent_with_config  # ✅
from .agent import create_agent_with_config  # ❌
```

### Issue 2: Missing Dependencies
**Error**: `ModuleNotFoundError: No module named 'langchain_anthropic'` or `'langchain_community'`

**Cause**: These dependencies were missing from pyproject.toml

**Solution**: Already fixed - both are now in dependencies list. If you see this, run:
```bash
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
python3.11 -m pip install -e .
```

### Issue 3: use_longterm_memory Parameter Error
**Error**: `TypeError: create_deep_agent() got an unexpected keyword argument 'use_longterm_memory'`

**Cause**: This parameter doesn't exist in create_deep_agent() - it was removed/never existed

**Solution**: Already fixed in agent.py - just pass `store=` parameter. The store itself enables long-term memory.

### Issue 4: Checkpoint/Store API Errors (RESOLVED)
**Errors**:
- `'_GeneratorContextManager' object has no attribute 'get_next_version'`
- `PostgresStore.__init__() got an unexpected keyword argument 'connection_string'`

**Cause**: `from_conn_string()` methods return context managers (Iterators), not direct instances. Direct `__init__()` requires connection objects, not connection strings.

**Solution**: Use direct construction with connection objects for long-running applications:
```python
# For SqliteSaver
import sqlite3
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)

# For PostgresStore
import psycopg
pg_conn = psycopg.connect(database_url, autocommit=True)
store = PostgresStore(pg_conn)
```

**Note**: Context manager pattern (`with from_conn_string() as store:`) is for scripts, not long-running apps like the CLI.

### Issue 5: PostgreSQL Connection Error
**Error**: `could not connect to server` or `database "deepagents" does not exist`

**Solution**:
```bash
# Start PostgreSQL (if not running)
brew services start postgresql@14

# Create database
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents
```

## Debugging & Tracing

### LangSmith Integration
- **Enabled**: `LANGCHAIN_TRACING_V2=true` in .env
- **Project**: `deepagents-cli`
- **Access**: https://smith.langchain.com
- **Cost**: Free for local dev server

### Studio UI
- **Access**: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
- **Features**:
  - Visual graph execution
  - Step-by-step debugging
  - State inspection
  - Time travel debugging
  - Free for local dev server

### CLI Debugging
- Errors printed to console with rich formatting
- Token usage tracked per interaction
- `/tokens` command shows usage statistics

## Important Implementation Details

### 1. create_deep_agent() Signature
**Location**: `/Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents/graph.py:40`

**Key Parameters**:
```python
def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    response_format: ResponseFormat | None = None,
    context_schema: type[Any] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,  # ⭐ This enables long-term memory
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
) -> CompiledStateGraph:
```

**Note**: NO `use_longterm_memory` parameter! Just pass `store=` to enable.

### 2. Agent Storage Locations
- **Checkpoints**: `~/.deepagents/{agent_name}/checkpoints.db`
- **Agent Prompt**: `~/.deepagents/{agent_name}/agent.md`
- **Memory Files**: `~/.deepagents/{agent_name}/*` (accessed via `/memories/` prefix)
- **Long-term Store**: PostgreSQL database (shared across all agents)

### 3. Thread ID Management

**Location**: `execution.py:execute_task()` line 210

**Current Implementation** (as of 2025-01-11):
```python
config = {"configurable": {"thread_id": assistant_id or "main"}}
```

**Current Behavior**:
- `thread_id = assistant_id` (static, no timestamp/UUID)
- Same agent name = same thread forever
- No built-in thread rotation or switching
- Conversations persist across CLI sessions (by design)

**Known Issue**: Long-running agents accumulate 1M+ tokens in single thread with no easy way to start fresh while keeping memory files.

**Planned Enhancement** (See docs/thread-management-proposal.md):
- Add ThreadManager for in-CLI thread control
- Amp-style commands: `/new`, `/threads`, `/threads continue <id>`
- Thread ID format: `{assistant_id}:{uuid_short}` (e.g., `agent:a1b2c3d4`)
- Metadata in `~/.deepagents/{agent}/threads.json`
- Memory files (`/memories/`) remain accessible across all threads

### 4. Checkpoint and Store Initialization Pattern

**CRITICAL**: For long-running applications like the CLI, use direct construction:

```python
# Checkpointer (conversation state)
import sqlite3
conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()  # Initialize schema

# Store (long-term memory)
import psycopg
pg_conn = psycopg.connect(database_url, autocommit=True)
store = PostgresStore(pg_conn)
store.setup()  # Initialize schema
```

**NEVER use** `from_conn_string()` which returns a context manager:
```python
# ❌ WRONG - returns Iterator/context manager, causes errors
checkpointer = SqliteSaver.from_conn_string(...)
store = PostgresStore.from_conn_string(...)
```

**Context manager pattern** is only for short-lived scripts:
```python
# Only for scripts, NOT for CLI/server
with PostgresStore.from_conn_string(db_uri) as store:
    graph = builder.compile(store=store)
```

### 5. CompositeBackend Routes
```python
backend = CompositeBackend(
    default=FilesystemBackend(),  # CWD operations
    routes={
        "/memories/": long_term_backend  # Persistent agent storage
    }
)
```

**Usage by Agent**:
- `ls /memories/` - List persistent memory files
- `read_file /memories/guide.md` - Read from agent storage
- `write_file /memories/note.txt` - Write to agent storage
- `ls` (no prefix) - List files in current working directory
- `read_file main.py` - Read from current working directory

## Testing Checklist

Before committing changes, verify:

- [ ] LangGraph server starts without errors: `langgraph dev`
- [ ] Server registers the graph: Look for "Registering graph with id 'agent'"
- [ ] CLI starts without errors: `deepagents`
- [ ] Both server and CLI can execute tasks
- [ ] Memory persists across sessions
- [ ] HITL prompts work correctly
- [ ] Web search works (if TAVILY_API_KEY is set)
- [ ] File operations work in both CWD and /memories/
- [ ] Auto-approve mode works: `deepagents --auto-approve`
- [ ] Agent listing works: `deepagents list`
- [ ] Agent reset works: `deepagents reset --agent test`

## Package Installation

**Development Install**:
```bash
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

**Why `--break-system-packages`**: macOS Homebrew Python protection

**Editable Install**: Changes to source code immediately affect installed package

## Key Takeaways for Future Sessions

1. **Never use relative imports in graph.py** - Always absolute
2. **create_deep_agent() has NO use_longterm_memory parameter** - Use store=
3. **Both CLI and server MUST share create_agent_with_config()** - Consistency
4. **Environment is in .env, not .zshrc** - For portability
5. **PostgreSQL is for store (long-term), SQLite for checkpointing** - Different purposes
6. **Memory system has two parts**: Checkpointing + Store
7. **Tools must match between CLI and server** - Same list building logic
8. **/memories/ is virtual path to ~/.deepagents/{agent_name}/** - Not CWD
9. **Server auto-reloads, CLI doesn't** - Restart CLI for changes
10. **Studio UI is free for local server** - No API credits needed

## Quick Reference

| Component | Location | Purpose |
|-----------|----------|---------|
| Agent creation | `agent.py:create_agent_with_config()` | Shared logic for CLI & server |
| Server export | `graph.py:graph` | Module-level variable for LangGraph |
| Tools | `tools.py` | http_request, web_search |
| Environment | `.env` | API keys, configuration |
| Server config | `langgraph.json` | Points to graph.py |
| CLI entry | `main.py:cli_main()` | Console script |
| Execution | `execution.py:execute_task()` | Task runner |
| Memory | `agent_memory.py` | Memory middleware |
| Checkpoints | `~/.deepagents/{agent}/checkpoints.db` | SQLite |
| Store | `postgresql://localhost/deepagents` | PostgreSQL |
| Agent storage | `~/.deepagents/{agent}/` | Memory files |

---

## Planned Enhancements

### Thread Management System (Planned - See docs/thread-management-proposal.md)

**Problem**: Current implementation uses static `thread_id = assistant_id`, causing single thread to grow indefinitely (user experienced 1M+ tokens).

**Solution**: Amp-style in-CLI thread management
- ThreadManager class for thread lifecycle
- Slash commands: `/new`, `/threads`, `/threads continue <id>`, `/threads fork`
- Thread metadata storage in `threads.json`
- Fixed `/clear` command (creates new thread instead of breaking persistence)

**Safety**: Validated safe by LangGraph documentation
- Thread switching is intended behavior
- Checkpointer handles multiple threads automatically
- Backward compatible - existing checkpoints untouched
- Easy rollback via git branches

**Implementation**: Phased approach on `Deep-AI-CLI` branch
1. Phase 1: Core ThreadManager class (non-breaking)
2. Phase 2: Slash commands (additive)
3. Phase 3: Integration with execution.py (behavior change)
4. Phase 4: Polish features (optional)

**Status**: UI guardrails documented, ready to implement Phase 1

**Documentation**:
- Thread management plan: `docs/thread-management-proposal.md` (587 lines)
- UI architecture & guardrails: `docs/ui-architecture-and-guardrails.md` (620 lines)

---

**Last Updated**: 2025-01-11
**By**: Claude (Sonnet 4.5)
**Session Context**:
- Completed thread management research and planning
- Created GitHub repository (DEEP-AI)
- Added git workflow documentation for maintaining fork
- Created comprehensive UI architecture and guardrails documentation
- Added mandatory guardrails section to CLAUDE.md for future Claude instances
- Branch: Deep-AI-CLI (ready for Phase 1 implementation)
