"""Command handlers for slash commands and bash execution."""

import asyncio
import logging
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langsmith import Client
from requests.exceptions import HTTPError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import CompleteStyle

from deepagents.middleware.handoff_summarization import (
    MAX_REFINEMENT_ITERATIONS,
    HandoffSummary,
    generate_handoff_summary,
    select_messages_for_summary,
)

from .config import COLORS, console, get_banner_ascii
from .prompt_theme import build_thread_prompt_style
from .handoff_persistence import apply_handoff_acceptance
from .handoff_ui import HandoffDecision, HandoffProposal, prompt_handoff_decision
from .server_client import extract_first_user_message, extract_last_message_preview, get_thread_data
from .ui import TokenTracker, show_interactive_help

logger = logging.getLogger(__name__)

# Simple TTL cache (5 minutes)
_metrics_cache = {}
_cache_ttl = 300  # seconds

# Manual /handoff tuning
HANDOFF_DEFAULT_MESSAGE_LIMIT = 10
HANDOFF_MAX_MESSAGE_LIMIT = 50


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

    trace_count = thread.get("trace_count")
    tokens = thread.get("langsmith_tokens", 0)

    if trace_count is None:
        trace_display = "??"
    else:
        trace_display = str(trace_count)

    if tokens >= 1_000_000:
        token_display = f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        token_display = f"{tokens / 1_000:.1f}K"
    else:
        token_display = f"{tokens:,}"

    stats = f"{trace_display} traces · {token_display} tokens"
    current_suffix = " · current" if thread["id"] == current_thread_id else ""
    preview = thread.get("preview")

    if preview:
        return f"{short_id}  {display_name}  · {stats}  · {preview}  · {last_used}{current_suffix}"
    return f"{short_id}  {display_name}  · {stats}  · Last: {last_used}{current_suffix}"


def _print_thread_list(threads: list[dict], current_thread_id: str | None) -> None:
    """Display threads with index numbers for quick switching."""
    console.print()
    if not threads:
        console.print("[yellow]No threads available. Use /new to create one.[/yellow]")
        console.print()
        return

    console.print("[bold]Conversation Threads[/bold]")
    console.print()
    for idx, thread in enumerate(threads, start=1):
        prefix = "*" if thread["id"] == current_thread_id else " "
        summary = _format_thread_summary(thread, current_thread_id)
        console.print(f"{idx:>2}. {prefix} {summary}")
    console.print()
    console.print(
        "[dim]Commands: /threads switch <#|id>, rename <#|id> <name>, delete <#|id> --force, info <#|id>, list[/dim]"
    )
    console.print()


def _print_thread_info(thread: dict) -> None:
    """Render thread metadata details."""

    metadata = thread.get("metadata") or {}
    console.print()
    console.print(f"[bold]{thread.get('display_name') or thread.get('name') or '(unnamed)'}[/bold]")
    console.print(f"ID: {thread['id']}")
    console.print(f"Created: {thread.get('created')}")
    console.print(f"Last used: {thread.get('last_used')}")
    console.print(f"Parent: {thread.get('parent_id')}")
    console.print(f"Metadata: {metadata}")
    console.print()


def _resolve_thread_identifier(identifier: str, threads: list[dict]) -> dict | None:
    """Resolve a numeric index or id prefix to a thread dict."""
    if not identifier:
        return None

    if identifier.isdigit():
        idx = int(identifier)
        if 1 <= idx <= len(threads):
            return threads[idx - 1]

    for thread in threads:
        if thread["id"] == identifier:
            return thread

    matches = [thread for thread in threads if thread["id"].startswith(identifier)]
    if len(matches) == 1:
        return matches[0]

    return None
def _thread_toolbar() -> list[tuple[str, str]]:
    """Toolbar hint for the `/threads` selector."""

    return [
        ("class:threads-menu.hint-sep", "────────"),
        ("", " "),
        ("class:threads-menu.hint", "type number/id to filter"),
        ("", "  "),
        ("class:toolbar-green", "[Enter] switches"),
        ("", "  "),
        ("class:toolbar-orange", "[Esc] cancels"),
    ]


_THREAD_PROMPT_STYLE = build_thread_prompt_style()
_THREAD_PROMPT_SESSION = PromptSession(style=_THREAD_PROMPT_STYLE, bottom_toolbar=_thread_toolbar)


class _ThreadSelectionCompleter(Completer):
    """PromptToolkit completer that surfaces threads inline."""

    def __init__(self, threads: list[dict]):
        self.entries: list[dict] = []
        for idx, thread in enumerate(threads, start=1):
            name = thread.get("display_name") or thread.get("name") or "(unnamed)"
            preview_text = (thread.get("preview") or "No recent messages").replace("\n", " ")
            trace_count = thread.get("trace_count")
            trace_display = "?? traces" if trace_count is None else f"{trace_count} traces"
            tokens = thread.get("langsmith_tokens", 0)
            if tokens >= 1_000_000:
                token_display = f"{tokens / 1_000_000:.1f}M tokens"
            elif tokens >= 1_000:
                token_display = f"{tokens / 1_000:.1f}K tokens"
            else:
                token_display = f"{tokens:,} tokens"
            last_used = relative_time(thread.get("last_used", ""))
            display = FormattedText(
                [
                    ("class:threads-menu.index", f"{idx:02d}"),
                    ("", "  "),
                    ("class:threads-menu.name", name),
                    ("", " "),
                    ("class:threads-menu.id", f"[{thread['id'][:8]}]"),
                ]
            )
            meta_preview = preview_text[:70]
            meta = FormattedText(
                [
                    ("class:threads-menu.meta-header", meta_preview),
                    ("", "\n"),
                    (
                        "class:threads-menu.meta-footer",
                        f"{trace_display} · {token_display} · {last_used}",
                    ),
                ]
            )
            self.entries.append(
                {
                    "token": str(idx),
                    "display": display,
                    "meta": meta,
                    "search": f"{idx} {name.lower()} {thread['id']} {preview_text.lower()}",
                    "thread": thread,
                }
            )

    def get_completions(self, document, complete_event):  # type: ignore[override]
        text = document.text_before_cursor.strip().lower()
        for entry in self.entries:
            if text and text not in entry["search"]:
                continue
            yield Completion(
                entry["token"],
                start_position=-len(document.text_before_cursor),
                display=entry["display"],
                display_meta=entry["meta"],
            )


async def _run_threads_dashboard(thread_manager, agent, initial_threads=None) -> bool:
    """Leverage prompt_toolkit's default completion UI for thread selection."""

    unused_agent = agent  # keep signature compatibility
    threads = initial_threads or await _load_enriched_threads(thread_manager)
    if not threads:
        console.print("[yellow]No threads available. Use /new to create one.[/yellow]")
        console.print()
        return True

    if not (console.is_terminal and sys.stdin.isatty()):
        _print_thread_list(threads, thread_manager.get_current_thread_id())
        return True

    completer = _ThreadSelectionCompleter(threads)

    def _prompt() -> str:
        def pre_run() -> None:
            buffer = _THREAD_PROMPT_SESSION.app.current_buffer
            buffer.start_completion(select_first=True)

        message = FormattedText([("class:prompt", "/threads ")])

        return _THREAD_PROMPT_SESSION.prompt(
            message,
            completer=completer,
            complete_while_typing=True,
            complete_style=CompleteStyle.MULTI_COLUMN,
            reserve_space_for_menu=min(len(threads) + 4, 16),
            pre_run=pre_run,
        )

    try:
        selection = await asyncio.to_thread(_prompt)
    except (EOFError, KeyboardInterrupt):  # pragma: no cover - user cancelled
        console.print()
        return True

    selection = selection.strip()
    if not selection:
        console.print()
        return True

    target = None
    if selection.isdigit():
        idx = int(selection)
        if 1 <= idx <= len(threads):
            target = threads[idx - 1]
    if not target:
        target = _resolve_thread_identifier(selection, threads)

    if not target:
        console.print(f"[red]Thread '{selection}' not found.[/red]")
        console.print()
        return True

    thread_manager.switch_thread(target["id"])
    display_name = target.get("display_name") or target.get("name") or "(unnamed)"
    console.print()
    console.print(
        f"[{COLORS['primary']}]✓ Switched to thread: {display_name} ({target['id'][:8]})[/{COLORS['primary']}]"
    )
    console.print()
    return True

async def _load_enriched_threads(thread_manager) -> list[dict]:
    """Load threads with LangSmith metrics and server previews."""
    threads = thread_manager.list_threads()
    if not threads:
        return []

    enriched = [_enrich_thread_with_server_data(t) for t in threads]
    langsmith_client = get_langsmith_client()
    project_name = os.getenv("LANGCHAIN_PROJECT", "deepagents-cli")

    with ThreadPoolExecutor(max_workers=5) as executor:
        enriched = await _enrich_threads_with_metrics(
            enriched,
            langsmith_client,
            project_name,
            executor,
        )
    return enriched


async def handle_thread_commands_async(args: str, thread_manager, agent) -> bool:
    """Handle /threads commands without optional dependencies."""
    args = args.strip()
    parts = shlex.split(args) if args else []

    threads = await _load_enriched_threads(thread_manager)
    current_id = thread_manager.get_current_thread_id()

    if not parts:
        if console.is_terminal and sys.stdin.isatty():
            return await _run_threads_dashboard(thread_manager, agent, threads)
        _print_thread_list(threads, current_id)
        return True

    if parts[0].lower() == "list":
        _print_thread_list(threads, current_id)
        return True

    subcommand = parts[0].lower()
    operands = parts[1:]

    def require_target() -> dict | None:
        if not operands:
            console.print("[red]Provide a thread number or id.[/red]")
            console.print()
            return None
        target = _resolve_thread_identifier(operands[0], threads)
        if not target:
            console.print(f"[red]Thread '{operands[0]}' not found.[/red]")
            console.print()
            return None
        return target

    if subcommand == "switch":
        target = require_target()
        if not target:
            return True
        try:
            thread_manager.switch_thread(target["id"])
            display_name = target.get("display_name") or target.get("name") or "(unnamed)"
            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ Switched to thread: {display_name} ({target['id'][:8]})[/{COLORS['primary']}]"
            )
            console.print()
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            console.print()
        return True

    if subcommand == "rename":
        target = require_target()
        if not target:
            return True
        if len(operands) < 2:
            console.print("[red]Provide a new name after the thread id.[/red]")
            console.print()
            return True
        new_name = " ".join(operands[1:]).strip()
        if not new_name:
            console.print("[red]Thread name cannot be empty.[/red]")
            console.print()
            return True
        try:
            thread_manager.rename_thread(target["id"], new_name)
            console.print()
            console.print(
                f"[{COLORS['primary']}]✓ Renamed thread to: {new_name} ({target['id'][:8]})[/{COLORS['primary']}]"
            )
            console.print()
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            console.print()
        return True

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

    if subcommand == "info":
        target = require_target()
        if not target:
            return True
        _print_thread_info(target)
        return True

    console.print("[yellow]Unknown /threads subcommand.[/yellow]")
    console.print("[dim]Use /threads list to see available options.[/dim]")
    console.print()
    return True


def _coerce_message_limit(raw_value: str) -> int | None:
    """Normalize a --messages/-n argument into a bounded integer or None."""

    normalized = raw_value.strip().lower()
    if not normalized or normalized in {"all", "*", "max"}:
        return None

    limit = int(normalized)
    if limit <= 0:
        return None
    return min(limit, HANDOFF_MAX_MESSAGE_LIMIT)


def _parse_handoff_args(arg_string: str) -> tuple[bool, int | None]:
    """Return preview flag + window size extracted from /handoff args."""

    preview_only = False
    message_limit = HANDOFF_DEFAULT_MESSAGE_LIMIT
    if not arg_string:
        return preview_only, message_limit

    tokens = shlex.split(arg_string)
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token in {"--preview", "-p"}:
            preview_only = True
        elif token.startswith("--messages="):
            message_limit = _coerce_message_limit(token.split("=", 1)[1])
        elif token in {"--messages", "-n"}:
            idx += 1
            if idx >= len(tokens):
                msg = "Missing value for --messages"
                raise ValueError(msg)
            message_limit = _coerce_message_limit(tokens[idx])
        elif token in {"--help", "-h"}:
            msg = "Usage: /handoff [--preview] [--messages N]"
            raise ValueError(msg)
        else:
            msg = f"Unknown /handoff option: {token}"
            raise ValueError(msg)
        idx += 1
    return preview_only, message_limit


def _limit_messages_for_summary(
    messages: Sequence[BaseMessage],
    limit: int | None,
) -> list[BaseMessage]:
    """Return the most recent messages while keeping tool-call pairs intact."""

    window = list(messages)
    if limit is None or limit <= 0 or len(window) <= limit:
        return window

    start_index = len(window) - limit
    limited = list(window[start_index:])

    # Ensure we don't orphan a tool message that needs the preceding AI call.
    if limited and isinstance(limited[0], ToolMessage):
        preceding_index = start_index - 1
        if preceding_index >= 0 and isinstance(window[preceding_index], AIMessage):
            limited.insert(0, window[preceding_index])
    return limited


async def handle_handoff_command(args: str, agent, session_state) -> bool:
    """Manual `/handoff` entry point that summarizes and persists the thread.

    The CLI owns user-initiated handoffs while middleware (HandoffTool +
    HandoffSummarization + HandoffCleanup) continues to manage automatic
    lifecycle hooks. This handler gathers the recent messages, generates a
    summary with the configured model, prompts the user for approval, and
    persists the `<current_thread_summary>` block via existing helpers.
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

    try:
        preview_only, message_limit = _parse_handoff_args(args)
    except ValueError as exc:
        console.print()
        console.print(f"[red]{exc}[/red]")
        console.print("[dim]/handoff usage: /handoff [--preview] [--messages N][/dim]")
        console.print()
        return True

    model = getattr(session_state, "model", None)
    if model is None:
        console.print()
        console.print("[red]Model is not initialized yet; try again in a moment.[/red]")
        console.print()
        return True

    thread_manager = session_state.thread_manager
    thread_id = thread_manager.get_current_thread_id()
    assistant_id = getattr(thread_manager, "assistant_id", None) or "agent"

    console.print()
    window_text = "all recent" if not message_limit else f"last {message_limit}"
    console.print(
        f"[{COLORS['primary']}]Collecting {window_text} messages before handoff...[/]"
    )

    config = {"configurable": {"thread_id": thread_id}}
    if assistant_id:
        config["configurable"]["assistant_id"] = assistant_id

    try:
        state = await agent.aget_state(config)
    except Exception as exc:  # pragma: no cover - defensive guarantee
        console.print()
        console.print(f"[red]Unable to load conversation history: {exc}[/red]")
        console.print()
        return True

    state_values = getattr(state, "values", {}) or {}
    all_messages = list(state_values.get("messages") or [])
    if not all_messages:
        console.print()
        console.print("[yellow]No conversation history found to summarize.[/yellow]")
        console.print()
        return True

    selected = select_messages_for_summary(all_messages) or all_messages
    windowed = _limit_messages_for_summary(selected, message_limit)

    try:
        summary = generate_handoff_summary(
            model=model,
            messages=windowed,
            assistant_id=assistant_id,
            parent_thread_id=thread_id,
        )
    except Exception as exc:  # pragma: no cover - surfaced to the CLI
        console.print()
        console.print(f"[red]Failed to generate handoff summary: {exc}[/red]")
        console.print()
        return True

    current_summary = summary
    proposal = HandoffProposal(
        handoff_id=current_summary.handoff_id,
        summary_json=dict(current_summary.summary_json),
        summary_md=current_summary.summary_md,
        parent_thread_id=thread_id,
        assistant_id=assistant_id,
    )

    iteration = 0
    while True:
        decision = await prompt_handoff_decision(proposal, preview_only=preview_only)

        if decision.status == "preview":
            return True

        if decision.status == "declined":
            console.print("[dim]Handoff cancelled per user request.[/dim]")
            console.print()
            return True

        if decision.status != "refine":
            break

        feedback = (decision.feedback or "").strip()
        if not feedback:
            console.print(
                "[yellow]Feedback was empty; keeping the current summary.[/yellow]"
            )
            continue

        next_iteration = iteration + 1
        if next_iteration >= MAX_REFINEMENT_ITERATIONS:
            console.print()
            console.print(
                f"[yellow]Reached refinement limit ({MAX_REFINEMENT_ITERATIONS}). "
                "Using the latest summary as-is.[/yellow]"
            )
            console.print()
            decision = HandoffDecision(
                status="accepted",
                summary_md=proposal.summary_md,
                summary_json=proposal.summary_json,
            )
            break

        iteration = next_iteration
        console.print()
        console.print(
            f"[{COLORS['primary']}]Refining summary (iteration {iteration})...[/]"
        )

        try:
            refined_summary = generate_handoff_summary(
                model=model,
                messages=windowed,
                assistant_id=assistant_id,
                parent_thread_id=thread_id,
                feedback=feedback,
                previous_summary_md=proposal.summary_md,
                iteration=iteration,
            )
        except Exception as exc:  # pragma: no cover - surfaced to CLI
            console.print()
            console.print(f"[red]Failed to refine handoff summary: {exc}[/red]")
            console.print()
            return True

        current_summary = refined_summary
        proposal = HandoffProposal(
            handoff_id=current_summary.handoff_id,
            summary_json=dict(current_summary.summary_json),
            summary_md=current_summary.summary_md,
            parent_thread_id=thread_id,
            assistant_id=assistant_id,
        )

    final_summary_json = dict(decision.summary_json or current_summary.summary_json)
    final_summary_json["handoff_id"] = current_summary.handoff_id
    final_summary_md = decision.summary_md or current_summary.summary_md
    prepared_summary = HandoffSummary(
        handoff_id=current_summary.handoff_id,
        summary_json=final_summary_json,
        summary_md=final_summary_md,
    )

    try:
        child_id = apply_handoff_acceptance(
            session_state=session_state,
            summary=prepared_summary,
            summary_md=final_summary_md,
            summary_json=final_summary_json,
            parent_thread_id=thread_id,
        )
    except Exception as exc:  # pragma: no cover - surfaced to CLI
        console.print()
        console.print(f"[red]Failed to persist handoff summary: {exc}[/red]")
        console.print()
        return True

    try:
        thread_manager.switch_thread(child_id)
        console.print()
        console.print(
            f"[green]✓ Handoff recorded. Switched to new thread: {child_id[:8]}[/green]"
        )
        console.print()
    except ValueError as exc:
        console.print()
        console.print(
            f"[yellow]Summary saved, but thread switch failed: {exc}[/yellow]"
        )
        console.print()

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
            console.print(
                get_banner_ascii(getattr(session_state, "banner_variant", None)),
                style=f"bold {COLORS['primary']}",
            )
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
            console.print(
                get_banner_ascii(getattr(session_state, "banner_variant", None) if session_state else None),
                style=f"bold {COLORS['primary']}",
            )
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
