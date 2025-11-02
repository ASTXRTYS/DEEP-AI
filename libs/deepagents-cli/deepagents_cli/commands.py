"""Command handlers for slash commands and bash execution."""

import subprocess
from datetime import datetime
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from .config import COLORS, DEEP_AGENTS_ASCII, console
from .ui import TokenTracker, show_interactive_help


def relative_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to relative time string.

    Args:
        iso_timestamp: ISO 8601 timestamp (e.g., "2025-01-11T20:30:00Z")

    Returns:
        Human-readable relative time (e.g., "2h ago", "just now")
    """
    try:
        # Parse ISO timestamp (with or without 'Z')
        ts_str = iso_timestamp.rstrip('Z')
        ts = datetime.fromisoformat(ts_str)
        now = datetime.utcnow()
        delta = now - ts

        seconds = delta.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            mins = int(seconds / 60)
            return f"{mins}m ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h ago"
        else:
            days = int(seconds / 86400)
            return f"{days}d ago"
    except Exception:
        return iso_timestamp


def find_thread_by_partial_id(thread_manager, partial_id: str):
    """Find thread by partial UUID match.

    Args:
        thread_manager: ThreadManager instance
        partial_id: Partial UUID to match (e.g., "550e")

    Returns:
        Tuple of (thread_metadata, matches_list) where matches_list contains all matches

    Raises:
        ValueError: If no matches or multiple ambiguous matches
    """
    threads = thread_manager.list_threads()
    matches = [t for t in threads if t['id'].startswith(partial_id)]

    if not matches:
        raise ValueError(f"No thread found matching '{partial_id}'")

    if len(matches) > 1:
        match_ids = [t['id'][:8] for t in matches]
        raise ValueError(
            f"Ambiguous thread ID '{partial_id}' - matches multiple threads: {', '.join(match_ids)}\n"
            f"Please provide more characters to uniquely identify the thread."
        )

    return matches[0], matches


def handle_thread_commands(args: str, thread_manager, agent) -> bool:
    """Handle /threads subcommands.

    Args:
        args: Arguments after '/threads' command
        thread_manager: ThreadManager instance
        agent: Agent instance (for fork operations)

    Returns:
        True if handled
    """
    args = args.strip()

    # /threads (no args) - List threads
    if not args:
        threads = thread_manager.list_threads()
        current_id = thread_manager.get_current_thread_id()

        if not threads:
            console.print()
            console.print("[yellow]No threads found.[/yellow]")
            console.print()
            return True

        # Create Rich table
        table = Table(
            title="Available Threads",
            show_header=True,
            header_style=f"bold {COLORS['primary']}",
            border_style=COLORS['dim']
        )

        table.add_column("", width=2)  # Current thread indicator
        table.add_column("ID", style=COLORS['primary'], width=10)
        table.add_column("Name", style="white")
        table.add_column("Created", style=COLORS['dim'], width=12)
        table.add_column("Last Used", style=COLORS['dim'], width=12)

        for thread in threads:
            is_current = thread['id'] == current_id
            indicator = "→" if is_current else ""
            thread_id_short = thread['id'][:8]
            name = thread.get('name') or "(unnamed)"
            created = relative_time(thread.get('created', ''))
            last_used = relative_time(thread.get('last_used', ''))

            # Highlight current thread row
            style = "bold" if is_current else None

            table.add_row(
                indicator,
                thread_id_short,
                name,
                created,
                last_used,
                style=style
            )

        console.print()
        console.print(table)
        console.print()
        console.print(f"[dim]Use /threads continue <id> to switch threads[/dim]")
        console.print()
        return True

    # Parse subcommand
    parts = args.split(maxsplit=1)
    subcommand = parts[0].lower()
    subargs = parts[1] if len(parts) > 1 else ""

    # /threads continue <id>
    if subcommand == "continue":
        if not subargs:
            console.print()
            console.print("[yellow]Usage: /threads continue <id>[/yellow]")
            console.print()
            return True

        try:
            thread, _ = find_thread_by_partial_id(thread_manager, subargs)
            thread_manager.switch_thread(thread['id'])

            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ Switched to thread: {thread.get('name') or '(unnamed)'} ({thread['id'][:8]})[/{COLORS['primary']}]"
            )
            console.print()
        except ValueError as e:
            console.print()
            console.print(f"[red]Error: {e}[/red]")
            console.print()

        return True

    # /threads fork [name]
    elif subcommand == "fork":
        name = subargs if subargs else None

        try:
            current_id = thread_manager.get_current_thread_id()
            current_thread = thread_manager.get_thread_metadata(current_id)

            new_id = thread_manager.fork_thread(agent, source_thread_id=current_id, name=name)

            # Compute display name outside f-string to avoid nested f-string syntax error
            current_name = current_thread.get('name') or '(unnamed)'
            fork_name = name or f"Fork of {current_thread.get('name', 'conversation')}"

            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ Forked thread: {current_name} → {fork_name} ({new_id[:8]})[/{COLORS['primary']}]"
            )
            console.print(f"[dim]Now on new thread. Use /threads to see all threads.[/dim]")
            console.print()
        except Exception as e:
            console.print()
            console.print(f"[red]Error forking thread: {e}[/red]")
            console.print()

        return True

    # /threads info [id]
    elif subcommand == "info":
        target_id = subargs if subargs else thread_manager.get_current_thread_id()

        try:
            # If partial ID provided, resolve it
            if subargs:
                thread, _ = find_thread_by_partial_id(thread_manager, subargs)
            else:
                thread = thread_manager.get_thread_metadata(target_id)

            if not thread:
                console.print()
                console.print(f"[red]Thread not found: {target_id}[/red]")
                console.print()
                return True

            # Build info panel
            info_text = f"""[bold]Thread ID:[/bold] {thread['id']}
[bold]Name:[/bold] {thread.get('name') or '(unnamed)'}
[bold]Created:[/bold] {thread.get('created', 'Unknown')}
[bold]Last Used:[/bold] {thread.get('last_used', 'Unknown')}
[bold]Parent:[/bold] {thread.get('parent_id') or 'None (original thread)'}
[bold]Assistant:[/bold] {thread.get('assistant_id', 'Unknown')}"""

            panel = Panel(
                info_text,
                title=f"Thread Info: {thread['id'][:8]}",
                border_style=COLORS['primary']
            )

            console.print()
            console.print(panel)
            console.print()
        except ValueError as e:
            console.print()
            console.print(f"[red]Error: {e}[/red]")
            console.print()

        return True

    # /threads rename <id> <name>
    elif subcommand == "rename":
        if not subargs:
            console.print()
            console.print("[yellow]Usage: /threads rename <id> <name>[/yellow]")
            console.print()
            return True

        # Split into ID and name
        rename_parts = subargs.split(maxsplit=1)
        if len(rename_parts) < 2:
            console.print()
            console.print("[yellow]Usage: /threads rename <id> <name>[/yellow]")
            console.print()
            return True

        partial_id, new_name = rename_parts

        try:
            thread, _ = find_thread_by_partial_id(thread_manager, partial_id)
            old_name = thread.get('name') or '(unnamed)'

            thread_manager.rename_thread(thread['id'], new_name)

            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ Renamed thread {thread['id'][:8]}: {old_name} → {new_name}[/{COLORS['primary']}]"
            )
            console.print()
        except ValueError as e:
            console.print()
            console.print(f"[red]Error: {e}[/red]")
            console.print()

        return True

    # /threads delete <id>
    elif subcommand == "delete":
        console.print()
        console.print("[yellow]Thread deletion not yet implemented.[/yellow]")
        console.print("[dim]This feature requires additional safety checks and will be added in Phase 3.[/dim]")
        console.print()
        return True

    else:
        console.print()
        console.print(f"[yellow]Unknown threads subcommand: {subcommand}[/yellow]")
        console.print("[dim]Available: continue, fork, info, rename[/dim]")
        console.print()
        return True


def handle_command(command: str, agent, token_tracker: TokenTracker, session_state=None) -> str | bool:
    """Handle slash commands. Returns 'exit' to exit, True if handled, False to pass to agent."""
    cmd = command.lower().strip().lstrip("/")

    # Extract command and args
    parts = command.strip().lstrip("/").split(maxsplit=1)
    base_cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if base_cmd in ["quit", "exit", "q"]:
        return "exit"

    if base_cmd == "clear":
        # Use thread manager if available (proper fix for /clear)
        if session_state and session_state.thread_manager:
            thread_manager = session_state.thread_manager

            # Create new thread instead of destroying checkpointer
            new_thread_id = thread_manager.create_thread(name="New conversation")

            # Reset token tracking to baseline
            token_tracker.reset()

            # Clear screen and show fresh UI
            console.clear()
            console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
            console.print()
            console.print(
                f"... Fresh start! Created new thread: {new_thread_id[:8]}",
                style=COLORS["agent"]
            )
            console.print()
        else:
            # Thread manager not available - just clear the screen without destroying checkpointer
            # IMPORTANT: Never replace the checkpointer with InMemorySaver as it breaks persistence
            token_tracker.reset()
            console.clear()
            console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
            console.print()
            console.print(
                "[yellow]Warning: Thread manager not available. Use /new to create a fresh thread.[/yellow]",
                style=COLORS["dim"]
            )
            console.print()

        return True

    if base_cmd == "help":
        show_interactive_help()
        return True

    if base_cmd == "tokens":
        token_tracker.display_session()
        return True

    # /new - Create new thread
    if base_cmd == "new":
        if not session_state or not session_state.thread_manager:
            console.print()
            console.print("[red]Thread manager not available[/red]")
            console.print()
            return True

        thread_manager = session_state.thread_manager
        name = args if args else None

        new_id = thread_manager.create_thread(name=name)

        console.print()
        console.print(
            f"[{COLORS['primary']}]✓ Created new thread: {name or '(unnamed)'} ({new_id[:8]})[/{COLORS['primary']}]",
        )
        console.print()
        return True

    # /threads - Thread management
    if base_cmd == "threads":
        if not session_state or not session_state.thread_manager:
            console.print()
            console.print("[red]Thread manager not available[/red]")
            console.print()
            return True

        return handle_thread_commands(args, session_state.thread_manager, agent)

    console.print()
    console.print(f"[yellow]Unknown command: /{base_cmd}[/yellow]")
    console.print("[dim]Type /help for available commands.[/dim]")
    console.print()
    return True


def execute_bash_command(command: str) -> bool:
    """Execute a bash command and display output. Returns True if handled."""
    cmd = command.strip().lstrip("!")

    if not cmd:
        return True

    try:
        console.print()
        console.print(f"[dim]$ {cmd}[/dim]")

        # Execute the command
        result = subprocess.run(
            cmd, check=False, shell=True, capture_output=True, text=True, timeout=30, cwd=Path.cwd()
        )

        # Display output
        if result.stdout:
            console.print(result.stdout, style=COLORS["dim"], markup=False)
        if result.stderr:
            console.print(result.stderr, style="red", markup=False)

        # Show return code if non-zero
        if result.returncode != 0:
            console.print(f"[dim]Exit code: {result.returncode}[/dim]")

        console.print()
        return True

    except subprocess.TimeoutExpired:
        console.print("[red]Command timed out after 30 seconds[/red]")
        console.print()
        return True
    except Exception as e:
        console.print(f"[red]Error executing command: {e}[/red]")
        console.print()
        return True
