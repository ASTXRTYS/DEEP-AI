# Thread Management & UX Issues - Restoration Needed

**Branch:** `claude/restore-thread-management-01GV6w7i4D1ZSvFp4GhMBppp`
**Date:** 2025-11-14
**Context:** Features lost in merge PR #107 (commit 8dbea7d) from upstream/Resolve

## Executive Summary

The recent merge from upstream/Resolve into the repository has resulted in the loss of several thread management and UX features. The previous implementation (PR #34) used `questionary` for interactive menus, but this dependency has been **intentionally removed** from the project.

**Goal:** Restore the lost functionality using the existing tech stack (`rich` + `prompt-toolkit`) without adding `questionary` back.

## Architecture Decision: No Questionary

**Important:** The `questionary` dependency was intentionally excluded from this project. All interactive menu functionality must be implemented using:
- ✅ `rich` - Already in dependencies, used for console output
- ✅ `prompt-toolkit` - Already in dependencies, used for input handling
- ❌ `questionary` - **NOT to be used**

## Critical Issues Found

### 1. Menu System Code Incompatible with Current Stack

**Status:** 🔴 BROKEN
**Severity:** HIGH
**Location:** `libs/deepagents-cli/deepagents_cli/menu_system/`

#### Problem
The menu system code (from PR #34) imports and uses `questionary`, which is not in our dependencies and **should not be added**.

**Files with questionary imports:**
- `menu_system/core.py:9` - `import questionary`
- `handoff_ui.py` - uses `questionary` for handoff approval

#### Impact
- Pressing `Ctrl+M` triggers import error
- `/menu` command crashes
- Menu system completely non-functional

#### Fix Required
**Rewrite the menu system** to use `prompt-toolkit` directly instead of `questionary`. The prompt-toolkit library is already used successfully in `input.py` for:
- Key bindings (`Ctrl+M`, `Ctrl+T`, `Ctrl+C`)
- Command completion (`/` commands, `@` file mentions)
- Multi-line input with Enter to submit
- Bottom toolbar

**Implementation approach:**
- Use `prompt-toolkit.shortcuts.radiolist_dialog()` or `prompt-toolkit.shortcuts.checkboxlist_dialog()`
- OR build custom prompts using `PromptSession` with custom completers
- Follow the pattern in `input.py:create_prompt_session()`
- Style with `prompt-toolkit.styles.Style` (already used for toolbar)
- Render with `rich` for visual output

---

### 2. Interactive Thread Picker Removed

**Status:** 🟡 DEGRADED
**Severity:** MEDIUM
**Location:** `libs/deepagents-cli/deepagents_cli/commands.py`

#### Problem
The interactive thread picker with arrow key navigation was removed and replaced with a simple numbered list display.

#### What Was Lost
**Before (PR #34 - commit 63f2900):**
- ✅ Interactive arrow-key navigation
- ✅ Real-time search/filtering for 10+ threads
- ✅ Visual highlighting of current selection
- ✅ Current thread pre-selected by default
- ✅ Unified styling matching CLI theme
- ✅ Clear visual feedback during selection

**After (current state - commit 8dbea7d):**
- ❌ No interactive selection
- ❌ Manual typing of thread number or ID required
- ❌ No search/filtering capability
- ❌ Less discoverable for new users
- ✅ Still shows thread list with metrics

#### User Experience Impact
**Current workflow (tedious):**
1. Run `/threads` to see the list
2. Manually type `/threads switch <number>` to switch threads

**Desired workflow (interactive):**
1. Run `/threads` - interactive picker appears
2. Use arrow keys to navigate (↑↓)
3. Press Enter to switch
4. OR type to search/filter threads
5. ESC to cancel

#### Fix Required
**Implement interactive picker using `prompt-toolkit`**, not questionary:

```python
from prompt_toolkit.shortcuts import radiolist_dialog
from prompt_toolkit.styles import Style

async def _select_thread_interactive(threads, current_thread_id):
    """Interactive thread picker using prompt-toolkit."""

    # Build choices list
    values = []
    for thread in threads:
        summary = _format_thread_summary(thread, current_thread_id)
        is_current = (thread["id"] == current_thread_id)
        values.append((thread["id"], summary, is_current))

    # Custom style matching CLI theme
    style = Style.from_dict({
        'dialog': f'bg:{COLORS["primary"]}',
        'dialog.body': 'bg:#1a1a1a',
        'radio-checked': f'{COLORS["primary"]} bold',
        'radio-selected': f'bg:{COLORS["primary"]} #ffffff bold',
    })

    # Show dialog
    result = await radiolist_dialog(
        title="Select Thread",
        text="Use arrow keys to navigate, Enter to select:",
        values=values,
        style=style,
    ).run_async()

    return result
```

**Alternative approach:** Build a custom completer/prompt for inline thread selection (similar to command completion in `input.py`).

---

### 3. Thread Deletion Functionality Status

**Status:** 🟢 IMPLEMENTED
**Severity:** LOW
**Location:** `libs/deepagents-cli/deepagents_cli/commands.py:431-451`

#### Status Check
Thread deletion **IS** currently implemented and functional:

```python
# commands.py:431-451
if subcommand == "delete":
    flags = {flag for flag in operands if flag in {"--force", "-f"}}
    operands = [op for op in operands if op not in flags]
    target = require_target()
    if not target:
        return True
    if not flags:
        console.print(
            "[yellow]Add --force to confirm deletion (this removes checkpoints and metadata).[/yellow]"
        )
        console.print()
        return True
    try:
        thread_manager.delete_thread(target["id"], agent)
        console.print()
        console.print(f"[green]✓ Deleted thread: {target['id'][:8]}[/green]")
        console.print()
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        console.print()
    return True
```

**Usage:**
```bash
/threads delete <#|id> --force
```

**Note:** This was NOT lost in the merge - it works correctly! ✓

---

### 4. Remove Unwanted `/menu` Command

**Status:** 🔴 REMOVE THIS
**Severity:** MEDIUM
**Location:** `libs/deepagents-cli/deepagents_cli/config.py:44`

#### Problem
The `/menu` command is **not wanted** and should be completely removed. It creates confusion:
1. When users type `/` to see commands, "menu" appears - which is circular (menu within menu)
2. Users already have `Ctrl+M` for the main menu
3. The `/` autocomplete IS the command menu - having `/menu` in that list is redundant
4. This command serves no purpose and clutters the interface

**User preference: We do not care for the `/menu` command at all.**

#### Current State
```python
# config.py:43-53
COMMANDS = {
    "menu": "Open main menu (also: Ctrl+M)",  # ← NOT WANTED - REMOVE!
    "help": "Show help and available commands",
    "new": "Create a new thread (/new [name])",
    "threads": "Switch threads (interactive)",
    "handoff": "Summarize current thread and start a child",
    "tokens": "Show token usage statistics",
    "clear": "Clear screen",
    "quit": "Exit (also: /exit)",
    "exit": "Exit the CLI",
}
```

#### Fix Required
**DELETE** the `/menu` command entirely from COMMANDS dict:

```python
COMMANDS = {
    # "menu": "Open main menu (also: Ctrl+M)",  # DELETED - not wanted
    "help": "Show help and available commands",
    "new": "Create a new thread (/new [name])",
    "threads": "Switch threads (interactive)",
    "handoff": "Summarize current thread and start a child",
    "tokens": "Show token usage statistics",
    "clear": "Clear screen",
    "quit": "Exit (also: /exit)",
    "exit": "Exit the CLI",
}
```

**Note:** If `/menu` command handling exists elsewhere in the code (e.g., in `commands.py`), remove that too. Users have `Ctrl+M` - `/menu` is completely unnecessary.

---

### 5. Thread Management Subcommands Status

**Status:** 🟢 IMPLEMENTED (but reduced)
**Severity:** INFO
**Location:** `libs/deepagents-cli/deepagents_cli/commands.py:362-473`

#### Current Implementation
The following thread subcommands are currently implemented:
- ✅ `/threads list` - Show all threads (default)
- ✅ `/threads switch <#|id>` - Switch to thread
- ✅ `/threads rename <#|id> <name>` - Rename thread
- ✅ `/threads delete <#|id> --force` - Delete thread
- ✅ `/threads info <#|id>` - Show thread details

#### Previously Removed (commit 0511689)
These were removed as "unused" but may be wanted:
- ❌ `/threads fork [name]` - Fork current thread
- ❌ `/threads cleanup [--days N]` - Bulk cleanup old threads
- ❌ `/threads sync` - Reconcile metadata
- ❌ `/threads vacuum` - Reclaim space
- ❌ `/threads stats` - Database statistics

**Note:** The commit message for 0511689 stated these were "not exposed in the help menu" and "not essential". Discuss whether to restore.

---

### 6. Handoff UI Uses Questionary

**Status:** 🔴 POTENTIALLY BROKEN
**Severity:** MEDIUM
**Location:** `libs/deepagents-cli/deepagents_cli/handoff_ui.py`

#### Problem
The handoff approval UI (`prompt_handoff_decision()`) likely imports and uses `questionary` for interactive prompts.

#### Impact
The `/handoff` command may crash when trying to prompt for user approval/refinement.

#### Fix Required
Check `handoff_ui.py` and rewrite any questionary usage to use `prompt-toolkit` or `rich.prompt` instead.

**Example using rich.prompt:**
```python
from rich.prompt import Prompt, Confirm

# Instead of questionary
choice = Prompt.ask(
    "Choose action",
    choices=["accept", "refine", "decline"],
    default="accept"
)

# Or for yes/no
confirmed = Confirm.ask("Accept this handoff?", default=True)
```

---

## Related Files Present

The merge preserved several UI enhancement files from PR #34:
- ✅ `ui_components.py` (6,445 bytes) - TUI components using `rich`
- ✅ `ui_constants.py` (2,801 bytes) - Icons and constants

These files are ready to use and compatible with our `rich`-based approach.

---

## Recommended Actions

### Immediate (Required to unblock)

1. **Rewrite menu_system to use prompt-toolkit**
   - File: `libs/deepagents-cli/deepagents_cli/menu_system/core.py`
   - Action: Replace `questionary` imports with `prompt-toolkit.shortcuts` dialogs
   - Example: Use `radiolist_dialog()`, `button_dialog()`, etc.
   - Reference: `input.py` for prompt-toolkit patterns already in use

2. **DELETE unwanted `/menu` command**
   - File: `libs/deepagents-cli/deepagents_cli/config.py`
   - Action: Remove `"menu": "Open main menu (also: Ctrl+M)",` from COMMANDS dict entirely
   - Note: We do not want this command - it's confusing and serves no purpose
   - Impact: Cleaner UX, less confusion, `Ctrl+M` still available

3. **Check and fix handoff_ui.py**
   - File: `libs/deepagents-cli/deepagents_cli/handoff_ui.py`
   - Action: Replace any `questionary` usage with `rich.prompt` or `prompt-toolkit`
   - Test: Run `/handoff` command end-to-end

### Short-term (UX improvements)

4. **Implement interactive thread picker using prompt-toolkit**
   - File: `libs/deepagents-cli/deepagents_cli/commands.py`
   - Action: Create `_select_thread_interactive()` function using `radiolist_dialog()`
   - Features needed:
     - Arrow key navigation
     - Search/filter for 10+ threads
     - Current thread pre-selected
     - Styled to match CLI theme
   - Fallback: If dialog too complex, use inline completion (like @ and /)

5. **Test menu system thoroughly**
   - Action: Manual testing of `Ctrl+M` menu after rewrite
   - Files to test: All menu_system/* files
   - Verify: No questionary imports remain anywhere

### Optional (Nice-to-have)

6. **Consider restoring advanced thread subcommands**
   - Commands: fork, cleanup, sync, vacuum, stats
   - Source: Commit 0511689^ (before removal)
   - Discussion needed: Are these truly needed or just bloat?

---

## Implementation Guide: Replacing Questionary

### Current Dependencies (Available to Use)
```python
# Already in pyproject.toml - use these!
from rich import console, prompt, box, panel  # Console output & prompts
from prompt_toolkit import PromptSession        # Input handling
from prompt_toolkit.shortcuts import (          # Dialogs
    radiolist_dialog,
    checkboxlist_dialog,
    button_dialog,
    input_dialog,
    message_dialog,
)
from prompt_toolkit.styles import Style        # Styling
from prompt_toolkit.key_binding import KeyBindings  # Custom keys
```

### Questionary → Prompt-Toolkit Migration

#### For Simple Prompts (Yes/No, Single Choice)
**Questionary way (DON'T USE):**
```python
import questionary
answer = questionary.confirm("Continue?").ask()
choice = questionary.select("Pick:", choices=["A", "B"]).ask()
```

**Our way (USE THIS):**
```python
from rich.prompt import Confirm, Prompt
answer = Confirm.ask("Continue?")
choice = Prompt.ask("Pick", choices=["A", "B"])
```

#### For Interactive Lists (Arrow Keys)
**Questionary way (DON'T USE):**
```python
import questionary
result = questionary.select(
    "Select item:",
    choices=["Item 1", "Item 2"]
).ask()
```

**Our way (USE THIS):**
```python
from prompt_toolkit.shortcuts import radiolist_dialog
from prompt_toolkit.styles import Style

style = Style.from_dict({
    'dialog': 'bg:#10b981',
    'radio-selected': 'bg:#10b981 #ffffff bold',
})

result = await radiolist_dialog(
    title="Select Item",
    text="Use arrow keys:",
    values=[("item1", "Item 1"), ("item2", "Item 2")],
    style=style,
).run_async()
```

#### For Text Input
**Questionary way (DON'T USE):**
```python
import questionary
name = questionary.text("Enter name:").ask()
```

**Our way (USE THIS):**
```python
from rich.prompt import Prompt
name = Prompt.ask("Enter name")

# OR for async with prompt-toolkit
from prompt_toolkit.shortcuts import input_dialog
name = await input_dialog(
    title="Input",
    text="Enter name:",
).run_async()
```

### Menu System Rewrite Pattern

The menu_system needs to be refactored to:
1. Remove all `import questionary` statements
2. Replace `questionary.select()` with `radiolist_dialog()`
3. Replace `questionary.confirm()` with `Confirm.ask()` from rich
4. Use async/await with `.run_async()` for prompt-toolkit dialogs
5. Style using `prompt_toolkit.styles.Style` to match CLI theme

**Key files to rewrite:**
- `menu_system/core.py` - Main menu logic
- `menu_system/handlers.py` - Action handlers
- `menu_system/menus.py` - Menu definitions
- `handoff_ui.py` - Handoff approval prompts

---

## Testing Checklist

After implementing fixes:
- [ ] Verify NO `import questionary` anywhere in codebase
- [ ] Test `Ctrl+M` menu system (should open without errors)
- [ ] Test interactive thread picker (arrow keys work)
- [ ] Test `/threads` command variations (switch, delete, rename, info)
- [ ] Test thread deletion with `--force` flag
- [ ] Test `/handoff` command (approval prompts work)
- [ ] Verify `/menu` removed from autocomplete
- [ ] Check styling matches CLI theme (green primary color)
- [ ] Run full test suite: `make test`
- [ ] Run integration tests

---

## Git History References

- **PR #107** (commit 8dbea7d): Big merge that caused the issues
- **PR #34** (commit 63f2900): Added menu system (using questionary)
- **Commit bdb8f35**: Merge from upstream/Resolve
- **Commit 0511689**: Intentional removal of "unused" thread subcommands
- **Commit b33c111**: Refactor that cleaned up imports and CLI argument handling

---

## Additional Context

### Why Questionary Was Removed
The decision to exclude `questionary` is intentional. The project uses:
- `rich` for beautiful console output (already integrated)
- `prompt-toolkit` for interactive input (already integrated)

Adding `questionary` would be redundant since it's just a wrapper around `prompt-toolkit` with opinionated styling. We can achieve the same functionality with our existing dependencies.

### User Impact
Users currently experience:
- ❌ Broken `Ctrl+M` menu (import error)
- ❌ No interactive thread switching (manual typing required)
- ❌ Potentially broken `/handoff` prompts
- ❌ Unwanted `/menu` command cluttering the interface

### Priority Assessment
- **P0 (Blocking):** Rewrite menu_system to remove questionary - currently crashes
- **P1 (High):** DELETE unwanted `/menu` command - not wanted at all, confusing UX
- **P1 (High):** Fix handoff_ui if it uses questionary - broken workflow
- **P2 (Medium):** Implement interactive thread picker - significant UX regression
- **P3 (Low):** Consider restoring advanced thread commands - uncertain value

---

## Conclusion

The thread management features can be fully restored using our existing tech stack (`rich` + `prompt-toolkit`) without adding `questionary`. The menu system code needs to be rewritten to use prompt-toolkit's dialog functions directly.

**Good news:**
- ✅ Thread deletion is working
- ✅ All menu system code is present (just needs questionary removed)
- ✅ UI components ready to use (ui_components.py, ui_constants.py)
- ✅ `prompt-toolkit` already successfully used in input.py

**The fix is straightforward:** Replace questionary imports with prompt-toolkit equivalents using the patterns from `input.py` as a reference.
