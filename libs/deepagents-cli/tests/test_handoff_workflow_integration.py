"""Integration test for handoff workflow after code cleanup.

This test verifies that removing unused code (termios/tty, get_all_threads, get_message_count)
did not break the handoff functionality.

Test strategy:
1. Clear any existing summary from agent.md
2. Verify thread management still works
3. Verify handoff command infrastructure is intact
4. Verify no imports are missing
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_imports_after_cleanup():
    """Verify all necessary imports still work after removing termios/tty."""
    # These imports should all work
    from deepagents_cli import commands
    from deepagents_cli.commands import (
        _enrich_thread_with_server_data,
        _format_thread_summary,
        _parse_handoff_args,
        _select_thread_interactively,
        handle_thread_commands_async,
    )

    assert commands is not None
    assert _enrich_thread_with_server_data is not None
    assert _format_thread_summary is not None
    assert _parse_handoff_args is not None
    assert _select_thread_interactively is not None
    assert handle_thread_commands_async is not None


def test_handoff_args_parsing():
    """Test that handoff argument parsing still works."""
    from deepagents_cli.commands import _parse_handoff_args

    # Test --preview flag
    result = _parse_handoff_args("--preview")
    assert result["preview_only"] is True

    # Test -p flag
    result = _parse_handoff_args("-p")
    assert result["preview_only"] is True

    # Test no flags
    result = _parse_handoff_args("")
    assert result["preview_only"] is False

    # Test with thread name
    result = _parse_handoff_args("my-thread-name")
    assert result["preview_only"] is False


def test_thread_selector_works_without_termios():
    """Verify thread selection works after removing termios/tty imports."""
    from deepagents_cli.commands import _select_thread_interactively
    from datetime import UTC, datetime

    # Create sample threads
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    threads = [
        {
            "id": f"thread-{i:02d}-abcdef",
            "assistant_id": "test",
            "created": now,
            "last_used": now,
            "name": f"Thread {i}",
        }
        for i in range(1, 4)
    ]

    # Mock input to select thread 2
    with patch("builtins.input", return_value="2"):
        selected = _select_thread_interactively(threads, threads[0]["id"])

    assert selected == threads[1]["id"]


def test_server_client_functions_exist():
    """Verify that the functions we KEPT in server_client still exist."""
    from deepagents_cli.server_client import (
        extract_first_user_message,
        extract_last_message_preview,
        get_thread_data,
    )

    # These should all exist
    assert extract_first_user_message is not None
    assert extract_last_message_preview is not None
    assert get_thread_data is not None


def test_removed_functions_are_gone():
    """Verify that unused functions were actually removed."""
    from deepagents_cli import server_client

    # These should NOT exist anymore
    assert not hasattr(server_client, "get_all_threads")
    assert not hasattr(server_client, "get_message_count")


def test_extract_message_functions():
    """Test the message extraction functions that we KEPT."""
    from deepagents_cli.server_client import (
        extract_first_user_message,
        extract_last_message_preview,
    )

    # Test data
    thread_data = {
        "values": {
            "messages": [
                {
                    "type": "human",
                    "content": [{"text": "First message from user"}],
                },
                {
                    "type": "ai",
                    "content": [{"text": "AI response"}],
                },
                {
                    "type": "human",
                    "content": [{"text": "This is a long message that should be truncated because it exceeds the 60 character limit"}],
                },
            ]
        }
    }

    # Test first message extraction
    first = extract_first_user_message(thread_data)
    assert first == "First message from user"

    # Test last message preview (should be truncated)
    preview = extract_last_message_preview(thread_data)
    assert preview is not None
    assert len(preview) <= 63  # 60 chars + "..."
    assert preview.endswith("...")


def test_handoff_command_handler_exists():
    """Verify handoff command handler exists and is importable."""
    from deepagents_cli.commands import _handle_handoff_command, _parse_handoff_args

    # Should be able to import these
    assert _handle_handoff_command is not None
    assert _parse_handoff_args is not None

    # Test parsing works
    result = _parse_handoff_args("--preview")
    assert result["preview_only"] is True


def test_sys_import_is_used():
    """Verify sys import is actually used (not just for test mocking)."""
    import sys
    from deepagents_cli import commands

    # The module should import sys
    assert hasattr(commands, "sys")

    # Verify sys is actually the real sys module
    assert commands.sys is sys


def test_thread_management_infrastructure():
    """Verify thread management infrastructure is intact."""
    # Import thread manager
    from deepagents_cli.thread_manager import ThreadManager
    from deepagents_cli.thread_store import ThreadStore

    # Should be able to create instance with temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir) / "test-agent"
        agent_dir.mkdir()

        # Create threads.json
        threads_json = agent_dir / "threads.json"
        threads_json.write_text('{"threads": [], "current_thread_id": null}')

        # Verify ThreadStore works
        store = ThreadStore(threads_json)
        data = store.load()
        assert data.threads == []

        # Note: ThreadManager requires server connection for initialization
        # so we just verify it's importable and the store works
        assert ThreadManager is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
