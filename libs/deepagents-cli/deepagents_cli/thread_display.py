"""Shared helpers for formatting thread metadata for CLI menus."""

from __future__ import annotations

from datetime import UTC, datetime

from .server_client import (
    extract_first_user_message,
    extract_last_message_preview,
    get_thread_data,
    is_server_available,
)

__all__ = [
    "check_server_availability",
    "enrich_thread_with_server_data",
    "format_thread_summary",
    "relative_time",
]


def relative_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to relative time string."""
    if not iso_timestamp:
        return "unknown"

    try:
        trimmed = iso_timestamp.rstrip("Z")
        timestamp = datetime.fromisoformat(trimmed)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)

        delta = datetime.now(UTC) - timestamp
        seconds = int(delta.total_seconds())

        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except Exception:
        return iso_timestamp


def check_server_availability() -> bool:
    """Check if LangGraph server is available for thread data enrichment.

    Returns:
        True if server is available, False otherwise
    """
    return is_server_available()


def enrich_thread_with_server_data(thread: dict, *, server_available: bool | None = None) -> dict:
    """Populate display fields (name, preview) using server data when available.

    Args:
        thread: Thread metadata dictionary
        server_available: Optional pre-checked server availability status.
            If None, will check server for each thread (slower).
            If provided, skips check and uses cached availability.

    Returns:
        Thread dictionary with enriched display fields
    """
    # Use provided availability or check for this thread
    should_fetch_data = server_available if server_available is not None else is_server_available()

    if should_fetch_data:
        thread_data = get_thread_data(thread["id"])
        if thread_data:
            if not thread.get("name") or thread.get("name") == "(unnamed)":
                first_msg = extract_first_user_message(thread_data)
                thread["display_name"] = first_msg or "(unnamed)"
            else:
                thread["display_name"] = thread["name"]

            preview = extract_last_message_preview(thread_data)
            if preview:
                thread["preview"] = preview
        else:
            # Server said it was available but data fetch failed - fallback
            thread["display_name"] = thread.get("name") or "(unnamed)"
    else:
        # Server not available - use cached data only
        thread["display_name"] = thread.get("name") or "(unnamed)"

    return thread


def format_thread_summary(thread: dict, current_thread_id: str | None) -> str:
    """Build a single-line summary matching LangSmith UI format."""
    display_name = thread.get("display_name") or thread.get("name") or "(unnamed)"
    short_id = thread["id"][:8]
    last_used = relative_time(thread.get("last_used", ""))

    trace_count = thread.get("trace_count")
    if trace_count is None:
        trace_count = thread.get("message_count")
    if trace_count is None:
        trace_count = 0

    tokens = thread.get("langsmith_tokens")
    if tokens is None:
        tokens = thread.get("total_tokens") or thread.get("token_count") or 0

    if tokens >= 1_000_000:
        token_display = f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        token_display = f"{tokens / 1_000:.1f}K"
    else:
        token_display = f"{tokens:,}"

    stats = f"{trace_count} traces · {token_display} tokens"

    current_suffix = " · current" if thread["id"] == current_thread_id else ""

    preview = thread.get("preview")
    if preview:
        return f"{short_id}  {display_name}  · {stats}  · {preview}  · {last_used}{current_suffix}"
    return f"{short_id}  {display_name}  · {stats}  · Last: {last_used}{current_suffix}"
