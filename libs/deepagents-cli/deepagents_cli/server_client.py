"""Client for LangGraph dev server API."""

from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import tempfile
import time
from typing import Any

import requests

from .config import SERVER_REQUEST_TIMEOUT


_STARTED_SERVER_PROCESS: subprocess.Popen[bytes] | None = None
_CLEANUP_REGISTERED = False


def _register_server_cleanup(process: subprocess.Popen[bytes]) -> None:
    """Register an atexit handler to terminate the spawned dev server."""

    global _STARTED_SERVER_PROCESS, _CLEANUP_REGISTERED
    _STARTED_SERVER_PROCESS = process

    if not _CLEANUP_REGISTERED:
        atexit.register(_cleanup_started_server)
        _CLEANUP_REGISTERED = True


def _cleanup_started_server() -> None:
    """Terminate the LangGraph dev server started by the CLI."""

    global _STARTED_SERVER_PROCESS

    process = _STARTED_SERVER_PROCESS
    if process is None:
        return

    if process.poll() is None:
        try:
            if hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGTERM)
            else:  # pragma: no cover - platform specific
                process.terminate()
            process.wait(timeout=5)
        except Exception:  # pragma: no cover - defensive cleanup
            try:
                process.kill()
            except Exception:
                pass

    _STARTED_SERVER_PROCESS = None


def _request(
    method: str,
    path: str,
    *,
    server_url: str | None = None,
    timeout: float | None = None,
    json: Any | None = None,
) -> requests.Response:
    """Internal helper for LangGraph requests with consistent handling."""

    url = f"{server_url or get_server_url()}{path}"
    timeout = timeout or SERVER_REQUEST_TIMEOUT

    try:
        response = requests.request(method, url, timeout=timeout, json=json)
        response.raise_for_status()
        return response
    except requests.Timeout as exc:
        raise LangGraphTimeoutError(f"Timed out talking to LangGraph at {url}") from exc
    except requests.RequestException as exc:  # pragma: no cover - network errors
        raise LangGraphRequestError(str(exc)) from exc


class LangGraphError(RuntimeError):
    """Base error for LangGraph client."""


class LangGraphTimeoutError(LangGraphError):
    """Raised when requests to LangGraph time out."""


class LangGraphRequestError(LangGraphError):
    """Raised for non-timeout request failures."""


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
        response = _request("GET", f"/threads/{thread_id}/state", server_url=server_url)
        return response.json()
    except LangGraphError:
        return None


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
            if isinstance(content, str):
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
        response = requests.get(
            f"{server_url or get_server_url()}/ok", timeout=min(1.0, SERVER_REQUEST_TIMEOUT)
        )
        return response.status_code == 200
    except requests.RequestException:
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
    payload: dict[str, Any] = {}
    merged_metadata = dict(metadata or {})
    if name and "name" not in merged_metadata:
        merged_metadata["name"] = name
    if merged_metadata:
        payload["metadata"] = merged_metadata

    response = _request("POST", "/threads", server_url=server_url, json=payload)
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
    response = _request("POST", f"/threads/{thread_id}/copy", server_url=server_url, json={})
    return response.json()["thread_id"]


def delete_thread_on_server(thread_id: str, server_url: str | None = None) -> None:
    """Delete a thread on LangGraph server.

    Deletes the thread and all associated checkpoints via the server API.
    Deletion cascades automatically on the server side.

    If the thread doesn't exist (404), this is treated as success since the
    desired end state (thread not existing) is achieved.

    Args:
        thread_id: Thread ID to delete
        server_url: Optional server URL, defaults to get_server_url()

    Raises:
        LangGraphError: If server request fails or times out (except 404)
    """
    url = f"{server_url or get_server_url()}/threads/{thread_id}"
    timeout = SERVER_REQUEST_TIMEOUT

    try:
        response = requests.delete(url, timeout=timeout)
        # 204 No Content = success
        # 404 Not Found = thread doesn't exist, which is the desired state
        if response.status_code in (204, 404):
            return
        response.raise_for_status()
    except requests.Timeout as exc:
        raise LangGraphTimeoutError(f"Timed out talking to LangGraph at {url}") from exc
    except requests.RequestException as exc:  # pragma: no cover - network errors
        raise LangGraphRequestError(str(exc)) from exc


def start_server_if_needed() -> tuple[bool, str | None]:
    """Start LangGraph dev server if not already running.

    Attempts to start 'langgraph dev' in the background and waits
    for it to become available.

    Returns:
        Tuple of (success flag, error message or None)
    """
    # Check if already running
    if is_server_available():
        return True, None

    # Check for port conflicts before starting
    try:
        with socket.create_connection(("127.0.0.1", 2024), timeout=1):  # type: ignore[arg-type]
            return False, "Port 2024 is already in use by another process"
    except OSError:
        pass

    # Try to start server
    try:
        log_file = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".log")

        process = subprocess.Popen(  # noqa: S603
            ["langgraph", "dev"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

        _register_server_cleanup(process)

        timeout_seconds = max(10, int(SERVER_REQUEST_TIMEOUT * 3))
        attempts = int(timeout_seconds / 0.5)

        for _ in range(attempts):
            time.sleep(0.5)
            if is_server_available():
                log_file.close()
                return True, None
            if process.poll() is not None:
                _STARTED_SERVER_PROCESS = None
                log_file.seek(0)
                error_output = log_file.read().strip()
                log_file.close()
                error_msg = error_output or "LangGraph server exited unexpectedly"
                return False, error_msg[:500]

        log_file.close()
        _cleanup_started_server()
        return False, f"LangGraph server did not respond within {timeout_seconds}s"
    except FileNotFoundError:
        return False, "'langgraph' command not found. Install with: pip install langgraph-cli"
    except Exception as exc:  # pragma: no cover - defensive
        _cleanup_started_server()
        return False, f"Failed to start LangGraph server: {exc}"
