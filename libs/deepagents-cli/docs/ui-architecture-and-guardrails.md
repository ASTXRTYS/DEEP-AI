# UI Architecture & Development Guardrails

**Created**: 2025-01-11
**Purpose**: Comprehensive guide for safely modifying the DeepAgents CLI UI
**Context**: Thread management implementation (Deep-AI-CLI branch)

---

## Executive Summary

This document provides a complete map of the CLI's UI architecture and establishes guardrails for safe modifications. The DeepAgents CLI uses:
- **Rich** for terminal rendering
- **prompt_toolkit** for input handling
- **LangGraph streaming** for real-time agent execution
- **Dual-mode streaming** for HITL (Human-in-the-Loop) approvals

### Critical Finding: `/clear` Command is BROKEN
The current `/clear` implementation (commands.py:21) **destroys persistence** by replacing the SQLite checkpointer with `InMemorySaver()`. This is a bug that must be fixed as part of thread management.

---

## Table of Contents

1. [UI Architecture Overview](#ui-architecture-overview)
2. [State Management](#state-management)
3. [Rendering System](#rendering-system)
4. [Input System](#input-system)
5. [Execution Flow](#execution-flow)
6. [Command System](#command-system)
7. [Best Practices from Research](#best-practices-from-research)
8. [Guardrails: Do's and Don'ts](#guardrails-dos-and-donts)
9. [Thread Management UI Requirements](#thread-management-ui-requirements)
10. [Implementation Safety Checklist](#implementation-safety-checklist)

---

## UI Architecture Overview

### File Structure

```
deepagents_cli/
├── ui.py              # Rendering functions, TokenTracker, formatters
├── config.py          # Configuration, colors, SessionState, Console singleton
├── input.py           # prompt_toolkit session, completers, key bindings
├── execution.py       # Streaming execution, tool rendering, HITL
├── commands.py        # Slash command handlers (/clear, /help, etc.)
├── main.py            # CLI loop, initialization
└── file_ops.py        # File operation tracking and diff generation
```

### Key Components

#### 1. **Console Singleton** (config.py:76)
```python
console = Console(highlight=False)
```
- **Used by**: Every module for output
- **Pattern**: Singleton - import and use directly
- **Do not**: Create new Console instances
- **Why**: Maintains consistent styling and state

#### 2. **Color Scheme** (config.py:13-20)
```python
COLORS = {
    "primary": "#10b981",    # Green - agent responses, headings
    "dim": "#6b7280",        # Gray - metadata, secondary info
    "user": "#ffffff",       # White - user input
    "agent": "#10b981",      # Green - agent responses
    "thinking": "#34d399",   # Light green - status spinner
    "tool": "#fbbf24",       # Amber - tool calls
}
```
- **Consistency is critical** - don't introduce new colors without plan
- These colors are used throughout all UI elements

#### 3. **Rich Components Used**
- `Panel` - Grouping related content (HITL prompts, summaries)
- `Syntax` - Code highlighting (diffs)
- `Markdown` - Agent responses
- `Text` - Styled text segments
- `Status` - Animated spinner ("Agent is thinking...")
- `box.ROUNDED` - Border style

---

## State Management

### Current State Containers

#### 1. **TokenTracker** (ui.py:164-226)
**Purpose**: Track token usage across conversation

```python
class TokenTracker:
    def __init__(self):
        self.baseline_context = 0  # System + agent.md + tools
        self.current_context = 0   # Total context including messages
        self.last_output = 0       # Last response output tokens
```

**Methods**:
- `set_baseline(tokens)` - Initialize baseline
- `reset()` - Reset to baseline (used by /clear)
- `add(input_tokens, output_tokens)` - Update after response
- `display_last()` - Show last turn usage
- `display_session()` - Show full session usage

**Used by**: main.py:134, execution.py:216-642

**⚠️ Guardrail**: Don't modify internals without checking all usage sites

#### 2. **SessionState** (config.py:79-88)
**Purpose**: Hold mutable session state (auto-approve mode)

```python
class SessionState:
    def __init__(self, auto_approve: bool = False):
        self.auto_approve = auto_approve

    def toggle_auto_approve(self) -> bool:
        self.auto_approve = not self.auto_approve
        return self.auto_approve
```

**Used by**:
- execution.py:326 - Check if auto-approve enabled
- input.py:179 - Ctrl+T key binding toggle
- input.py:157 - Bottom toolbar display

**✅ Safe to extend**: Add thread_id tracking here

#### 3. **FileOpTracker** (file_ops.py)
**Purpose**: Track file operations for enhanced rendering

**Used by**: execution.py:237
**Scope**: Per-execution, not session-wide

---

## Rendering System

### Core Rendering Functions (ui.py)

#### 1. `format_tool_display(tool_name: str, tool_args: dict) -> str`
**Lines**: 23-143
**Purpose**: Smart formatting for different tool types
**Examples**:
- `read_file(config.py)` - Shows basename
- `web_search("query")` - Shows query
- `shell("command")` - Shows command

**Tool-specific logic**:
- File operations: Show abbreviated path
- Web search: Show query (truncated to 100 chars)
- Shell: Show command (truncated to 120 chars)
- Grep: Show pattern
- Task: Show description
- Todos: Show count

**⚠️ Don't modify** without understanding all tool types

#### 2. `render_todo_list(todos: list[dict]) -> None`
**Lines**: 228-257
**Purpose**: Render todo panel with checkboxes
**States**:
- ☑ Green - completed
- ⏳ Yellow - in_progress
- ☐ Dim - pending

**✅ Safe to use** for thread list inspiration

#### 3. `render_summary_panel(summary_content: str) -> None`
**Lines**: 260-280
**Purpose**: Show context summarization panel
**Pattern**: Yellow panel with warning icon

**✅ Use similar pattern** for thread switches

#### 4. `render_file_operation(record: FileOperationRecord) -> None`
**Lines**: 295-344
**Purpose**: Show file ops with detailed metrics
**Output**: Tool icon, file path, metrics, optional diff

**⚠️ Don't modify** - working correctly

#### 5. `render_diff_block(diff: str, title: str) -> None`
**Lines**: 353-359
**Purpose**: Render diff in syntax-highlighted panel

**✅ Safe to reuse** for other code display

---

## Input System

### prompt_toolkit Session (input.py:166-249)

#### Key Bindings

```python
kb = KeyBindings()

@kb.add("c-t")          # Ctrl+T: Toggle auto-approve
@kb.add("enter")        # Enter: Submit (or apply completion)
@kb.add("escape", "enter")  # Alt+Enter: Insert newline
@kb.add("c-e")          # Ctrl+E: Open external editor
```

**⚠️ Don't break** existing key bindings
**✅ Safe to add** new bindings (e.g., Ctrl+N for new thread?)

#### Completers

1. **CommandCompleter** (lines 72-96)
   - Triggers on `/` prefix
   - Completes from COMMANDS dict
   - Case-insensitive

2. **BashCompleter** (lines 99-123)
   - Triggers on `!` prefix
   - Completes common bash commands

3. **FilePathCompleter** (lines 23-69)
   - Triggers on `@` prefix
   - Case-insensitive path matching

**✅ Pattern established** - add ThreadCompleter if needed

#### Bottom Toolbar (lines 153-163)

```python
def get_bottom_toolbar(session_state: SessionState):
    def toolbar():
        if session_state.auto_approve:
            return [("class:toolbar-green", "auto-accept ON (CTRL+T to toggle)")]
        return [("class:toolbar-orange", "manual accept (CTRL+T to toggle)")]
    return toolbar
```

**✅ Extend this** to show current thread:
```python
"auto-accept ON | Thread: main:a1b2c3d4 (CTRL+T to toggle)"
```

---

## Execution Flow

### Critical Code: Thread ID Configuration (execution.py:209-212)

```python
config = {
    "configurable": {"thread_id": assistant_id or "main"},
    "metadata": {"assistant_id": assistant_id} if assistant_id else {},
}
```

**Line 210 is THE PROBLEM**: Static `thread_id = assistant_id`

**Thread management fix**:
```python
# Get current thread from ThreadManager
current_thread = thread_manager.get_current_thread_id()

config = {
    "configurable": {"thread_id": current_thread or assistant_id or "main"},
    "metadata": {"assistant_id": assistant_id, "thread_id": current_thread} if assistant_id else {},
}
```

### Streaming Architecture (execution.py:286-608)

**Dual-mode streaming** (line 294):
```python
for chunk in agent.stream(
    stream_input,
    stream_mode=["messages", "updates"],  # Both modes!
    subgraphs=True,
    config=config,
    durability="exit",
):
```

**Why dual-mode?**
1. **"updates" stream** - HITL interrupts, todo updates, graph state changes
2. **"messages" stream** - AI responses, tool calls, tool results

**Chunk format** (line 303):
```python
namespace, current_stream_mode, data = chunk
```

**⚠️ CRITICAL**: Don't break this streaming logic
**⚠️ CRITICAL**: Don't modify interrupt handling (lines 311-366)
**⚠️ CRITICAL**: Don't change tool call buffering (lines 491-574)

### State Machines in Execution

1. **Spinner management** (`spinner_active` flag)
   - Start: Line 220
   - Stop before: Tool display, text output, interrupts
   - Restart: After interrupts resume

2. **Text buffering** (`pending_text`, lines 244-262)
   - Accumulate text chunks
   - Flush on tool calls or final chunk
   - Render as Markdown

3. **Summary detection** (`summary_mode`, lines 246-281)
   - Detect summarization messages
   - Render in special panel
   - Separate from normal responses

4. **Tool call buffering** (`tool_call_buffers`, lines 242-574)
   - Accumulate streaming tool call chunks
   - Parse when complete
   - Display once with icon

**⚠️ Don't modify** these state machines without deep understanding

---

## Command System

### Current Commands (commands.py:12-48)

#### 1. `/quit`, `/exit`, `/q` - Exit CLI
**Lines**: 16-17
**Status**: ✅ Working correctly

#### 2. `/clear` - **BROKEN!**
**Lines**: 19-34
**Current code**:
```python
if cmd == "clear":
    # Reset agent conversation state
    agent.checkpointer = InMemorySaver()  # ❌ DESTROYS PERSISTENCE!

    # Reset token tracking to baseline
    token_tracker.reset()

    # Clear screen and show fresh UI
    console.clear()
    console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
    console.print()
    console.print(
        "... Fresh start! Screen cleared and conversation reset.", style=COLORS["agent"]
    )
    console.print()
    return True
```

**Why it's broken**:
- Replaces SqliteSaver with InMemorySaver
- **Destroys the persistent checkpointer**
- Agent forgets everything after /clear
- No way to recover - persistence is gone!

**Correct implementation** (using thread management):
```python
if cmd == "clear":
    # Create new thread instead of destroying checkpointer
    new_thread_id = thread_manager.create_thread()
    thread_manager.switch_thread(new_thread_id)

    # Reset token tracking
    token_tracker.reset()

    # Clear screen and show fresh UI
    console.clear()
    console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
    console.print()
    console.print(
        f"✨ Started fresh thread: {new_thread_id}", style=COLORS["agent"]
    )
    console.print()
    return True
```

#### 3. `/help` - Show interactive help
**Lines**: 36-38
**Status**: ✅ Working correctly

#### 4. `/tokens` - Show token usage
**Lines**: 40-42
**Status**: ✅ Working correctly

### COMMANDS Dict (config.py:40-46)

```python
COMMANDS = {
    "clear": "Clear screen and reset conversation",
    "help": "Show help information",
    "tokens": "Show token usage for current session",
    "quit": "Exit the CLI",
    "exit": "Exit the CLI",
}
```

**✅ Add thread commands here**:
```python
"new": "Create a new thread",
"threads": "List all threads",
"threads continue <id>": "Switch to a different thread",
"threads fork": "Fork the current thread",
```

---

## Best Practices from Research

### From Rich Library Documentation

1. **Context Managers for Live Updates**
   ```python
   with console.status("[bold green]Working..."):
       # Do work
   ```
   ✅ Already using: execution.py:219

2. **Tables for Structured Data**
   ```python
   from rich.table import Table
   table = Table(title="Threads")
   table.add_column("ID", style="cyan")
   table.add_column("Created", style="dim")
   ```
   ✅ **Use for thread list!**

3. **Panels for Important Messages**
   ```python
   Panel("Message", title="Title", border_style="green")
   ```
   ✅ Already using: execution.py:78, ui.py:250

4. **Consistent Styling**
   - Define color scheme once
   - Use throughout application
   ✅ Already doing: config.py COLORS

### From CLI Design Patterns

1. **Clear Visual Hierarchy**
   - Primary actions: Bold, colored
   - Secondary info: Dim
   - Errors: Red
   ✅ Already following

2. **Responsive Feedback**
   - Show spinners for long operations
   - Immediate feedback for commands
   ✅ Already doing

3. **Intuitive Commands**
   - Short, memorable names
   - Clear descriptions
   - Auto-complete support
   ✅ Pattern established

---

## Guardrails: Do's and Don'ts

### 🚫 CRITICAL - DO NOT

1. **Console & Rendering**
   - ❌ Create new Console instances (breaks singleton pattern)
   - ❌ Modify TokenTracker internals without checking all usage sites
   - ❌ Change COLORS dict without comprehensive review
   - ❌ Break format_tool_display() tool-specific logic

2. **Execution Flow**
   - ❌ Modify dual-mode streaming architecture (execution.py:292-608)
   - ❌ Break HITL interrupt handling (execution.py:311-366)
   - ❌ Change tool call buffering logic (execution.py:491-574)
   - ❌ Modify summary detection (execution.py:264-281)
   - ❌ Break spinner state machine

3. **Input System**
   - ❌ Remove or break existing key bindings (Ctrl+T, Alt+Enter, Ctrl+E)
   - ❌ Modify completer logic without understanding trigger patterns
   - ❌ Break file mention parsing (@file syntax)

4. **State Management**
   - ❌ Mutate global state unexpectedly
   - ❌ Break SessionState.auto_approve flag
   - ❌ Modify agent.checkpointer directly (this is what /clear bug does!)

### ✅ SAFE TO DO

1. **UI Extensions**
   - ✅ Add new render functions to ui.py (follow existing patterns)
   - ✅ Add new panels for thread switching
   - ✅ Extend bottom toolbar with thread info
   - ✅ Add new tool icons to tool_icons dict (execution.py:223-235)
   - ✅ Create new formatters following format_tool_display pattern

2. **Command System**
   - ✅ Add new commands to commands.py
   - ✅ Add command descriptions to COMMANDS dict
   - ✅ Add new completers to input.py (follow existing patterns)
   - ✅ Add new key bindings (don't conflict with existing)

3. **State Management**
   - ✅ Extend SessionState with thread_id field
   - ✅ Create ThreadManager as separate module
   - ✅ Pass thread_manager to execution.py
   - ✅ Modify execution.py:210 to use thread_manager.get_current_thread_id()

4. **New Modules**
   - ✅ Create thread_manager.py (new file)
   - ✅ Create thread UI helpers in ui.py
   - ✅ Add thread commands to commands.py

### 🔧 MUST FIX

1. **Broken /clear Command** (commands.py:19-34)
   - Current: Destroys persistence with InMemorySaver
   - Fix: Use thread switching instead
   - Priority: HIGH - this is a bug

2. **Static Thread ID** (execution.py:210)
   - Current: `thread_id = assistant_id` (static)
   - Fix: Use ThreadManager to get dynamic thread_id
   - Priority: HIGH - main feature

---

## Thread Management UI Requirements

### 1. New Commands to Add

#### `/new` - Create new thread
```python
if cmd == "new":
    thread_id = thread_manager.create_thread()
    console.print(f"✨ Created new thread: {thread_id}", style=COLORS["primary"])
    return True
```

#### `/threads` - List all threads (with current indicator)
```python
if cmd == "threads":
    if len(cmd_parts) == 1:
        # Display threads as table
        from rich.table import Table
        table = Table(title="Available Threads", border_style=COLORS["primary"])
        table.add_column("ID", style="cyan")
        table.add_column("Created", style="dim")
        table.add_column("Last Used", style="dim")
        table.add_column("Messages", justify="right", style="dim")

        threads = thread_manager.list_threads()
        current_id = thread_manager.current_thread_id

        for thread in threads:
            marker = "→ " if thread["id"] == current_id else "  "
            table.add_row(
                f"{marker}{thread['id']}",
                thread["created"],
                thread["last_used"],
                str(thread["message_count"])
            )

        console.print()
        console.print(table)
        console.print()
        return True
```

#### `/threads continue <id>` - Switch thread
```python
if len(cmd_parts) >= 3 and cmd_parts[1] == "continue":
    thread_id = cmd_parts[2]
    try:
        thread_manager.switch_thread(thread_id)
        console.print()
        console.print(
            Panel(
                f"Switched to thread: {thread_id}\n\n"
                f"Previous messages in this thread are now in context.",
                title="[bold green]Thread Switched[/bold green]",
                border_style="green",
            )
        )
        console.print()
        return True
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        return True
```

#### `/threads fork` - Fork current thread
```python
if len(cmd_parts) >= 2 and cmd_parts[1] == "fork":
    parent_id = thread_manager.current_thread_id
    new_id = thread_manager.fork_thread(parent_id)
    console.print()
    console.print(
        Panel(
            f"Forked thread {parent_id} → {new_id}\n\n"
            f"New thread inherits all messages up to this point.",
            title="[bold cyan]Thread Forked[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()
    return True
```

### 2. Bottom Toolbar Extension

**Current** (input.py:157-162):
```python
if session_state.auto_approve:
    return [("class:toolbar-green", "auto-accept ON (CTRL+T to toggle)")]
return [("class:toolbar-orange", "manual accept (CTRL+T to toggle)")]
```

**Enhanced** (add thread info):
```python
def toolbar():
    parts = []

    # Thread info
    if hasattr(session_state, 'current_thread_id'):
        thread_id = session_state.current_thread_id
        # Truncate for display if needed
        if len(thread_id) > 20:
            display_id = thread_id[:20] + "..."
        else:
            display_id = thread_id
        parts.append(("class:toolbar-thread", f" Thread: {display_id} "))

    # Auto-approve status
    if session_state.auto_approve:
        parts.append(("class:toolbar-green", " auto-accept ON (CTRL+T) "))
    else:
        parts.append(("class:toolbar-orange", " manual accept (CTRL+T) "))

    return parts
```

### 3. Thread Indicator in Main Loop

**Option A**: Show in startup banner
```python
console.print("... Ready to code! What would you like to build?", style=COLORS["agent"])
console.print(f"  [dim]Working directory: {Path.cwd()}[/dim]")
console.print(f"  [dim]Thread: {thread_manager.current_thread_id}[/dim]")
console.print()
```

**Option B**: Show in prompt (not recommended - clutters input)
```python
message=HTML(f'<style fg="{COLORS["user"]}">[{thread_id}]></style> ')
```

**Recommendation**: Use Option A (startup banner) + bottom toolbar

---

## Implementation Safety Checklist

### Phase 1: ThreadManager Infrastructure

- [ ] Create `thread_manager.py` with ThreadManager class
- [ ] Add `threads.json` metadata storage
- [ ] Implement `create_thread()` method
- [ ] Implement `switch_thread()` method
- [ ] Implement `list_threads()` method
- [ ] Implement `fork_thread()` method
- [ ] Add unit tests for ThreadManager
- [ ] Verify no existing code breaks

### Phase 2: Command Integration

- [ ] Add thread commands to COMMANDS dict (config.py)
- [ ] Implement `/new` command (commands.py)
- [ ] Implement `/threads` command with table display
- [ ] Implement `/threads continue <id>` command
- [ ] Implement `/threads fork` command
- [ ] Fix `/clear` command to use thread switching
- [ ] Test all commands in isolation

### Phase 3: Execution Integration

- [ ] Pass thread_manager to execute_task() (main.py → execution.py)
- [ ] Modify execution.py:210 to use thread_manager.get_current_thread_id()
- [ ] Add SessionState.current_thread_id field
- [ ] Update SessionState after thread switches
- [ ] Test thread switching during execution
- [ ] Verify checkpointer works across threads

### Phase 4: UI Polish

- [ ] Add thread info to bottom toolbar (input.py)
- [ ] Add thread ID to startup banner (main.py)
- [ ] Create thread switch confirmation panel
- [ ] Add thread count to /threads list
- [ ] Add timestamps to thread metadata
- [ ] Test UI elements render correctly
- [ ] Verify colors and styling consistent

### Testing Checklist

- [ ] Start CLI, verify default thread created
- [ ] Create new thread with `/new`
- [ ] List threads with `/threads`
- [ ] Switch between threads with `/threads continue`
- [ ] Verify messages persist in each thread
- [ ] Fork thread and verify inheritance
- [ ] Use `/clear` and verify new thread created (not crash)
- [ ] Toggle auto-approve while in different threads
- [ ] Verify bottom toolbar shows correct info
- [ ] Test with long thread IDs (truncation)
- [ ] Verify /memories/ files accessible across all threads
- [ ] Test keyboard interrupts during thread operations
- [ ] Verify LangGraph server compatibility

---

## Amp CLI Reference

From research, Amp CLI (Sourcegraph) has these thread management commands:

- `/new` - Start a new conversation thread
- `/threads` - List all conversation threads
- `/threads continue <id>` - Switch to a specific thread
- `/threads fork` - Fork the current thread

**We're following this pattern exactly** - proven UX design.

---

## Summary: What to Build

### Minimal Viable Thread Management (MVP)

1. **ThreadManager class** (thread_manager.py)
   - Thread ID generation: `{assistant_id}:{uuid_short}`
   - Metadata storage: `~/.deepagents/{agent}/threads.json`
   - Methods: create, switch, list, fork

2. **Fix `/clear` command** (commands.py:19-34)
   - Replace InMemorySaver logic with thread creation
   - Don't destroy checkpointer!

3. **Add thread commands** (commands.py)
   - `/new` - Create new thread
   - `/threads` - List threads
   - `/threads continue <id>` - Switch thread

4. **Integrate with execution** (execution.py:210)
   - Get thread_id from ThreadManager
   - Pass to LangGraph config

5. **UI indicators**
   - Bottom toolbar: Show current thread
   - Thread list: Rich table with current marker

### Future Enhancements (Post-MVP)

- Thread naming/renaming
- Thread deletion/archiving
- Thread search by content
- Thread export
- Thread statistics (token usage per thread)

---

## Questions for User

Before implementing, confirm:

1. ✅ Fix `/clear` as part of Phase 1 or separate hotfix?
2. ✅ Bottom toolbar: Show full thread ID or truncated?
3. ✅ Default thread naming: `{assistant_id}:{uuid}` or custom?
4. ✅ Thread list: Table view or panel list?
5. ✅ Any other UI preferences?

---

**Document Status**: Complete - Ready for implementation
**Next Step**: Review with user, then begin Phase 1 (ThreadManager class)

