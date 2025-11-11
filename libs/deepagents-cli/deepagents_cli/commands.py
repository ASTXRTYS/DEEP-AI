"""Command handlers for slash commands and bash execution."""

import asyncio
import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from langsmith import Client
from requests.exceptions import HTTPError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import COLORS, DEEP_AGENTS_ASCII, console
from .execution import execute_task
from .server_client import extract_first_user_message, extract_last_message_preview, get_thread_data
from .ui import TokenTracker, show_interactive_help

logger = logging.getLogger(__name__)

# Simple TTL cache (5 minutes)
_metrics_cache = {}
_cache_ttl = 300  # seconds


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


def get_langsmith_client() -> Client | None:
    """Get LangSmith client if API key is configured."""
    api_key = os.getenv("LANGCHAIN_API_KEY")

    if not api_key:
        return None

    return Client()


@retry(
    retry=retry_if_exception_type(HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _fetch_langsmith_metrics_sync(
    thread_id: str, client: Client, project_name: str
) -> tuple[int | None, int | None]:
    """Fetch trace count and total tokens from LangSmith (sync).

    Uses robust filter matching all metadata keys (session_id, conversation_id, thread_id).
    Retries on HTTPError with exponential backoff (handles 429 rate limits).

    Args:
        thread_id: Thread ID to fetch metrics for
        client: LangSmith Client instance
        project_name: LangSmith project name

    Returns:
        (trace_count, total_tokens) tuple
        - Both ints: success
        - Both None: error/unavailable
    """
    try:
        # Robust filter for all metadata keys
        filter_string = (
            "and("
            '  in(metadata_key, ["session_id", "conversation_id", "thread_id"]),'
            f'  eq(metadata_value, "{thread_id}")'
            ")"
        )

        trace_count = 0
        total_tokens = 0

        logger.debug(f"Fetching LangSmith metrics for thread {thread_id[:8]}...")

        # Synchronous list_runs (client.list_runs is sync generator)
        for run in client.list_runs(
            project_name=project_name,
            filter=filter_string,
            is_root=True,  # Only root runs = traces
        ):
            trace_count += 1
            if run.total_tokens:
                total_tokens += run.total_tokens

        logger.debug(f"Fetched: {trace_count} traces, {total_tokens:,} tokens")
        return trace_count, total_tokens

    except HTTPError as e:
        if e.response.status_code == 429:
            logger.warning(f"Rate limited on thread {thread_id[:8]}, retrying...")
            # Let retry handle it
            raise
        logger.error(f"HTTPError fetching metrics for {thread_id[:8]}: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Error fetching metrics for {thread_id[:8]}: {e}")
        return None, None


async def _get_langsmith_metrics_async(
    thread_id: str, client: Client, project_name: str, executor: ThreadPoolExecutor
) -> tuple[int | None, int | None]:
    """Async wrapper around sync LangSmith API call.

    Checks cache first (5-minute TTL), then runs blocking call in thread pool.

    Args:
        thread_id: Thread ID to fetch metrics for
        client: LangSmith Client instance
        project_name: LangSmith project name
        executor: ThreadPoolExecutor for blocking calls

    Returns:
        (trace_count, total_tokens) tuple or (None, None) on error
    """
    # Check cache
    cache_key = f"{project_name}:{thread_id}"
    if cache_key in _metrics_cache:
        cached_data, cached_time = _metrics_cache[cache_key]
        if time.time() - cached_time < _cache_ttl:
            logger.debug(f"Cache hit: {cache_key}")
            return cached_data

    # Run blocking call in thread pool
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor, _fetch_langsmith_metrics_sync, thread_id, client, project_name
    )

    # Cache result (even errors - avoid hammering on repeated failures)
    _metrics_cache[cache_key] = (result, time.time())

    return result


async def _enrich_threads_with_metrics(
    threads: list[dict], client: Client | None, project_name: str, executor: ThreadPoolExecutor
) -> list[dict]:
    """Enrich all threads with LangSmith metrics concurrently.

    Uses semaphore to limit concurrent requests to 5, respecting
    LangSmith rate limits (10 req/10sec). Blocks in ThreadPoolExecutor
    to avoid blocking event loop.

    Args:
        threads: List of thread dicts to enrich
        client: LangSmith Client or None
        project_name: LangSmith project name
        executor: ThreadPoolExecutor for blocking I/O

    Returns:
        List of enriched threads with trace_count and langsmith_tokens
    """
    if not client:
        # No client - use local token counts, no traces
        logger.debug("No LangSmith client - using local token counts")
        for thread in threads:
            thread["trace_count"] = 0
            thread["langsmith_tokens"] = thread.get("token_count", 0)
        return threads

    # Limit concurrent requests to avoid rate limits
    semaphore = asyncio.Semaphore(5)

    async def fetch_metrics(thread: dict):
        async with semaphore:
            trace_count, tokens = await _get_langsmith_metrics_async(
                thread["id"], client, project_name, executor
            )

            # Store metrics
            thread["trace_count"] = trace_count
            if tokens is not None:
                thread["langsmith_tokens"] = tokens
            else:
                # Error - fall back to local token count
                thread["langsmith_tokens"] = thread.get("token_count", 0)

    # Fetch all concurrently
    logger.debug(f"Fetching metrics for {len(threads)} threads concurrently...")
    await asyncio.gather(*[fetch_metrics(t) for t in threads])

    return threads


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
    """Build a single-line summary matching LangSmith UI format."""
    display_name = thread.get("display_name") or thread.get("name") or "(unnamed)"
    short_id = thread["id"][:8]
    last_used = relative_time(thread.get("last_used", ""))

    # Get LangSmith metrics
    trace_count = thread.get("trace_count")
    tokens = thread.get("langsmith_tokens", 0)

    # Format trace count (distinguish error from empty)
    if trace_count is None:
        trace_display = "??"  # Error state
    else:
        trace_display = str(trace_count)

    # Format tokens with K/M abbreviations OR comma separators
    if tokens >= 1_000_000:
        token_display = f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        token_display = f"{tokens / 1_000:.1f}K"
    else:
        token_display = f"{tokens:,}"  # Comma separators for <1K

    # Build stats like LangSmith: "12 traces · 34.5K tokens"
    stats = f"{trace_display} traces · {token_display} tokens"

    current_suffix = " · current" if thread["id"] == current_thread_id else ""

    preview = thread.get("preview")
    if preview:
        return f"{short_id}  {display_name}  · {stats}  · {preview}  · {last_used}{current_suffix}"
    return f"{short_id}  {display_name}  · {stats}  · Last: {last_used}{current_suffix}"


async def _select_thread_with_questionary(
    threads, current_thread_id: str | None
) -> tuple[str, str] | tuple[None, None]:
    """Interactive thread picker using questionary with arrow key navigation.

    Args:
        threads: List of thread metadata dicts
        current_thread_id: ID of currently active thread

    Returns:
        Tuple of (thread_id, action) or (None, None) if cancelled
    """
    import questionary
    from questionary import Choice, Style

    # Custom style matching CLI color scheme
    # Key insight from questionary docs: highlighted needs BACKGROUND color to be visually obvious
    custom_style = Style(
        [
            ("qmark", f"{COLORS['primary']} bold"),
            ("question", "bold"),
            ("answer", f"{COLORS['primary']} bold"),
            ("pointer", f"{COLORS['primary']} bold"),
            (
                "highlighted",
                f"#ffffff bg:{COLORS['primary']} bold",
            ),  # White text on green background
            ("selected", f"{COLORS['primary']}"),
            ("instruction", "#888888 italic"),
            ("text", ""),
            ("search_success", f"{COLORS['primary']}"),  # Successful search results
            ("search_none", "#888888"),  # No search results message
            ("separator", "#888888"),  # Separators in lists
        ]
    )

    console.print()

    # Build choices with formatted display
    choices = []
    default_choice = None

    for thread in threads:
        summary = _format_thread_summary(thread, current_thread_id)
        choice = Choice(title=summary, value=thread["id"])
        choices.append(choice)

        # Mark current thread as default
        if thread["id"] == current_thread_id:
            default_choice = choice

    # Step 1: Select thread with search filtering for large lists
    try:
        selected_id = await questionary.select(
            "Select a thread:",
            choices=choices,
            default=default_choice,
            use_arrow_keys=True,
            use_indicator=True,
            use_shortcuts=False,
            use_search_filter=len(threads) > 10,  # Enable search for 10+ threads
            style=custom_style,
            qmark="▶",
            pointer="●",
            instruction="(↑↓ navigate, Enter select, type to search)"
            if len(threads) > 10
            else "(↑↓ navigate, Enter select)",
        ).ask_async()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return None, None

    if not selected_id:
        console.print()
        return None, None

    # Step 2: Select action
    thread = next((t for t in threads if t["id"] == selected_id), None)
    if not thread:
        return None, None

    thread_name = thread.get("display_name") or thread.get("name") or "(unnamed)"
    short_id = selected_id[:8]

    console.print()
    console.print(f"[{COLORS['primary']}]✓ Selected: {thread_name} ({short_id})[/]")
    console.print()

    # Action menu style - same background highlighting
    action_style = Style(
        [
            ("qmark", f"{COLORS['primary']} bold"),
            ("question", "bold"),
            ("answer", f"{COLORS['primary']} bold"),
            ("pointer", f"{COLORS['primary']} bold"),
            ("highlighted", f"#ffffff bg:{COLORS['primary']} bold"),  # Consistent highlighting
            ("selected", f"{COLORS['primary']}"),
            ("instruction", "#888888 italic"),
            ("text", ""),
            ("search_success", f"{COLORS['primary']}"),  # Successful search results
            ("search_none", "#888888"),  # No search results message
            ("separator", "#888888"),  # Separators in lists
        ]
    )

    action_choices = [
        Choice(title="↻  Switch to this thread", value="switch"),
        Choice(title="✕  Delete this thread", value="delete"),
        Choice(title="✎  Rename this thread", value="rename"),
        Choice(title="←  Cancel", value="cancel"),
    ]

    try:
        action = await questionary.select(
            "Choose an action:",
            choices=action_choices,
            use_arrow_keys=True,
            use_indicator=True,
            use_shortcuts=False,
            style=action_style,
            qmark="▶",
            pointer="●",
            instruction="(↑↓ navigate, Enter select)",
        ).ask_async()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return None, None

    if not action or action == "cancel":
        console.print()
        return None, None

    return selected_id, action


async def _confirm_thread_deletion(thread: dict) -> bool:
    """Show confirmation dialog for thread deletion.

    Args:
        thread: Thread metadata dict

    Returns:
        True if user confirmed deletion, False otherwise
    """
    import questionary
    from questionary import Style

    # Warning style for deletion confirmation
    warning_style = Style(
        [
            ("qmark", "#f59e0b bold"),  # Amber/orange for warning
            ("question", "bold"),
            ("answer", "#ef4444 bold"),  # Red for destructive action
            ("instruction", "#888888 italic"),
            ("text", ""),
        ]
    )

    thread_name = thread.get("display_name") or thread.get("name") or "(unnamed)"
    short_id = thread["id"][:8]
    trace_count = thread.get("trace_count", 0)
    tokens = thread.get("langsmith_tokens", 0)

    # Format token count with K/M abbreviations
    if tokens >= 1_000_000:
        token_display = f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        token_display = f"{tokens / 1_000:.1f}K"
    else:
        token_display = f"{tokens:,}"

    console.print()
    console.print("[yellow]⚠  WARNING: Permanent Deletion[/yellow]")
    console.print()
    console.print(f"[bold]Thread:[/bold] {thread_name} [dim]({short_id})[/dim]")
    console.print()
    console.print("[dim]This will permanently delete:[/dim]")
    console.print(f"[dim]  • All conversation history ({trace_count} traces)[/dim]")
    console.print(f"[dim]  • {token_display} tokens of context[/dim]")
    console.print("[dim]  • Cannot be undone[/dim]")
    console.print()

    try:
        confirmation = await questionary.text(
            "Type 'DELETE' to confirm:",
            validate=lambda text: text == "DELETE" or "Must type DELETE exactly (case-sensitive)",
            style=warning_style,
            qmark="⚠",
            instruction="(Type DELETE in all caps to confirm)",
        ).ask_async()
    except (KeyboardInterrupt, EOFError):
        console.print()
        console.print("[dim]✓ Deletion cancelled.[/dim]")
        console.print()
        return False

    if confirmation != "DELETE":
        console.print()
        console.print("[dim]✓ Deletion cancelled.[/dim]")
        console.print()
        return False

    return True


async def _select_thread_interactively(
    threads, current_thread_id: str | None
) -> tuple[str, str] | tuple[None, None]:
    """Present an interactive picker to choose a thread and action.

    Returns tuple of (thread_id, action) where action is 'switch', 'delete', or 'rename'.
    Returns (None, None) if selection was cancelled.
    """
    if not threads:
        return None, None

    return await _select_thread_with_questionary(threads, current_thread_id)


# Removed _select_thread_fallback - no longer needed after questionary migration


async def handle_thread_commands_async(args: str, thread_manager, agent) -> bool:
    """Handle /threads subcommands (async version)."""
    args = args.strip()

    if not args:
        threads = thread_manager.list_threads()
        current_id = thread_manager.get_current_thread_id()

        if not threads:
            console.print()
            console.print("[yellow]No threads available.[/yellow]")
            console.print()
            return True

        # Phase 1: Enrich with server data (sync, blocking)
        enriched_threads = [_enrich_thread_with_server_data(t) for t in threads]

        # Phase 2: Enrich with LangSmith metrics (async, concurrent)
        langsmith_client = get_langsmith_client()
        project_name = os.getenv("LANGCHAIN_PROJECT", "deepagents-cli")

        # Use context manager for executor cleanup
        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_threads = await _enrich_threads_with_metrics(
                enriched_threads, langsmith_client, project_name, executor
            )

        console.print()
        try:
            target_id, action = await _select_thread_interactively(enriched_threads, current_id)
        except KeyboardInterrupt:
            console.print("\n[red]Thread selection interrupted.[/red]")
            console.print()
            return True

        console.print()

        if not target_id or not action:
            console.print("[dim]Selection cancelled.[/dim]")
            console.print()
            return True

        # Get thread metadata for all actions
        thread = next((t for t in enriched_threads if t["id"] == target_id), None)
        if not thread:
            console.print("[red]Thread not found.[/red]")
            console.print()
            return True

        thread_name = thread.get("display_name") or thread.get("name") or "(unnamed)"
        short_id = target_id[:8]

        # Handle action
        if action == "switch":
            try:
                thread_manager.switch_thread(target_id)
                console.print()
                console.print(
                    f"[{COLORS['primary']}]✓ Switched to thread: {thread_name} ({short_id})[/{COLORS['primary']}]"
                )
                console.print()
            except ValueError as e:
                console.print()
                console.print(f"[red]Error: {e}[/red]")
                console.print()

        elif action == "delete":
            # Confirm deletion
            if not await _confirm_thread_deletion(thread):
                return True

            # Perform deletion
            try:
                thread_manager.delete_thread(target_id, agent)
                console.print()
                console.print(f"[green]✓ Deleted thread: {thread_name} ({short_id})[/green]")
                console.print()
            except ValueError as e:
                console.print()
                console.print(f"[red]Error: {e}[/red]")
                console.print()

        elif action == "rename":
            import questionary
            from questionary import Style

            # Custom style for rename
            rename_style = Style(
                [
                    ("qmark", f"{COLORS['primary']} bold"),
                    ("question", "bold"),
                    ("answer", f"{COLORS['primary']} bold"),
                    ("instruction", "#888888 italic"),
                    ("text", ""),
                ]
            )

            console.print()
            try:
                new_name = await questionary.text(
                    "Enter new thread name:",
                    default=thread_name if thread_name != "(unnamed)" else "",
                    style=rename_style,
                    qmark="✎",
                    instruction="(Enter to confirm, Ctrl+C to cancel)",
                    validate=lambda text: len(text.strip()) > 0 or "Thread name cannot be empty",
                ).ask_async()
            except (KeyboardInterrupt, EOFError):
                console.print()
                console.print("[dim]✓ Rename cancelled.[/dim]")
                console.print()
                return True

            if not new_name or new_name.strip() == thread_name:
                console.print()
                console.print("[dim]✓ Rename cancelled.[/dim]")
                console.print()
                return True

            try:
                thread_manager.rename_thread(target_id, new_name.strip())
                console.print()
                console.print(
                    f"[{COLORS['primary']}]✓ Renamed thread to: {new_name.strip()} [dim]({short_id})[/dim][/{COLORS['primary']}]"
                )
                console.print()
            except ValueError as e:
                console.print()
                console.print(f"[red]✕ Error: {e}[/red]")
                console.print()

        return True

    # If args provided, unsupported
    console.print()
    console.print("[yellow]The /threads command doesn't take arguments[/yellow]")
    console.print("[dim]Just type /threads to open the interactive picker[/dim]")
    console.print()
    return True


async def handle_handoff_command(args: str, agent, session_state) -> bool:
    """Handle /handoff command via tool invocation.

    Args:
        args: Command arguments (--preview or -p for preview only)
        agent: The agent instance
        session_state: Current session state

    Returns:
        True (command handled)
    """
    if not session_state or not session_state.thread_manager:
        console.print()
        console.print("[red]Thread manager not available for handoff.[/red]")
        console.print()
        return True

    if agent is None:
        console.print()
        console.print("[red]Agent is not initialized; cannot run /handoff.[/red]")
        console.print()
        return True

    # Parse args
    preview_only = "--preview" in args or "-p" in args

    # Get current thread info
    thread_id = session_state.thread_manager.get_current_thread_id()
    assistant_id = getattr(session_state.thread_manager, "assistant_id", None)

    console.print()
    console.print(f"[{COLORS['primary']}]Initiating handoff...[/]")

    # Use execute_task to properly handle state-based interrupts via streaming
    # This follows LangChain v1 best practices for interrupt handling

    user_input = "Please call the request_handoff tool to initiate thread handoff."

    await execute_task(
        user_input=user_input,
        agent=agent,
        assistant_id=assistant_id,
        session_state=session_state,
        token_tracker=None,
    )

    # The execution loop handles approval UI and persistence when it detects handoff_approval_pending
    return True


async def handle_command(
    command: str, agent, token_tracker: TokenTracker, session_state=None
) -> str | bool:
    """Handle slash commands. Returns 'exit' to exit, True if handled, False to pass to agent."""
    command = command.strip()
    if not command:
        return False

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

    if base_cmd == "menu" or base_cmd == "m":
        # Open main menu
        if not session_state:
            console.print()
            console.print("[red]Session state not available[/red]")
            console.print()
            return True

        from .menu_system import MenuSystem

        menu_system = MenuSystem(session_state, agent, token_tracker)
        result = await menu_system.show_main_menu()
        if result == "exit":
            return "exit"
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

        return await handle_thread_commands_async(args, session_state.thread_manager, agent)

    if base_cmd == "handoff":
        return await handle_handoff_command(args, agent, session_state)

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
