# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Library Overview

**DeepAgents Core Library** - The foundational library implementing the "deep agent" pattern with planning, file system access, and subagent spawning capabilities built on LangGraph.

**Location:** `libs/deepagents/` within the deepagents monorepo
**Package Name:** `deepagents`
**Version:** 0.2.5

For workspace-level commands (setup, testing across both packages), see `/Users/Jason/astxrtys/DevTools/deepagents/CLAUDE.md` at the repository root.

## Core Library Commands

All commands assume you're at the **repository root** (`/Users/Jason/astxrtys/DevTools/deepagents/`), not in `libs/deepagents/`.

### Testing

```bash
# Unit tests (fast, no external API calls)
make test
# Equivalent: uv run pytest libs/deepagents/tests/unit_tests --cov=deepagents --cov-report=term-missing

# Integration tests (requires API keys, makes real LLM calls)
make integration_test
# Equivalent: uv run pytest libs/deepagents/tests/integration_tests --cov=deepagents --cov-report=term-missing

# Run specific test file
uv run pytest libs/deepagents/tests/unit_tests/test_specific.py

# Run specific test function
uv run pytest libs/deepagents/tests/unit_tests/test_file.py::test_function_name

# Run with verbose output
uv run pytest libs/deepagents/tests/unit_tests -v
```

### Linting & Formatting

```bash
# Format all code
make format

# Lint without auto-fixing
make lint

# Lint only the core package
make lint_package

# Lint only tests
make lint_tests

# Lint changes since master branch
make lint_diff
```

**Tools:** `ruff` (format + lint), `mypy` (type checking)

### Building & Installing

```bash
# Build distribution packages
uv build

# Install in development mode (changes immediately reflected)
uv pip install -e libs/deepagents
```

## Architecture

### The Core Abstraction: `create_deep_agent()`

**Location:** `libs/deepagents/graph.py:41`

This is the primary entry point that creates a LangGraph agent with built-in capabilities:

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
    store: BaseStore | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
) -> CompiledStateGraph
```

**Returns:** A compiled LangGraph `StateGraph` with all middleware and tools attached.

**Key insight:** This function is really just a **middleware composer** around LangChain's `create_agent()`. The "deep" part comes from the specific middleware stack it assembles.

### Middleware Stack (Execution Order)

Middleware attaches in the order listed, but **`after_model()` hooks execute in reverse order**:

```python
[
    1. TodoListMiddleware()                         # Planning with write_todos tool
    2. handle_filesystem_permissions                # Guards for file operations
    3. FilesystemMiddleware(backend=backend)        # File tools: ls, read_file, write_file, edit_file, glob_search, grep_search
    4. SubAgentMiddleware(...)                      # Subagent spawning with task tool
    5. SummarizationMiddleware(...)                 # Automatic conversation summarization
    6. SafeAnthropicPromptCachingMiddleware(...)    # Prompt caching for Anthropic models
    7. PatchToolCallsMiddleware()                   # Fixes tool call formatting edge cases
    8. *middleware (user-provided)                  # Custom middleware from parameters
    9. HumanInTheLoopMiddleware(...)                # HITL approvals (only if interrupt_on configured)
]
```

**Critical execution detail:**
- `before_agent()` → runs in **forward order** (1→9)
- `before_model()` → runs in **forward order** (1→9)
- `after_model()` → runs in **REVERSE order** (9→1) ⚠️
- `before_tool()` → runs in **forward order** (1→9)
- `after_tool()` → runs in **forward order** (1→9)

### Three Pillars of Deep Agents

#### 1. Planning - TodoListMiddleware

**File:** `libs/deepagents/../langchain/agents/middleware/todo_list.py` (in langchain core)

**What it does:**
- Adds `write_todos` tool to the agent
- Injects system prompt instructing agent to break down complex tasks
- Manages todo list state in the graph

**Usage pattern:**
```python
# Included by default in create_deep_agent()
# Can also use standalone:
from langchain.agents.middleware import TodoListMiddleware

agent = create_agent(
    model="claude-sonnet-4-5-20250929",
    middleware=[TodoListMiddleware()]
)
```

#### 2. File System - FilesystemMiddleware

**File:** `libs/deepagents/middleware/filesystem.py`

**Provides 6 tools:**
- `ls` - List files/directories
- `read_file` - Read file content with line numbers
- `write_file` - Create new file
- `edit_file` - Replace strings in existing file
- `glob_search` - Pattern-based file search (like `find`)
- `grep_search` - Content-based file search (regex)

**Backend abstraction:**
```python
FilesystemMiddleware(backend=backend)
```

The `backend` parameter implements the `BackendProtocol` and determines WHERE files are stored:
- `FilesystemBackend` - Local disk
- `StateBackend` - LangGraph state (checkpointed with conversation)
- `StoreBackend` - LangGraph Store (PostgreSQL/Redis)
- `CompositeBackend` - Route different paths to different backends

**Key architectural decision:** File operations are backend-agnostic. The same tools work whether files are stored in state, on disk, or in a database.

#### 3. Subagents - SubAgentMiddleware

**File:** `libs/deepagents/middleware/subagents.py`

**What it does:**
- Adds `task` tool for spawning subagents
- Subagents are isolated agent instances with their own context
- Main agent hands off work to subagents and receives results
- Prevents context window pollution

**Subagent types:**

1. **SubAgent** (dict-based config):
```python
{
    "name": "researcher",
    "description": "Researches topics in depth",
    "prompt": "You are an expert researcher...",
    "tools": [web_search],
    "model": "gpt-4o",  # Optional
    "middleware": []    # Optional
}
```

2. **CompiledSubAgent** (pre-built graph):
```python
{
    "name": "analyzer",
    "description": "Analyzes data",
    "runnable": my_langgraph_graph  # Pre-compiled StateGraph
}
```

**Recursion:** Subagents created by SubAgentMiddleware also have the full middleware stack (including SubAgentMiddleware), so they can spawn their own subagents.

### Backend System

**Location:** `libs/deepagents/backends/`

The backend system abstracts storage for file operations, allowing the same tools to work with different storage implementations.

**Protocol:** All backends implement `BackendProtocol` defined in `backends/protocol.py`:

```python
class BackendProtocol(Protocol):
    def ls_info(self, path: str) -> list[FileInfo]: ...
    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str: ...
    def write(self, file_path: str, content: str) -> WriteResult: ...
    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult: ...
    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> list[GrepMatch] | str: ...
    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]: ...
```

**Implementations:**

1. **FilesystemBackend** (`backends/filesystem.py`)
   - Stores files on local disk
   - Takes optional `root_dir` parameter
   - Best for: Local development, CLIs, single-user applications

2. **StateBackend** (`backends/state.py`)
   - Stores files in LangGraph state
   - Files are checkpointed with conversation
   - Best for: Small files that should persist with conversation history

3. **StoreBackend** (`backends/store.py`)
   - Stores files in LangGraph Store (PostgreSQL/Redis)
   - Requires passing `store=` to `create_deep_agent()`
   - Best for: Multi-instance deployments, cloud applications

4. **CompositeBackend** (`backends/composite.py`)
   - Routes operations to different backends based on path prefix
   - Example: `/memories/` → StoreBackend, everything else → FilesystemBackend
   - Enables hybrid storage strategies

**Factory pattern:**
```python
# Direct backend instance
backend = FilesystemBackend(root_dir="/path/to/storage")

# Factory function (gets ToolRuntime at initialization)
backend = lambda rt: StateBackend(rt)
```

### Middleware Architecture

**Base class:** `langchain.agents.middleware.AgentMiddleware` (in langchain core)

**Hook methods:**
```python
class MyMiddleware(AgentMiddleware):
    tools = [my_tool]  # Optional: tools to add

    def before_agent(self, agent_input, config, **kwargs):
        """Called once before agent starts executing"""

    def before_model(self, messages, agent_input, config, **kwargs):
        """Called before each model invocation"""

    def after_model(self, messages, agent_input, config, **kwargs):
        """Called after each model invocation (REVERSE ORDER!)"""
        yield from messages  # Must yield messages

    def before_tool(self, tool_input, tool_name, config, **kwargs):
        """Called before each tool invocation"""

    def after_tool(self, tool_output, tool_name, config, **kwargs):
        """Called after each tool invocation"""
```

**Critical patterns:**

1. **after_model() must yield:** This is a generator that can modify the message stream
2. **Reverse order in after_model():** Last middleware attached runs first
3. **interrupt() calls:** Can be emitted in after_model() for HITL patterns
4. **Accessing state:** Via `config["configurable"]["tools_runtime"].state`

### Handoff Middleware (Advanced Pattern)

**Files:** `middleware/handoff_*.py`

These implement an advanced pattern for transferring control between agents:

- **HandoffToolMiddleware** - Adds `request_handoff` tool
- **HandoffApprovalMiddleware** - Implements HITL approval for handoffs
- **HandoffSummarizationMiddleware** - Generates summaries when handing off
- **HandoffCleanupMiddleware** - Cleans up temporary state after handoff

**Use case:** Multi-agent workflows where one agent can explicitly hand off to another (different from subagents which return to caller).

### ResumableShellToolMiddleware

**File:** `middleware/resumable_shell.py`

Provides a `shell` tool that can execute bash commands with special handling:
- Long-running commands can be resumed
- Background process management
- Workspace root sandboxing

## Common Development Patterns

### Adding New Middleware

1. **Create middleware class:**
```python
# libs/deepagents/middleware/my_feature.py
from langchain.agents.middleware import AgentMiddleware

class MyFeatureMiddleware(AgentMiddleware):
    tools = [my_tool] if you_need_tools else []

    def __init__(self, param: str):
        self.param = param

    def after_model(self, messages, agent_input, config, **kwargs):
        # Your logic here
        yield from messages
```

2. **Export in `__init__.py`:**
```python
# libs/deepagents/middleware/__init__.py
from deepagents.middleware.my_feature import MyFeatureMiddleware

__all__ = [..., "MyFeatureMiddleware"]
```

3. **Add to package exports (if public):**
```python
# libs/deepagents/__init__.py
from deepagents.middleware.my_feature import MyFeatureMiddleware

__all__ = [..., "MyFeatureMiddleware"]
```

4. **Test it:**
```python
# libs/deepagents/tests/unit_tests/test_my_feature.py
def test_my_feature_middleware():
    middleware = MyFeatureMiddleware(param="value")
    # Test hooks...
```

### Adding New Backend

1. **Implement BackendProtocol:**
```python
# libs/deepagents/backends/my_backend.py
from deepagents.backends.protocol import BackendProtocol, FileInfo, WriteResult, EditResult, GrepMatch

class MyBackend:
    def ls_info(self, path: str) -> list[FileInfo]:
        # Implementation

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        # Implementation

    # ... implement all protocol methods
```

2. **Export and test:** Same pattern as middleware

### Testing with Mock LLM

```python
from langchain.chat_models import FakeChatModel
from deepagents import create_deep_agent

# Mock model that returns predefined responses
model = FakeChatModel(
    responses=["I'll use the write_todos tool first...", "Here's my response..."]
)

agent = create_deep_agent(model=model, tools=[my_tool])

# Now test without making real API calls
result = agent.invoke({"messages": [{"role": "user", "content": "test"}]})
```

### Using Individual Middleware

You don't need `create_deep_agent()` if you only want specific capabilities:

```python
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from deepagents.middleware import FilesystemMiddleware

# Just planning and file system, no subagents
agent = create_agent(
    model="claude-sonnet-4-5-20250929",
    middleware=[
        TodoListMiddleware(),
        FilesystemMiddleware(backend=my_backend),
    ]
)
```

## Key Implementation Details

### Default Model

**Location:** `graph.py:29`

```python
def get_default_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
    )
```

Sonnet 4.5 (20250929) is the default because:
- Extended context window
- Strong reasoning for complex tasks
- Good balance of speed and capability

### System Prompt Composition

The final system prompt is assembled from:
1. User's `system_prompt` parameter (if provided)
2. `BASE_AGENT_PROMPT` constant (standard instructions)
3. Middleware-added prompts (each middleware can inject instructions)

### Recursion Limit

**Critical:** The graph has recursion limit set to 1000 (see `graph.py:146`):
```python
return create_agent(...).with_config({"recursion_limit": 1000})
```

This allows deep task decomposition and many subagent spawns.

### Tool Runtime

Middleware has access to `ToolRuntime` which provides:
- Current state
- Configuration
- Checkpointer
- Store

Access via: `config["configurable"]["tools_runtime"]`

## Testing Patterns

### Unit Test Structure

```python
# libs/deepagents/tests/unit_tests/test_feature.py
import pytest
from deepagents.middleware.feature import FeatureMiddleware

def test_feature_initialization():
    """Test middleware can be created"""
    middleware = FeatureMiddleware(param="value")
    assert middleware.param == "value"

def test_feature_hook():
    """Test specific hook behavior"""
    middleware = FeatureMiddleware(param="value")
    messages = [...]
    result = list(middleware.after_model(messages, {}, {}))
    assert len(result) == len(messages)
```

### Integration Test Structure

```python
# libs/deepagents/tests/integration_tests/test_agent.py
import pytest
import os
from deepagents import create_deep_agent

@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="No API key")
def test_full_agent_execution():
    """Test agent can execute a real task"""
    agent = create_deep_agent(tools=[my_tool])

    result = agent.invoke({
        "messages": [{"role": "user", "content": "Create a file called test.txt"}]
    })

    # Verify agent completed task
    assert "test.txt" in str(result)
```

### Running Tests Selectively

```bash
# Only tests matching pattern
uv run pytest libs/deepagents/tests -k "test_filesystem"

# Stop at first failure
uv run pytest libs/deepagents/tests -x

# Show print statements
uv run pytest libs/deepagents/tests -s

# Parallel execution (fast)
uv run pytest libs/deepagents/tests -n auto
```

## Code Style & Conventions

### Ruff Configuration

**Location:** `pyproject.toml:56-96`

- Line length: 150 characters
- Select: ALL rules enabled by default
- Convention: Google-style docstrings
- Ignored rules: COM812, ISC001 (formatter conflicts), and several project-specific ignores

### Type Checking with MyPy

- Strict mode enabled
- Missing imports ignored (for flexibility with optional dependencies)
- `disallow_any_generics = false` for ergonomics with LangChain types

### Docstring Format

Use Google style:

```python
def my_function(param: str) -> str:
    """One-line summary of function.

    Longer description if needed. Explain what this does and why.

    Args:
        param: Description of parameter.

    Returns:
        Description of return value.

    Raises:
        ValueError: When param is invalid.

    Example:
        >>> my_function("test")
        'result'
    """
```

## Relationship with deepagents-cli

The CLI (`libs/deepagents-cli/`) is a consumer of this core library:

```python
# CLI imports and uses create_deep_agent
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=model,
    tools=tools,
    middleware=[...],  # CLI adds its own middleware
    backend=CompositeBackend(...),
    checkpointer=checkpointer,
    store=store,
)
```

**Testing interdependency:** Changes to core library should not break CLI. Always run CLI tests after core library changes:
```bash
# After core library changes
make test  # Core library tests
cd libs/deepagents-cli && uv run pytest tests/  # CLI tests
```

## Common Pitfalls

### 1. Middleware Order Matters

❌ **Wrong:**
```python
middleware = [
    HumanInTheLoopMiddleware(...),  # This runs last in after_model
    MyLoggingMiddleware(),          # This runs first in after_model
]
```

If logging needs to see HITL decisions, the order is reversed because `after_model()` runs in reverse.

### 2. Backend Factory vs Instance

```python
# ✅ Direct instance - works when backend doesn't need runtime context
backend = FilesystemBackend(root_dir="/path")

# ✅ Factory - use when backend needs ToolRuntime
backend = lambda rt: StateBackend(rt)

# ❌ Wrong - StateBackend needs runtime, but passed as instance
backend = StateBackend(None)  # Will fail at runtime
```

### 3. Forgetting to Yield in after_model()

```python
# ❌ Wrong - breaks message flow
def after_model(self, messages, agent_input, config, **kwargs):
    modified = [msg + " [seen]" for msg in messages]
    return modified  # Don't return!

# ✅ Correct
def after_model(self, messages, agent_input, config, **kwargs):
    for msg in messages:
        yield msg  # or: yield from messages
```

### 4. Absolute vs Relative Imports in graph.py

When the graph is exported for LangGraph server, relative imports break:

```python
# ❌ Wrong in graph.py (or any file exported to server)
from .middleware import MyMiddleware

# ✅ Correct
from deepagents.middleware import MyMiddleware
```

## Version History

**0.2.5** (Current)
- Handoff middleware pattern
- Enhanced backend system
- Improved prompt caching

**0.2.4**
- Added resumable shell middleware
- StoreBackend implementation

**0.2.0**
- Initial public release
- Core middleware: TodoList, Filesystem, Subagents
- Backend abstraction layer

## Key Principles

1. **Composability** - Each middleware can be used independently
2. **Backend abstraction** - File operations work with any storage backend
3. **Middleware-first** - Functionality is added through middleware, not hardcoded
4. **Protocol-based** - Interfaces define contracts, not inheritance
5. **LangGraph native** - Returns compiled StateGraph, fully compatible with LangGraph ecosystem
