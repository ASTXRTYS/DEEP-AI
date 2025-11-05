"""Command handlers for slash commands and bash execution."""

import subprocess
import sys  # noqa: F401 - needed for test mocking
from datetime import UTC, datetime
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

try:  # POSIX-only modules for raw terminal input
    import termios
    import tty
except ImportError:  # pragma: no cover - exercised indirectly via fallback paths
    termios = None
    tty = None

from .config import COLORS, DEEP_AGENTS_ASCII, console
from .server_client import extract_first_user_message, extract_last_message_preview, get_thread_data
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
        ts_str = iso_timestamp.rstrip("Z")
        ts = datetime.fromisoformat(ts_str)
        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)

        now = datetime.now(UTC)
        delta = now - ts

        seconds = delta.total_seconds()

        if seconds < 60:
            return "just now"
        if seconds < 3600:
            mins = int(seconds / 60)
            return f"{mins}m ago"
        if seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h ago"
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
    matches = [t for t in threads if t["id"].startswith(partial_id)]

    if not matches:
        msg = f"No thread found matching '{partial_id}'"
        raise ValueError(msg)

    if len(matches) > 1:
        match_ids = [t["id"][:8] for t in matches]
        msg = (
            f"Ambiguous thread ID '{partial_id}' - matches multiple threads: {', '.join(match_ids)}\n"
            f"Please provide more characters to uniquely identify the thread."
        )
        raise ValueError(msg)

    return matches[0], matches


def _enrich_thread_with_server_data(thread: dict) -> dict:
    """Enrich thread metadata with data from server API.

    Args:
        thread: Thread metadata from threads.json

    Returns:
        Enriched thread dict with preview and auto-name
    """
    thread_data = get_thread_data(thread["id"])

    if thread_data:
        # Auto-name unnamed threads using first message
        if not thread.get("name") or thread.get("name") == "(unnamed)":
            first_msg = extract_first_user_message(thread_data)
            if first_msg:
                thread["display_name"] = first_msg
            else:
                thread["display_name"] = "(unnamed)"
        else:
            thread["display_name"] = thread["name"]

        # Add message preview
        preview = extract_last_message_preview(thread_data)
        if preview:
            thread["preview"] = preview
    else:
        # Server not available - fallback
        thread["display_name"] = thread.get("name") or "(unnamed)"

    return thread


def _format_thread_summary(thread: dict, current_thread_id: str | None) -> str:
    """Build a single-line summary describing a thread for the picker."""
    display_name = thread.get("display_name") or thread.get("name") or "(unnamed)"
    short_id = thread["id"][:8]
    last_used = relative_time(thread.get("last_used", ""))
    token_count = thread.get("token_count", 0)
    preview = thread.get("preview")

    # Format token count with comma separators for readability
    token_text = f"{token_count:,} tokens"

    current_suffix = " · current" if thread["id"] == current_thread_id else ""

    # Build summary with optional preview
    if preview:
        return f"{short_id}  {display_name}  · {token_text}  · {preview}  · {last_used}{current_suffix}"
    return f"{short_id}  {display_name}  · {token_text}  · Last: {last_used}{current_suffix}"


def _select_thread_interactively(threads, current_thread_id: str | None) -> str | None:
    """Present an interactive picker to choose a thread.

    Uses a simple numbered list for reliable selection across all terminals.
    Returns the selected thread ID, or ``None`` if the selection was cancelled.
    """
    if not threads:
        return None

    return _select_thread_fallback(threads, current_thread_id)


def _select_thread_fallback(threads, current_thread_id: str | None) -> str | None:
    """Fallback selection that works without raw TTY capabilities."""
    console.print()
    console.print("Select a thread:")

    default_index = 0
    if current_thread_id:
        for idx, thread in enumerate(threads):
            if thread["id"] == current_thread_id:
                default_index = idx
                break

    for idx, thread in enumerate(threads, start=1):
        summary = _format_thread_summary(thread, current_thread_id)
        selector = "*" if idx - 1 == default_index else " "
        console.print(f"  [{selector}] {idx}. {summary}")

    console.print()
    prompt = f"Choice (1-{len(threads)}; Enter to cancel) [default={default_index + 1}]: "
    try:
        choice = input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return None

    if not choice:
        return threads[default_index]["id"]

    if not choice.isdigit():
        console.print(f"[red]Invalid selection: {choice}[/red]")
        console.print()
        return None

    selected_idx = int(choice) - 1
    if selected_idx < 0 or selected_idx >= len(threads):
        console.print(f"[red]Selection out of range: {choice}[/red]")
        console.print()
        return None

    return threads[selected_idx]["id"]


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

    # /threads (no args) - Show interactive picker
    if not args:
        threads = thread_manager.list_threads()
        current_id = thread_manager.get_current_thread_id()

        if not threads:
            console.print()
            console.print("[yellow]No threads available.[/yellow]")
            console.print()
            return True

        # Enrich threads with server data (messages, preview, auto-names)
        enriched_threads = [_enrich_thread_with_server_data(t) for t in threads]

        console.print()
        try:
            target_id = _select_thread_interactively(enriched_threads, current_id)
        except KeyboardInterrupt:
            console.print("\n[red]Thread selection interrupted.[/red]")
            console.print()
            return True

        console.print()

        if not target_id:
            console.print("[dim]Thread selection cancelled.[/dim]")
            console.print()
            return True

        # Switch to selected thread
        try:
            thread_manager.switch_thread(target_id)
            thread = thread_manager.get_thread_metadata(target_id)
            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ Switched to thread: {thread.get('name') or '(unnamed)'} ({target_id[:8]})[/{COLORS['primary']}]"
            )
            console.print()
        except ValueError as e:
            console.print()
            console.print(f"[red]Error: {e}[/red]")
            console.print()

        return True

    # Parse subcommand
    parts = args.split(maxsplit=1)
    subcommand = parts[0].lower()
    subargs = parts[1] if len(parts) > 1 else ""

    # /threads list - Show table overview
    if subcommand == "list":
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
            border_style=COLORS["dim"],
        )

        table.add_column("", width=2)  # Current thread indicator
        table.add_column("ID", style=COLORS["primary"], width=10)
        table.add_column("Name", style="white")
        table.add_column("Tokens", style=COLORS["accent"], width=12, justify="right")
        table.add_column("Created", style=COLORS["dim"], width=12)
        table.add_column("Last Used", style=COLORS["dim"], width=12)

        for thread in threads:
            is_current = thread["id"] == current_id
            indicator = "→" if is_current else ""
            thread_id_short = thread["id"][:8]
            name = thread.get("name") or "(unnamed)"
            token_count = thread.get("token_count", 0)
            created = relative_time(thread.get("created", ""))
            last_used = relative_time(thread.get("last_used", ""))

            # Highlight current thread row
            style = "bold" if is_current else None

            table.add_row(
                indicator,
                thread_id_short,
                name,
                f"{token_count:,}",
                created,
                last_used,
                style=style,
            )

        console.print()
        console.print(table)
        console.print()
        console.print("[dim]Tip: Use /threads to open the picker[/dim]")
        console.print()
        return True

    # /threads continue <id>
    if subcommand == "continue":
        threads = thread_manager.list_threads()
        if not threads:
            console.print()
            console.print("[yellow]No threads available to switch to.[/yellow]")
            console.print()
            return True

        target_id = subargs.strip()

        if not target_id:
            # Enrich threads with server data for picker
            enriched_threads = [_enrich_thread_with_server_data(t) for t in threads]

            console.print()
            try:
                target_id = _select_thread_interactively(
                    enriched_threads, thread_manager.get_current_thread_id()
                )
            except KeyboardInterrupt:
                console.print("\n[red]Thread selection interrupted.[/red]")
                console.print()
                return True

            console.print()

            if not target_id:
                console.print("[dim]Thread selection cancelled.[/dim]")
                console.print()
                return True

        try:
            thread, _ = find_thread_by_partial_id(thread_manager, target_id)
            thread_manager.switch_thread(thread["id"])

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
    if subcommand == "fork":
        name = subargs if subargs else None

        try:
            current_id = thread_manager.get_current_thread_id()
            current_thread = thread_manager.get_thread_metadata(current_id)

            new_id = thread_manager.fork_thread(agent, source_thread_id=current_id, name=name)

            # Compute display name outside f-string to avoid nested f-string syntax error
            current_name = current_thread.get("name") or "(unnamed)"
            fork_name = name or f"Fork of {current_thread.get('name', 'conversation')}"

            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ Forked thread: {current_name} → {fork_name} ({new_id[:8]})[/{COLORS['primary']}]"
            )
            console.print("[dim]Now on new thread. Use /threads to see all threads.[/dim]")
            console.print()
        except Exception as e:
            console.print()
            console.print(f"[red]Error forking thread: {e}[/red]")
            console.print()

        return True

    # /threads info [id]
    if subcommand == "info":
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
            info_text = f"""[bold]Thread ID:[/bold] {thread["id"]}
[bold]Name:[/bold] {thread.get("name") or "(unnamed)"}
[bold]Created:[/bold] {thread.get("created", "Unknown")}
[bold]Last Used:[/bold] {thread.get("last_used", "Unknown")}
[bold]Parent:[/bold] {thread.get("parent_id") or "None (original thread)"}
[bold]Assistant:[/bold] {thread.get("assistant_id", "Unknown")}"""

            panel = Panel(
                info_text, title=f"Thread Info: {thread['id'][:8]}", border_style=COLORS["primary"]
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
    if subcommand == "rename":
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
            old_name = thread.get("name") or "(unnamed)"

            thread_manager.rename_thread(thread["id"], new_name)

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
    if subcommand == "delete":
        if not subargs:
            console.print()
            console.print("[yellow]Usage: /threads delete <id>[/yellow]")
            console.print()
            return True

        try:
            thread, _ = find_thread_by_partial_id(thread_manager, subargs)
            thread_name = thread.get("name") or "(unnamed)"
            thread_id_short = thread["id"][:8]

            # Confirm deletion
            console.print()
            console.print(f"[yellow]⚠️  Delete thread:[/yellow] {thread_name} ({thread_id_short})")
            console.print(f"[dim]Created: {relative_time(thread.get('created', ''))}[/dim]")
            console.print()

            response = console.input(
                "[yellow]Are you sure? This cannot be undone. (yes/no): [/yellow]"
            )
            console.print()

            if response.lower() not in ["yes", "y"]:
                console.print("[dim]Deletion cancelled.[/dim]")
                console.print()
                return True

            # Delete the thread
            thread_manager.delete_thread(thread["id"], agent)

            console.print(
                f"[{COLORS['primary']}]✓ Deleted thread: {thread_name} ({thread_id_short})[/{COLORS['primary']}]"
            )
            console.print()
        except ValueError as e:
            console.print()
            console.print(f"[red]Error: {e}[/red]")
            console.print()

        return True

    # /threads cleanup [--days N]
    if subcommand == "cleanup":
        # Parse --days flag or use default
        days_old = 30
        if subargs.startswith("--days"):
            parts = subargs.split()
            if len(parts) >= 2:
                try:
                    days_old = int(parts[1])
                except ValueError:
                    console.print()
                    console.print("[red]Error: --days must be followed by a number[/red]")
                    console.print("[yellow]Usage: /threads cleanup [--days N][/yellow]")
                    console.print()
                    return True

        # Dry run to show what would be deleted
        console.print()
        console.print(f"[dim]Checking for threads older than {days_old} days...[/dim]")

        try:
            count, names = thread_manager.cleanup_old_threads(days_old, agent, dry_run=True)
        except Exception as e:
            console.print()
            console.print(f"[red]Error checking threads: {e}[/red]")
            console.print()
            return True

        if count == 0:
            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ No threads older than {days_old} days found.[/{COLORS['primary']}]"
            )
            console.print()
            return True

        # Show preview
        console.print()
        console.print(
            f"[yellow]⚠️  Will delete {count} thread(s) older than {days_old} days:[/yellow]"
        )
        for name in names[:10]:  # Show first 10
            console.print(f"  • {name}")
        if count > 10:
            console.print(f"  ... and {count - 10} more")
        console.print()

        response = console.input("[yellow]Proceed with deletion? (yes/no): [/yellow]")
        console.print()

        if response.lower() not in ["yes", "y"]:
            console.print("[dim]Cleanup cancelled.[/dim]")
            console.print()
            return True

        # Actually delete
        try:
            count, names = thread_manager.cleanup_old_threads(days_old, agent, dry_run=False)
            console.print(f"[{COLORS['primary']}]✓ Deleted {count} thread(s)[/{COLORS['primary']}]")
            console.print("[dim]Tip: Run /threads vacuum to reclaim disk space[/dim]")
            console.print()
        except Exception as e:
            console.print()
            console.print(f"[red]Error during cleanup: {e}[/red]")
            console.print()

        return True

    # /threads sync
    if subcommand == "sync":
        console.print()
        console.print("[dim]Checking for metadata/checkpoint inconsistencies...[/dim]")

        try:
            preview = thread_manager.reconcile_with_checkpointer(apply=False)
        except Exception as e:  # pragma: no cover - defensive
            console.print()
            console.print(f"[red]Error during reconciliation: {e}[/red]")
            console.print()
            return True

        if not preview.pending_changes:
            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ Threads are already in sync.[/{COLORS['primary']}]"
            )
            console.print()
            return True

        console.print()
        if preview.metadata_only:
            console.print("[yellow]Metadata with no matching checkpoints:[/yellow]")
            for thread in preview.metadata_only[:10]:
                name = thread.get("name") or "(unnamed)"
                console.print(f"  • {name} ({thread['id'][:8]})")
            if len(preview.metadata_only) > 10:
                console.print(f"  ... and {len(preview.metadata_only) - 10} more")
            console.print()

        if preview.checkpoint_only:
            console.print("[yellow]Checkpoints missing from metadata:[/yellow]")
            for thread_id in preview.checkpoint_only[:10]:
                console.print(f"  • {thread_id[:8]}")
            if len(preview.checkpoint_only) > 10:
                console.print(f"  ... and {len(preview.checkpoint_only) - 10} more")
            console.print()

        console.print(
            "[dim]Recent or active threads without checkpoints are preserved automatically.[/dim]"
        )
        console.print()

        response = console.input("[yellow]Apply fixes? (yes/no): [/yellow]")
        console.print()

        if response.lower() not in ["yes", "y"]:
            console.print("[dim]Sync cancelled.[/dim]")
            console.print()
            return True

        try:
            result = thread_manager.reconcile_with_checkpointer(apply=True)
        except Exception as e:  # pragma: no cover - defensive
            console.print(f"[red]Error applying reconciliation: {e}[/red]")
            console.print()
            return True

        console.print(f"[{COLORS['primary']}]✓ Threads synchronized.[/{COLORS['primary']}]")

        if result.removed:
            console.print("  Removed metadata entries:")
            for thread in result.removed:
                name = thread.get("name") or "(unnamed)"
                console.print(f"    • {name} ({thread['id'][:8]})")

        if result.added:
            console.print("  Recovered threads from checkpoints:")
            for thread in result.added:
                name = thread.get("name") or "(unnamed)"
                console.print(f"    • {name} ({thread['id'][:8]})")

        if result.current_thread_changed and result.new_current_thread_id:
            console.print(
                f"  New current thread: {result.new_current_thread_id[:8]}",
                style=COLORS["dim"],
            )

        console.print()
        return True

    # /threads vacuum
    if subcommand == "vacuum":
        console.print()
        console.print("[dim]Vacuuming database to reclaim disk space...[/dim]")

        try:
            result = thread_manager.vacuum_database()
            size_before = result["size_before"]
            size_after = result["size_after"]
            reclaimed = size_before - size_after

            # Format sizes
            def format_bytes(b) -> str:
                if b < 1024:
                    return f"{b}B"
                if b < 1024 * 1024:
                    return f"{b / 1024:.1f}KB"
                return f"{b / (1024 * 1024):.1f}MB"

            console.print()
            console.print(f"[{COLORS['primary']}]✓ Vacuum complete[/{COLORS['primary']}]")
            console.print(f"  Before: {format_bytes(size_before)}")
            console.print(f"  After:  {format_bytes(size_after)}")
            if reclaimed > 0:
                console.print(f"  Reclaimed: {format_bytes(reclaimed)}")
            else:
                console.print("  No space reclaimed (database was already compact)")
            console.print()
        except Exception as e:
            console.print()
            console.print(f"[red]Error during vacuum: {e}[/red]")
            console.print()

        return True

    # /threads stats
    if subcommand == "stats":
        console.print()
        console.print("[dim]Gathering database statistics...[/dim]")

        try:
            stats = thread_manager.get_database_stats()

            # Format size
            def format_bytes(b) -> str:
                if b < 1024:
                    return f"{b}B"
                if b < 1024 * 1024:
                    return f"{b / 1024:.1f}KB"
                return f"{b / (1024 * 1024):.1f}MB"

            # Build stats panel
            stats_text = f"""[bold]Threads:[/bold] {stats["thread_count"]}
[bold]Checkpoints:[/bold] {stats["checkpoint_count"]}
[bold]Database Size:[/bold] {format_bytes(stats["db_size_bytes"])}"""

            if stats["oldest_thread"]:
                oldest = stats["oldest_thread"]
                stats_text += f"\n\n[bold]Oldest Thread:[/bold]\n  {oldest.get('name') or '(unnamed)'} ({oldest['id'][:8]})\n  Created: {relative_time(oldest.get('created', ''))}"

            if stats["newest_thread"]:
                newest = stats["newest_thread"]
                stats_text += f"\n\n[bold]Newest Thread:[/bold]\n  {newest.get('name') or '(unnamed)'} ({newest['id'][:8]})\n  Created: {relative_time(newest.get('created', ''))}"

            # Average checkpoints per thread
            if stats["thread_count"] > 0:
                avg_checkpoints = stats["checkpoint_count"] / stats["thread_count"]
                stats_text += f"\n\n[bold]Avg Checkpoints/Thread:[/bold] {avg_checkpoints:.1f}"

            panel = Panel(stats_text, title="Database Statistics", border_style=COLORS["primary"])

            console.print()
            console.print(panel)
            console.print()
        except Exception as e:
            console.print()
            console.print(f"[red]Error gathering stats: {e}[/red]")
            console.print()

        return True

    console.print()
    console.print(f"[yellow]Unknown threads subcommand: {subcommand}[/yellow]")
    console.print(
        "[dim]Available: continue, fork, info, rename, delete, cleanup, sync, vacuum, stats[/dim]"
    )
    console.print()
    return True


def handle_command(
    command: str, agent, token_tracker: TokenTracker, session_state=None
) -> str | bool:
    """Handle slash commands. Returns 'exit' to exit, True if handled, False to pass to agent."""
    command.lower().strip().lstrip("/")

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
                f"... Fresh start! Created new thread: {new_thread_id[:8]}", style=COLORS["agent"]
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
                style=COLORS["dim"],
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
