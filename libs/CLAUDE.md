# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Overview

This is the **libs/** directory of the DeepAgents monorepo, containing two interdependent Python packages managed as a **uv workspace**:

```
libs/
├── deepagents/          # Core library (0.2.5)
│   └── CLAUDE.md       # Core library-specific guidance
└── deepagents-cli/      # CLI application (0.0.7)
    └── CLAUDE.md       # CLI-specific guidance
```

**Package Relationship**: `deepagents-cli` depends on `deepagents` as a workspace dependency. Changes to the core library require testing both packages.

## Quick Commands

All commands below assume you're at the **repository root** (`/Users/Jason/astxrtys/DevTools/deepagents/`).

### Testing Both Packages

```bash
# Test core library
make test

# Test CLI
cd libs/deepagents-cli && make test

# Test both (run sequentially)
make test && cd libs/deepagents-cli && make test && cd ../..
```

### Linting & Formatting

```bash
# Format all code in workspace
make format

# Lint all code
make lint

# Lint only changed files (vs master)
make lint_diff
```

### Package Management with uv

```bash
# Install all workspace dependencies
uv sync

# Add dependency to core library
cd libs/deepagents
uv add <package-name>

# Add dependency to CLI
cd libs/deepagents-cli
uv add <package-name>

# Update lockfile after manual pyproject.toml changes
uv lock
```

## Architecture Overview

### Two-Package Design

**1. deepagents (Core Library)**
- **Purpose**: General-purpose "deep agent" framework built on LangGraph
- **Key Features**: Planning (TodoList), File System operations, Subagent spawning
- **Exported API**: `create_deep_agent()` factory function
- **Architecture**: Middleware-based composition, backend abstraction for storage
- **Location**: `libs/deepagents/`
- **Detailed Docs**: See `libs/deepagents/CLAUDE.md`

**2. deepagents-cli (CLI Application)**
- **Purpose**: Interactive terminal interface for coding assistance
- **Key Features**: Thread management, Rich UI, LangGraph server integration, HITL workflows
- **Architecture**: Dual deployment (standalone CLI + LangGraph server), persistent storage
- **Dependency**: Uses `deepagents` for agent creation
- **Location**: `libs/deepagents-cli/`
- **Detailed Docs**: See `libs/deepagents-cli/CLAUDE.md`

### Shared Agent Creation Pattern

**Critical**: Both CLI and LangGraph Server MUST use the same agent creation logic to ensure consistency.

**Shared Function**: `deepagents_cli/agent.py:create_agent_with_config()`
- **Used by CLI**: `main.py` → `execution.py` → `agent.py:create_agent_with_config()`
- **Used by Server**: `graph.py` imports and exports → `agent.py:create_agent_with_config()`

This ensures the agent behaves identically in both deployment modes.

## Development Workflows

### Making Changes to Core Library

When modifying `libs/deepagents/`:

```bash
# 1. Make changes to core library
vim libs/deepagents/graph.py

# 2. Run core library tests
make test

# 3. Test CLI (which depends on core)
cd libs/deepagents-cli && make test

# 4. If tests pass, check linting
make lint

# 5. Format if needed
make format
```

**Why test both**: The CLI depends on the core library. Breaking changes in core will break the CLI.

### Making Changes to CLI

When modifying `libs/deepagents-cli/`:

```bash
# 1. Make changes to CLI
vim libs/deepagents-cli/deepagents_cli/main.py

# 2. Run CLI tests only
cd libs/deepagents-cli && make test

# 3. Run the CLI locally to verify
deepagents

# 4. Test with LangGraph server
cd libs/deepagents-cli
langgraph dev  # Terminal 1
deepagents     # Terminal 2
```

### Adding Dependencies

**To core library** (`libs/deepagents/`):
```bash
cd libs/deepagents
uv add <package-name>
# This updates libs/deepagents/pyproject.toml and regenerates uv.lock
```

**To CLI** (`libs/deepagents-cli/`):
```bash
cd libs/deepagents-cli
uv add <package-name>
# This updates libs/deepagents-cli/pyproject.toml and regenerates uv.lock
```

**Important**: The workspace lockfile (`uv.lock` at repo root) is shared. Always run `uv sync` after pulling changes to ensure dependencies are up-to-date.

## CI/CD Structure

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs:

**Lint Jobs** (parallel):
1. Core library linting (Python 3.11)
2. CLI linting (Python 3.11)

**Test Jobs** (parallel matrix):
1. Core library tests (Python 3.11, 3.12, 3.13)
2. CLI tests (Python 3.11, 3.13)

**Both packages must pass** for CI to succeed.

## Common Patterns

### 1. Middleware Development

**Core library** provides middleware building blocks (`libs/deepagents/middleware/`):
- `TodoListMiddleware` - Planning tool
- `FilesystemMiddleware` - File operations
- `SubAgentMiddleware` - Subagent spawning
- Custom middleware base class: `AgentMiddleware`

**CLI** extends with custom middleware (`libs/deepagents-cli/deepagents_cli/`):
- `AgentMemoryMiddleware` - Virtual `/memories/` path routing
- `HandoffApprovalMiddleware` - Thread handoff HITL
- `ResumableShellToolMiddleware` - Shell command execution

**Pattern**: Core provides reusable components, CLI adds application-specific behavior.

### 2. Backend Abstraction

**Core library** defines `BackendProtocol` and implementations:
- `FilesystemBackend` - Local disk storage
- `StateBackend` - LangGraph state storage
- `StoreBackend` - LangGraph Store (PostgreSQL/Redis)
- `CompositeBackend` - Path-based routing

**CLI** uses `CompositeBackend` to route:
- Default path → `FilesystemBackend()` (CWD)
- `/memories/` → `FilesystemBackend(root_dir=~/.deepagents/{agent}/)`

**Pattern**: Core provides storage abstraction, CLI configures for specific use case.

### 3. Tool Development

**Define in core** (`libs/deepagents/middleware/`) if:
- General-purpose tool (useful beyond CLI)
- Part of the "deep agent" pattern (planning, files, subagents)
- Reusable across applications

**Define in CLI** (`libs/deepagents-cli/tools.py`) if:
- Application-specific (web search, http requests)
- Requires CLI-specific configuration
- Used only by this CLI

## Testing Strategy

### Unit Tests

**Core library** (`libs/deepagents/tests/unit_tests/`):
- Middleware behavior
- Backend implementations
- Tool definitions
- No LLM calls (use `FakeChatModel`)

**CLI** (`libs/deepagents-cli/tests/`):
- Thread management
- Command handlers
- File operations
- Socket access disabled (`--disable-socket`)

### Integration Tests

**Core library** (`libs/deepagents/tests/integration_tests/`):
- Full agent execution
- Real LLM calls (requires `ANTHROPIC_API_KEY`)
- End-to-end workflows
- HITL patterns

**CLI**: Integration tests run manually (interactive nature of CLI)

### Test Isolation

- **Parallel execution**: Core tests use `pytest-xdist` for speed
- **Timeouts**: CLI tests have 10-second timeout per test
- **Mocking**: External APIs mocked in unit tests
- **Fixtures**: `conftest.py` provides shared fixtures

## Import Rules

### Standard Rule (Most Files)

Use relative or absolute imports freely:
```python
# Both OK in regular files
from .middleware import MyMiddleware
from deepagents.middleware import MyMiddleware
```

### Exception: graph.py (CLI only)

**Only** `libs/deepagents-cli/graph.py` MUST use absolute imports:
```python
# ✅ CORRECT in graph.py
from deepagents_cli.agent import create_agent_with_config

# ❌ WRONG in graph.py (breaks LangGraph server)
from .agent import create_agent_with_config
```

**Reason**: LangGraph's module loader executes `graph.py` outside of package context, breaking relative imports.

## Package-Specific Guidance

For detailed information about each package:

### Core Library (deepagents)
- **File**: `libs/deepagents/CLAUDE.md`
- **Topics**: Middleware architecture, backend system, `create_deep_agent()` details, testing patterns

### CLI Application (deepagents-cli)
- **File**: `libs/deepagents-cli/CLAUDE.md`
- **Topics**: Dual deployment model, persistence layers, thread management, HITL workflows, UI architecture

## Key Principles

1. **Separation of Concerns**: Core library provides building blocks, CLI assembles them into an application
2. **Consistency**: CLI and Server use identical agent creation logic
3. **Testability**: Changes to core library require testing both packages
4. **Workspace Awareness**: Use `uv` commands at repo root, respects workspace relationships
5. **Documentation**: Each package maintains its own detailed CLAUDE.md

## Common Pitfalls

### 1. Breaking CLI by Changing Core

**Problem**: Modifying core library API without updating CLI usage

**Solution**: Always test CLI after core library changes
```bash
make test && cd libs/deepagents-cli && make test
```

### 2. Diverging Agent Creation Logic

**Problem**: CLI and server create agents differently, causing inconsistent behavior

**Solution**: Both MUST call `deepagents_cli.agent:create_agent_with_config()`

### 3. Workspace Dependency Issues

**Problem**: CLI not picking up latest core library changes

**Solution**:
```bash
# Reinstall workspace dependencies
uv sync

# Or reinstall CLI in editable mode
cd libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

### 4. Forgetting to Update Lockfile

**Problem**: Manual `pyproject.toml` edits not reflected in `uv.lock`

**Solution**: Run `uv lock` after manual dependency changes

## Development Checklist

Before committing changes:

- [ ] Run tests for affected package(s)
- [ ] If core library changed: Run CLI tests
- [ ] Run linting: `make lint`
- [ ] Format code: `make format`
- [ ] Update relevant CLAUDE.md if architecture changed
- [ ] Ensure `uv.lock` is committed if dependencies changed
- [ ] Check CI passes locally before pushing

## Git Workflow

**Repository**: Fork of `langchain-ai/deepagents` at `ASTXRTYS/DEEP-AI`

**Remotes**:
- `origin` → LangChain upstream (pull updates from here)
- `upstream` → Your fork (push changes here)

**Typical workflow**:
```bash
# Pull LangChain updates
git pull origin master

# Make changes and test
# ...

# Push to your fork
git push upstream master
```

## Summary

This workspace contains two interdependent packages:
- **deepagents**: Reusable "deep agent" framework (middleware, backends, core tools)
- **deepagents-cli**: Application using the framework (UI, thread management, persistence)

**When working here**:
1. Check package-specific CLAUDE.md for detailed guidance
2. Test both packages if modifying core library
3. Use `uv` for workspace-aware dependency management
4. Maintain consistency between CLI and server agent creation
5. Follow import rules (absolute imports in `graph.py` only)

For deep dives into architecture, see the package-specific CLAUDE.md files in each subdirectory.
