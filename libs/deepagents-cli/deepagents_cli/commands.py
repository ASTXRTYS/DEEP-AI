"""Command handlers for slash commands and bash execution."""

import asyncio
import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langsmith import Client

try:
    from httpx import HTTPStatusError as HttpxHTTPStatusError
    from httpx import RequestError as HttpxRequestError
except Exception:  # pragma: no cover - httpx may be indirect dep

    class HttpxHTTPStatusError(Exception):  # type: ignore
        pass

    class HttpxRequestError(Exception):  # type: ignore
        pass


from rich.markup import escape
from rich.panel import Panel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import COLORS, DEEP_AGENTS_ASCII, console, handle_error
from .execution import execute_task
from .rich_ui import RichPrompt, create_thread_table
from .thread_display import (
    check_server_availability,
    enrich_thread_with_server_data,
    format_thread_summary,
)
from .ui import TokenTracker, show_interactive_help
from .ui_constants import Colors

logger = logging.getLogger(__name__)

# Simple TTL cache (5 minutes)
_metrics_cache = {}
_cache_ttl = 300  # seconds


def get_langsmith_client() -> Client | None:
    """Get LangSmith client if API key is configured."""
    api_key = os.getenv("LANGCHAIN_API_KEY")

    if not api_key:
        return None

    return Client()


@retry(
    retry=retry_if_exception_type((HttpxHTTPStatusError, HttpxRequestError)),
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

    except HttpxHTTPStatusError as e:
        try:
            status = e.response.status_code if e.response is not None else None
        except Exception:
            status = None
        if status == 429:
            logger.warning(f"Rate limited on thread {thread_id[:8]}, retrying...")
            # Let retry handle it
            raise
        logger.error(f"HTTP status error fetching metrics for {thread_id[:8]}: {e}")
        return None, None
    except HttpxRequestError as e:
        logger.error(f"HTTP request error fetching metrics for {thread_id[:8]}: {e}")
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
    loop = asyncio.get_running_loop()
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


async def _select_thread_with_rich(
    threads, current_thread_id: str | None, session_state, prompt_session
) -> tuple[str, str] | tuple[None, None]:
    """Interactive thread picker using Rich prompts.

    Args:
        threads: List of thread metadata dicts
        current_thread_id: ID of currently active thread
        session_state: Current session state
        prompt_session: Main PromptSession for unified Application lifecycle

    Returns:
        Tuple of (thread_id, action) or (None, None) if cancelled
    """
    import asyncio

    try:
        rich_prompt = RichPrompt(console, session_state, prompt_session)

        # Create thread table for context panel
        table = create_thread_table(threads, current_thread_id)

        # Check server availability and add warning if offline
        server_available = check_server_availability()
        if not server_available:
            from rich.console import Group
            from rich.text import Text

            warning = Text()
            warning.append("⚠  ", style="yellow bold")
            warning.append("LangGraph server offline", style="yellow")
            warning.append(" – showing local metadata only\n", style="dim")
            warning.append(
                "   Previews and metrics may be stale. Start server with: ",
                style="dim",
            )
            warning.append("langgraph dev", style="cyan")

            table_with_warning = Group(warning, table)
            table_panel = Panel(
                table_with_warning,
                title=f"[bold {Colors.PRIMARY}]Thread Management[/bold {Colors.PRIMARY}]",
                border_style=Colors.PRIMARY,
                padding=(0, 1),
            )
        else:
            table_panel = Panel(
                table,
                title=f"[bold {Colors.PRIMARY}]Thread Management[/bold {Colors.PRIMARY}]",
                border_style=Colors.PRIMARY,
                padding=(0, 1),
            )

        # Build choices with formatted display
        choices = []
        for thread in threads:
            summary = format_thread_summary(thread, current_thread_id)
            choices.append((thread["id"], summary))

        selected_id = await rich_prompt.select_async(
            question="Select a thread:",
            choices=choices,
            default=current_thread_id,
            context_panel=table_panel,
        )

        if not selected_id:
            return None, None

        # Step 2: Select action
        thread = next((t for t in threads if t["id"] == selected_id), None)
        if not thread:
            return None, None

        thread_name = thread.get("display_name") or thread.get("name") or "(unnamed)"
        short_id = selected_id[:8]

        console.print()
        console.print(f"[{COLORS['primary']}]✓ Selected: {escape(thread_name)} ({short_id})[/]")
        console.print()

        action_choices = [
            ("switch", "[Switch] Change to this thread"),
            ("delete", "[Delete] Remove this thread"),
            ("rename", "[Rename] Update thread name"),
            ("cancel", "[Cancel] Return without changes"),
        ]

        action = await rich_prompt.select_async(
            question="Choose an action:",
            choices=action_choices,
        )

        if not action or action == "cancel":
            console.print()
            return None, None

        return selected_id, action

    except asyncio.CancelledError:
        # Task cancelled - perform cleanup and propagate cancellation
        raise
    finally:
        # Guaranteed cleanup (currently no resources to clean up, but pattern consistency)
        pass


async def _confirm_thread_deletion(thread: dict, session_state, prompt_session) -> bool:
    """Show confirmation dialog for thread deletion.

    Args:
        thread: Thread metadata dict
        session_state: Current session state
        prompt_session: Main PromptSession for unified Application lifecycle

    Returns:
        True if user confirmed deletion, False otherwise
    """
    rich_prompt = RichPrompt(console, session_state, prompt_session)

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

    # Build details dict for confirmation
    details = {
        "Conversation History": f"{trace_count} traces",
        "Token Count": f"{token_display} tokens of context",
    }

    return await rich_prompt.dangerous_confirmation_async(
        action="Delete Thread",
        target=f"{thread_name} ({short_id})",
        details=details,
        confirmation_text="DELETE",
    )


async def _select_thread_interactively(
    threads, current_thread_id: str | None, session_state, prompt_session
) -> tuple[str, str] | tuple[None, None]:
    """Present an interactive picker to choose a thread and action.

    Args:
        threads: List of thread metadata dicts
        current_thread_id: ID of currently active thread
        session_state: Current session state
        prompt_session: Main PromptSession for unified Application lifecycle

    Returns:
        Tuple of (thread_id, action) where action is 'switch', 'delete', or 'rename'.
        Returns (None, None) if selection was cancelled.
    """
    if not threads:
        return None, None

    return await _select_thread_with_rich(threads, current_thread_id, session_state, prompt_session)


# Removed _select_thread_fallback - no longer needed after questionary migration


async def handle_thread_commands_async(
    args: str, thread_manager, agent, session_state, prompt_session
) -> bool:
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

        # Phase 1: Check server availability and enrich with server data (sync, blocking)
        server_available = check_server_availability()
        enriched_threads = [
            enrich_thread_with_server_data(t, server_available=server_available) for t in threads
        ]

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
            target_id, action = await _select_thread_interactively(
                enriched_threads, current_id, session_state, prompt_session
            )
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
                safe_name = escape(thread_name)  # Escape user input
                console.print()
                console.print(
                    f"[{COLORS['primary']}]✓ Switched to thread: {safe_name} ({short_id})[/{COLORS['primary']}]"
                )
                console.print()
            except ValueError as e:
                console.print()
                console.print(f"[red]Error: {e}[/red]")
                console.print()

        elif action == "delete":
            # Confirm deletion
            if not await _confirm_thread_deletion(thread, session_state, prompt_session):
                return True

            # Perform deletion
            try:
                thread_manager.delete_thread(target_id, agent)
                safe_name = escape(thread_name)  # Escape user input
                console.print()
                console.print(f"[green]✓ Deleted thread: {safe_name} ({short_id})[/green]")
                console.print()
            except ValueError as e:
                console.print()
                console.print(f"[red]Error: {e}[/red]")
                console.print()

        elif action == "rename":
            rich_prompt = RichPrompt(console, session_state, prompt_session)

            # Validator function
            def validate_name(text: str) -> bool | str:
                if len(text.strip()) == 0:
                    return "Thread name cannot be empty"
                return True

            new_name = await rich_prompt.text_input_async(
                prompt_text="Enter new thread name:",
                default=thread_name if thread_name != "(unnamed)" else "",
                validate=validate_name,
            )

            if not new_name or new_name.strip() == thread_name:
                console.print()
                console.print("[dim]✓ Rename cancelled.[/dim]")
                console.print()
                return True

            try:
                thread_manager.rename_thread(target_id, new_name.strip())
                safe_new_name = escape(new_name.strip())  # Escape user input
                console.print()
                console.print(
                    f"[{COLORS['primary']}]✓ Renamed thread to: {safe_new_name} [dim]({short_id})[/dim][/{COLORS['primary']}]"
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


async def handle_handoff_command(args: str, agent, session_state, prompt_session=None) -> bool:
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
        prompt_session=prompt_session,
    )

    # The execution loop handles approval UI and persistence when it detects handoff_approval_pending
    return True


async def handle_command(
    command: str,
    agent,
    token_tracker: TokenTracker,
    session_state=None,
    prompt_session=None,
) -> str | bool:
    """Handle slash commands. Returns 'exit' to exit, True if handled, False to pass to agent.

    Args:
        command: The slash command string
        agent: The compiled agent instance
        token_tracker: Token usage tracker
        session_state: Session state object
        prompt_session: Main PromptSession for unified Application lifecycle (required for /menu)
    """
    command = command.strip()
    if not command:
        return False

    # Extract command and args
    stripped = command.strip().lstrip("/")
    if not stripped:
        base_cmd = ""
        args = ""
    else:
        parts = stripped.split(maxsplit=1)
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

    if base_cmd in {"", "menu", "m"}:
        # Open main menu
        if not session_state:
            console.print()
            console.print("[red]Session state not available[/red]")
            console.print()
            return True

        from .cement_menu_system import CementMenuSystem

        # Pass prompt_session to avoid nested Application anti-pattern
        menu_system = CementMenuSystem(session_state, token_tracker, agent, prompt_session)
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

        return await handle_thread_commands_async(
            args, session_state.thread_manager, agent, session_state, prompt_session
        )

    if base_cmd == "handoff":
        return await handle_handoff_command(args, agent, session_state, prompt_session)

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
        console.print(f"$ {cmd}", style=COLORS["dim"], markup=False)

        # Execute the command
        result = subprocess.run(
            cmd, check=False, shell=True, capture_output=True, text=True, timeout=30, cwd=Path.cwd()
        )

        # Display output
        if result.stdout:
            console.print(result.stdout, style=COLORS["dim"], markup=False)
        if result.stderr:
            console.print(result.stderr, style=Colors.ERROR, markup=False)

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
        handle_error(e, context="bash command execution", fatal=False)
        return True
