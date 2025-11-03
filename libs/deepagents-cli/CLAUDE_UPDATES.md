# Suggested Updates to CLAUDE.md

## Add Development Commands Section

Insert after line 612 (after "## Helper Scripts"):

```markdown
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

# Watch mode (requires ptw)
make test_watch
```

**Test Configuration:**
- Socket access is disabled by default to prevent unintended network calls
- Unix sockets are allowed for local IPC
- 10-second timeout per test
- Located in `tests/` directory

### Linting and Formatting

```bash
# Check code style (ruff)
make lint

# Auto-format code
make format

# Lint only changed files (vs master branch)
make lint_diff

# Format only changed files
make format_diff

# Run ruff directly
uv run ruff check deepagents_cli/
uv run ruff format deepagents_cli/
```

**Linting Configuration** (`pyproject.toml`):
- Line length: 100 characters
- Uses Ruff with "ALL" rules enabled by default
- Google-style docstrings
- Key ignores: COM812, ISC001, PERF203, SLF001, PLC0415, PLR0913, PLC0414, C901
- See `pyproject.toml` for full configuration

### Building and Installation

```bash
# Development install (editable mode)
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages

# Install with uv (faster)
uv pip install -e .

# Reinstall dependencies
uv pip install -e . --force-reinstall
```

---
```

## Update File Structure Section

Line 358-416 should be updated to note that:
- `cli.py` is a stub/placeholder (just prints "I'm alive!")
- `main.py` contains the actual CLI implementation
- Add missing files like `resumable_shell_async.py`

```markdown
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
│   ├── cli.py                   # Console script stub (placeholder)
│   │   └── cli_main()                  # Prints "I'm alive!" - unused
│   │
│   ├── main.py                  # ⭐ ACTUAL CLI entry point & loop
│   │   └── simple_cli()                # Interactive loop
│   │   └── check_cli_dependencies()    # Dependency checker
│   │
│   ├── execution.py             # Task execution logic
│   │   └── execute_task()              # Runs agent on user input
│   │
│   ├── agent_memory.py          # Memory middleware
│   │   └── AgentMemoryMiddleware       # Manages /memories/ access
│   │
│   ├── resumable_shell_async.py # Async shell execution
│   │   └── ResumableShellToolMiddleware # Shell middleware
│   │
│   ├── config.py                # Configuration & styling
│   │   └── create_model()              # Creates ChatAnthropic instance
│   │   └── get_default_coding_instructions()  # Default agent prompt
│   │   └── SessionState                # Session state dataclass
│   │
│   ├── ui.py                    # UI rendering & token tracking
│   │   └── TokenTracker               # Token usage tracking
│   │   └── show_help()                # Help display
│   │
│   ├── input.py                 # Prompt session handling
│   │   └── create_prompt_session()    # prompt_toolkit setup
│   │
│   ├── commands.py              # Slash command handlers
│   │   └── handle_command()           # Command dispatcher
│   │   └── execute_bash_command()     # Shell command execution
│   │
│   ├── file_ops.py              # File operation utilities
│   ├── token_utils.py           # Token counting utilities
│   └── thread_manager.py        # Thread management (ThreadManager class)
```

## Fix or Remove UI Guardrails Section

Lines 207-258 extensively reference `docs/ui-architecture-and-guardrails.md` which doesn't exist. Either:

**Option 1: Remove it entirely**
```markdown
## 🚨 UI Development Guardrails

**CRITICAL**: The CLI UI is complex and fragile. Before making changes to:
- User interface rendering
- Input handling
- Execution flow
- Command system
- Streaming logic

Carefully review the existing code in these critical files:
- `execution.py:292-608` - Dual-mode streaming (DO NOT modify)
- `execution.py:491-574` - Tool call buffering (DO NOT modify)
- `execution.py:311-366` - HITL interrupt logic (DO NOT modify)
- `config.py:76` - Console singleton (reuse, don't create new instances)
- `ui.py` - TokenTracker (check all usage sites before modifying)
```

**Option 2: Mark as TODO**
```markdown
## 🚨 UI Development Guardrails

**TODO**: Comprehensive UI architecture documentation is planned for `docs/ui-architecture-and-guardrails.md`

Until then, exercise extreme caution when modifying:
- Streaming logic in `execution.py`
- Input handling in `input.py`
- UI rendering in `ui.py`
- Command handling in `commands.py`
```

## Add Quick Start Section

Add at the very top after "Memory System" section for developers new to the project:

```markdown
---

## Quick Start for New Developers

### First Time Setup
```bash
# 1. Clone the repository
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli

# 2. Create .env file with API keys (see .env.example or README)
cp .env.example .env  # Then edit with your keys

# 3. Install dependencies
python3.11 -m pip install -e . --break-system-packages

# 4. Start PostgreSQL
brew services start postgresql@14
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents

# 5. Run the CLI
deepagents
```

### Development Workflow
```bash
# 1. Make your changes to the code

# 2. Run tests
make test

# 3. Format and lint
make format
make lint

# 4. Test the CLI
deepagents --agent test

# 5. Test with Studio (optional)
./start-dev.sh
```

### Common Issues on First Run
See "Known Issues & Solutions" section for detailed troubleshooting.
```

---
```
