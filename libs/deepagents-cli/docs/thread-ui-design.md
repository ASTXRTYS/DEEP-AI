# Thread Management UI/UX Design

**Created**: 2025-01-11
**Purpose**: Comprehensive CLI user experience design for thread management
**Philosophy**: Treat CLI as front-end design - make it intuitive, powerful, and delightful

---

## Design Principles

### 1. Progressive Disclosure
- Simple commands for common cases
- Advanced features available but not overwhelming
- `/threads` → clean list, `/threads help` → all options

### 2. Smart Defaults
- Most recent thread shown first
- Safe defaults (confirmations for destructive actions)
- Intelligent truncation (UUIDs → first 8 chars)

### 3. Visual Clarity
- Consistent use of Rich library components
- Color coding: Green (current), Dim (others), Yellow (warnings), Red (errors)
- Clear visual hierarchy (tables, panels, markers)

### 4. Discoverability
- Commands suggest next steps
- Error messages include corrections
- Help text is contextual

---

## Command Structure

### Command Hierarchy (Amp-style)

```
/new                          # Create new thread (instant)
/threads                      # List all threads (default view)
/threads continue <id>        # Switch to thread (partial UUID matching)
/threads fork [name]          # Fork current thread
/threads rename <id> <name>   # Rename thread
/threads delete <id>          # Delete thread (with confirmation)
/threads info [id]            # Show detailed thread info
/threads history [id]         # Show checkpoints in thread (TIME TRAVEL!)
```

### Why This Structure?

**Follows LangGraph/CLI best practices**:
- `/new` - One-word for most common action (git-style)
- `/threads` - Namespace for thread operations
- Subcommands are verbs (`continue`, `fork`, `rename`)
- Optional params in brackets, required in angle brackets

---

## UI Components

### 1. Thread List (`/threads`)

**Display Format**: Rich Table

```
╭─────────────────────────── Available Threads ───────────────────────────╮
│ ID         │ Name                    │ Created    │ Last Used  │ Messages │
├────────────┼─────────────────────────┼────────────┼────────────┼──────────┤
│ → 550e8400 │ Default conversation    │ 2h ago     │ Just now   │ 42       │
│   9b2d5f7e │ Web scraper project     │ 1d ago     │ 30m ago    │ 156      │
│   a3c4d5e6 │ Database design         │ 3d ago     │ 2h ago     │ 89       │
╰────────────┴─────────────────────────┴────────────┴────────────┴──────────╯

→ = current thread
Use: /threads continue <id> to switch
     /threads fork to branch from current
```

**Features**:
- ✅ Current thread marker (→)
- ✅ Truncated UUID (8 chars, expandable)
- ✅ Human-readable timestamps (relative: "2h ago")
- ✅ Message count (from checkpoint metadata)
- ✅ Sorted by last_used (most recent first)
- ✅ Footer with helpful hints

**Implementation**:
```python
from rich.table import Table
from datetime import datetime

def render_thread_list(threads, current_id):
    table = Table(title="Available Threads", border_style="cyan")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Created", style="dim")
    table.add_column("Last Used", style="dim")
    table.add_column("Messages", justify="right", style="dim")

    for thread in threads:
        marker = "→ " if thread["id"] == current_id else "  "
        id_short = thread["id"][:8]
        # Add rows with relative timestamps
        table.add_row(...)

    console.print(table)
```

---

### 2. Thread Switch (`/threads continue <id>`)

**UX Flow**:
1. User types `/threads continue 550e`
2. Partial UUID matching finds thread
3. Show confirmation panel
4. Switch thread, update state

**Display**:
```
╭───────────── Thread Switched ─────────────╮
│                                            │
│  Switched to: Default conversation        │
│  Thread ID:   550e8400-e29b-41d4...        │
│                                            │
│  📝 This thread has 42 messages            │
│  🕐 Last used: Just now                    │
│                                            │
│  Your conversation history is restored.   │
│                                            │
╰────────────────────────────────────────────╯
```

**Error Handling**:
```
❌ Thread '999xxx' not found

Did you mean one of these?
  • 9b2d5f7e (Web scraper project)
  • 550e8400 (Default conversation)

Use: /threads to see all threads
```

---

### 3. Thread Fork (`/threads fork [name]`)

**UX Flow**:
1. User types `/threads fork` or `/threads fork "experiment branch"`
2. Show forking panel (with agent requirement check)
3. Copy checkpoint state
4. Create new thread with metadata
5. Switch to new thread

**Display**:
```
╭──────────────── Forking Thread ────────────────╮
│                                                 │
│  🔱 Forked from: Default conversation          │
│                                                 │
│  Parent:    550e8400-e29b-41d4...              │
│  New:       a7b8c9d0-e1f2-3456...              │
│  Name:      Fork of Default conversation       │
│                                                 │
│  ✅ Copied 42 messages from parent             │
│  ✅ Switched to new forked thread              │
│                                                 │
│  Future messages will diverge from parent.     │
│                                                 │
╰─────────────────────────────────────────────────╯
```

**Why This Matters**:
- User knows exactly what happened
- Confirms state was copied
- Explains future behavior

---

### 4. Thread Info (`/threads info [id]`)

**Display Detailed Metadata**:

```
╭──────────────────────── Thread Details ────────────────────────╮
│                                                                 │
│  Thread ID:     550e8400-e29b-41d4-a716-446655440000           │
│  Name:          Default conversation                           │
│  Assistant:     agent                                          │
│                                                                 │
│  Created:       2025-01-10 18:30:00 UTC (2 hours ago)         │
│  Last Used:     2025-01-10 20:29:45 UTC (just now)            │
│                                                                 │
│  Parent:        None                                           │
│  Children:      2 forks                                        │
│                                                                 │
│  Messages:      42 exchanges                                   │
│  Checkpoints:   127 states saved                               │
│                                                                 │
│  First message: "Help me build a web scraper"                 │
│  Last message:  "That worked perfectly, thanks!"               │
│                                                                 │
╰─────────────────────────────────────────────────────────────────╯

Use /threads history to see all checkpoints
```

---

### 5. Thread History / Time Travel (`/threads history`)

**🚀 ADVANCED FEATURE** (Leveraging LangGraph's `get_state_history()`)

**Display Checkpoint Timeline**:

```
╭─────────────── Thread History: Default conversation ───────────────╮
│                                                                     │
│  Showing checkpoints for thread: 550e8400                          │
│                                                                     │
│  Checkpoint                     │ Step              │ Time         │
│  ───────────────────────────────┼───────────────────┼──────────────│
│  checkpoint_3a4b (current)      │ user message      │ just now     │
│  checkpoint_2f1e                │ tool: web_search  │ 2m ago       │
│  checkpoint_1d9c                │ agent response    │ 5m ago       │
│  checkpoint_0b7a                │ user message      │ 8m ago       │
│  ...                            │                   │              │
│                                                                     │
╰─────────────────────────────────────────────────────────────────────╯

Use /threads replay <checkpoint_id> to jump to a specific point
```

**Why This Matters**:
- User can see full conversation timeline
- Debug agent decision-making
- Fork from ANY point in history (not just current)

---

## UUID Handling Strategy

### Challenge
Pure UUIDs are 36 characters:
```
550e8400-e29b-41d4-a716-446655440000
```

### Solution: Progressive Disclosure

**In Lists**: Show first 8 chars
```
550e8400
```

**In Details**: Show full UUID
```
550e8400-e29b-41d4-a716-446655440000
```

**In Input**: Accept partial matching
```
User types:    /threads continue 550e
System finds:  550e8400-e29b-41d4-a716-446655440000
```

**Implementation**:
```python
def find_thread_by_partial_id(threads: list, partial_id: str) -> ThreadMetadata | None:
    """Find thread by partial UUID (case-insensitive, prefix match)."""
    partial_lower = partial_id.lower()

    # Try exact match first
    for thread in threads:
        if thread["id"] == partial_id:
            return thread

    # Try prefix match
    matches = [t for t in threads if t["id"].lower().startswith(partial_lower)]

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise ValueError(f"Ambiguous thread ID '{partial_id}'. Matches: {[m['id'][:8] for m in matches]}")
    else:
        return None
```

---

## Message Count Implementation

### Challenge
How do we get message count for each thread?

### Solution: Query Checkpointer

```python
def get_thread_message_count(agent, thread_id: str) -> int:
    """Get message count from checkpoint history."""
    config = {"configurable": {"thread_id": thread_id}}

    # Get latest state
    state = agent.get_state(config)

    # Count messages in state
    if state.values and "messages" in state.values:
        return len(state.values["messages"])

    return 0
```

**When to call this**:
- When rendering thread list (can be slow, consider caching)
- When showing thread info
- Async/lazy loading for large thread lists

---

## Relative Timestamps

### Human-Friendly Time Display

**Instead of**: `2025-01-10T20:30:00Z`
**Show**: `2h ago`, `just now`, `3d ago`

**Implementation**:
```python
from datetime import datetime, timezone

def relative_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to relative time."""
    dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    delta = now - dt

    seconds = delta.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}h ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days}d ago"
    else:
        weeks = int(seconds / 604800)
        return f"{weeks}w ago"
```

---

## Error Handling Patterns

### 1. Thread Not Found

```python
# Bad
raise ValueError(f"Thread {thread_id} not found")

# Good
available = [t["id"][:8] for t in threads[:3]]
console.print(f"\n[red]❌ Thread '{thread_id[:8]}' not found[/red]\n")
console.print("[dim]Available threads:[/dim]")
for tid in available:
    console.print(f"  • {tid}")
console.print(f"\nUse [cyan]/threads[/cyan] to see all threads")
```

### 2. Ambiguous Partial ID

```python
matches = ["550e8400", "550e9abc"]
console.print(f"\n[yellow]⚠️  Ambiguous thread ID '{partial_id}'[/yellow]\n")
console.print("Multiple threads match:")
for match in matches:
    thread = get_thread_metadata(match)
    console.print(f"  • {match} - {thread['name']}")
console.print("\nPlease provide more characters")
```

### 3. Fork Requires Agent

```python
console.print("[red]❌ Cannot fork thread:[/red] Agent not available")
console.print("\n[dim]Thread forking requires copying checkpoint state,[/dim]")
console.print("[dim]which needs agent access. Please try again.[/dim]")
```

---

## Bottom Toolbar Integration

### Current Toolbar
```python
if session_state.auto_approve:
    return [("class:toolbar-green", "auto-accept ON (CTRL+T)")]
return [("class:toolbar-orange", "manual accept (CTRL+T)")]
```

### Enhanced Toolbar (with thread info)

```python
def get_bottom_toolbar(session_state, thread_manager):
    parts = []

    # Thread info (left side)
    if hasattr(session_state, 'current_thread_id'):
        tid_short = session_state.current_thread_id[:8]
        thread = thread_manager.get_thread_metadata(session_state.current_thread_id)
        thread_name = thread.get('name', 'Unnamed')

        # Truncate name if too long
        if len(thread_name) > 25:
            thread_name = thread_name[:22] + "..."

        parts.append(("class:toolbar-thread", f" 💬 {thread_name} ({tid_short}) "))

    # Auto-approve status (right side)
    if session_state.auto_approve:
        parts.append(("class:toolbar-green", " ⚡ auto-approve ON (CTRL+T) "))
    else:
        parts.append(("class:toolbar-orange", " 🤚 manual approve (CTRL+T) "))

    return parts
```

**Styling**:
```python
toolbar_style = Style.from_dict({
    "bottom-toolbar": "noreverse",
    "toolbar-thread": "bg:#2F6868 #ffffff",  # Teal background
    "toolbar-green": "bg:#10b981 #000000",
    "toolbar-orange": "bg:#f59e0b #000000",
})
```

**Result**:
```
💬 Default conversation (550e8400) ⚡ auto-approve ON (CTRL+T)
```

---

## Confirmation Dialogs

### For Destructive Actions (`/threads delete`)

**Use Rich Panel with clear warning**:

```python
console.print()
console.print(
    Panel(
        f"[bold red]⚠️  Delete Thread?[/bold red]\n\n"
        f"Thread: {thread['name']}\n"
        f"ID: {thread_id[:8]}...\n"
        f"Messages: {message_count}\n\n"
        f"[yellow]This action cannot be undone.[/yellow]\n\n"
        f"Type 'delete' to confirm, or anything else to cancel:",
        border_style="red",
        padding=(1, 2),
    )
)

confirmation = input("> ").strip()
if confirmation.lower() == "delete":
    # Proceed with deletion
else:
    console.print("[dim]Deletion cancelled[/dim]")
```

---

## Future Enhancements (Post-MVP)

### 1. Thread Search
```
/threads search "web scraper"
```
- Search thread names, metadata
- Eventually: Search message content (requires checkpoint parsing)

### 2. Thread Tags
```
/threads tag <id> "project:acme,priority:high"
/threads filter tag:project:acme
```

### 3. Thread Export
```
/threads export <id> --format markdown
```
- Export conversation to file
- Useful for documentation, sharing

### 4. Auto-Naming
```python
# On thread creation, use first user message as name
first_message = "Help me build a web scraper"
auto_name = first_message[:50]  # "Help me build a web scraper"
```

### 5. Thread Statistics
```
/threads stats
```
- Total threads
- Total messages
- Most active thread
- Average thread length

---

## Implementation Priority

### Phase 2 (MVP) - Ship This First
1. ✅ `/new` - Create thread
2. ✅ `/threads` - List threads (Rich table)
3. ✅ `/threads continue <id>` - Switch (partial UUID matching)
4. ✅ `/threads fork [name]` - Fork thread
5. ✅ Fix `/clear` to use thread creation
6. ✅ Bottom toolbar with thread info

### Phase 3 (Polish)
1. `/threads info <id>` - Detailed view
2. `/threads rename <id> <name>` - Rename
3. `/threads delete <id>` - Delete (with confirmation)
4. Relative timestamps
5. Message counts

### Phase 4 (Advanced)
1. `/threads history` - Checkpoint timeline
2. `/threads replay <checkpoint>` - Time travel
3. Thread search
4. Auto-naming

---

## Testing Scenarios

### Scenario 1: New User
```
> deepagents
... Ready to code!
  Thread: Default conversation (550e8400)

> /threads
╭─────────────── Available Threads ───────────────╮
│ ID       │ Name                 │ Created      │
│ 550e8400 │ Default conversation │ just now     │
╰──────────────────────────────────────────────────╯
```

### Scenario 2: Multi-Thread Workflow
```
> /new
✨ Created new thread: 9b2d5f7e

> Help me build a web scraper
[conversation continues...]

> /threads
╭─────────────── Available Threads ───────────────╮
│ → 9b2d5f7e │ Unnamed thread       │ 5m ago      │
│   550e8400 │ Default conversation │ 10m ago     │
╰──────────────────────────────────────────────────╯

> /threads continue 550e
Switched to: Default conversation
```

### Scenario 3: Fork for Experimentation
```
> /threads fork "experiment with async"
🔱 Forked to: a7b8c9d0
✅ Copied 42 messages from parent

> [try experimental changes without affecting original]

> /threads continue 9b2d
Switched back to original thread
```

---

## Key Takeaways

1. **UUIDs**: Use full UUIDs internally, truncate for display, partial matching for UX
2. **Feedback**: Every action gets clear confirmation
3. **Discoverability**: Commands suggest next steps, errors are helpful
4. **Visual Hierarchy**: Consistent use of Rich components (tables, panels)
5. **Progressive Disclosure**: Simple by default, powerful when needed
6. **LangGraph Native**: Leverage time-travel, checkpoints, state history

**This is enterprise-grade CLI UX**, following LangGraph patterns and modern CLI best practices.

