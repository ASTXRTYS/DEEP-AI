"""Command handlers for slash commands and bash execution."""

import subprocess
import sys  # noqa: F401 - needed for test mocking
from datetime import UTC, datetime
from pathlib import Path

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

    # If args provided, it's an unsupported subcommand
    console.print()
    console.print("[yellow]The /threads command doesn't take arguments[/yellow]")
    console.print("[dim]Just type /threads to open the interactive picker[/dim]")
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
