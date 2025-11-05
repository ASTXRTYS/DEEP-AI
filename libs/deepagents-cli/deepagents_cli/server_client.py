"""Client for LangGraph dev server API."""

import os
import subprocess
import time
from typing import Any

import requests


def get_thread_data(
    thread_id: str, server_url: str = "http://127.0.0.1:2024"
) -> dict[str, Any] | None:
    """Get thread data from LangGraph server API.

    Args:
        thread_id: The thread ID to fetch
        server_url: The LangGraph server URL

    Returns:
        Thread data including messages, or None if server unavailable/error
    """
    try:
        response = requests.get(f"{server_url}/threads/{thread_id}/state", timeout=2)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def get_all_threads(server_url: str = "http://127.0.0.1:2024") -> list[dict[str, Any]]:
    """Get all threads from LangGraph server API.

    Args:
        server_url: The LangGraph server URL

    Returns:
        List of thread data, or empty list if server unavailable
    """
    try:
        response = requests.post(f"{server_url}/threads/search", json={}, timeout=2)
        response.raise_for_status()
        return response.json()
    except Exception:
        return []


def extract_first_user_message(thread_data: dict[str, Any]) -> str | None:
    """Extract the first user message from thread data.

    Args:
        thread_data: Thread data from server API

    Returns:
        First user message content, or None if not found
    """
    messages = thread_data.get("values", {}).get("messages", [])

    for msg in messages:
        if msg.get("type") == "human":
            content = msg.get("content", [])
            if isinstance(content, list) and content:
                text = content[0].get("text", "")
                # Truncate to first 50 chars for use as name
                return text[:50] if text else None
            elif isinstance(content, str):
                return content[:50] if content else None

    return None


def extract_last_message_preview(thread_data: dict[str, Any]) -> str | None:
    """Extract a preview of the last message from thread data.

    Args:
        thread_data: Thread data from server API

    Returns:
        Last message preview (truncated), or None if not found
    """
    messages = thread_data.get("values", {}).get("messages", [])

    if not messages:
        return None

    last_msg = messages[-1]
    content = last_msg.get("content", [])

    if isinstance(content, list) and content:
        text = content[0].get("text", "")
        # Truncate to 60 chars for preview
        if text:
            return (text[:60] + "...") if len(text) > 60 else text
    elif isinstance(content, str):
        return (content[:60] + "...") if len(content) > 60 else content

    return None


def get_message_count(thread_data: dict[str, Any]) -> int:
    """Get the count of messages in a thread.

    Args:
        thread_data: Thread data from server API

    Returns:
        Number of messages
    """
    messages = thread_data.get("values", {}).get("messages", [])
    return len(messages)


def get_server_url() -> str:
    """Get LangGraph server URL from environment or use default."""
    return os.getenv("LANGGRAPH_SERVER_URL", "http://127.0.0.1:2024")


def is_server_available(server_url: str | None = None) -> bool:
    """Check if LangGraph server is running.

    Args:
        server_url: Optional server URL, defaults to get_server_url()

    Returns:
        True if server is available, False otherwise
    """
    try:
        response = requests.get(f"{server_url or get_server_url()}/ok", timeout=1)
        return response.status_code == 200
    except Exception:
        return False


def create_thread_on_server(
    name: str | None = None, metadata: dict[str, Any] | None = None, server_url: str | None = None
) -> str:
    """Create a new thread on LangGraph server.

    Args:
        name: Optional thread name
        metadata: Optional metadata dict
        server_url: Optional server URL, defaults to get_server_url()

    Returns:
        Server-generated thread_id

    Raises:
        requests.HTTPError: If server returns error
        requests.Timeout: If request times out
    """
    payload = {}
    if metadata:
        payload["metadata"] = metadata
    elif name:
        payload["metadata"] = {"name": name}

    response = requests.post(f"{server_url or get_server_url()}/threads", json=payload, timeout=2)
    response.raise_for_status()
    return response.json()["thread_id"]


def fork_thread_on_server(thread_id: str, server_url: str | None = None) -> str:
    """Fork an existing thread on LangGraph server.

    Args:
        thread_id: Thread ID to fork
        server_url: Optional server URL, defaults to get_server_url()

    Returns:
        New thread_id of the forked thread

    Raises:
        requests.HTTPError: If server returns error
        requests.Timeout: If request times out
    """
    response = requests.post(
        f"{server_url or get_server_url()}/threads/{thread_id}/copy", json={}, timeout=2
    )
    response.raise_for_status()
    return response.json()["thread_id"]


def start_server_if_needed() -> bool:
    """Start LangGraph dev server if not already running.

    Attempts to start 'langgraph dev' in the background and waits
    for it to become available.

    Returns:
        True if server is running (already was or successfully started),
        False if failed to start
    """
    # Check if already running
    if is_server_available():
        return True

    # Try to start server
    try:
        # Start langgraph dev in background, suppressing output
        subprocess.Popen(
            ["langgraph", "dev"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent process
        )

        # Wait up to 10 seconds for server to start
        for _ in range(20):
            time.sleep(0.5)
            if is_server_available():
                return True

        return False
    except Exception:
        return False
