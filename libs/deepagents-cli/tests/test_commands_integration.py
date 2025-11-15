"""Integration tests for slash command handling.

Tests exercise the full command routing through handle_command() to ensure
all canonical commands work correctly without requiring a LangGraph server.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deepagents_cli.commands import handle_command
from deepagents_cli.config import SessionState
from deepagents_cli.ui import TokenTracker


@pytest.fixture
def mock_thread_manager():
    """Lightweight mock ThreadManager with proper return structures."""
    mock = MagicMock()
    mock.get_current_thread_id.return_value = "thread-abc123"
    mock.list_threads.return_value = []
    mock.create_thread.return_value = "thread-new456"

    # Stub get_thread_metadata to return proper dict structure
    mock.get_thread_metadata.return_value = {
        "id": "thread-new456",
        "name": "New conversation",
        "created": "2025-01-11T10:00:00Z",
        "last_used": "2025-01-11T10:00:00Z",
    }

    return mock


@pytest.fixture
def session_state(mock_thread_manager):
    """Real SessionState with mocked ThreadManager."""
    return SessionState(auto_approve=False, thread_manager=mock_thread_manager)


@pytest.fixture
def token_tracker(monkeypatch):
    """Real TokenTracker with spied display_session method."""
    tracker = TokenTracker()
    tracker.set_baseline(5000)

    # Spy pattern - wraps real method while tracking calls
    spy = MagicMock(wraps=tracker.display_session)
    monkeypatch.setattr(tracker, "display_session", spy)

    return tracker


def run_command(command: str, session_state, token_tracker, agent=None):
    """Helper to run the async handle_command coroutine."""

    return asyncio.run(handle_command(command, agent, token_tracker, session_state))


# ============================================================================
# Core Command Routing Tests
# ============================================================================


@pytest.mark.parametrize("command", ["/quit", "/exit", "/q"])
def test_quit_commands_return_exit_sentinel(command, session_state, token_tracker):
    """Test all quit variants return 'exit' string."""
    result = run_command(command, session_state, token_tracker)
    assert result == "exit"


@patch("deepagents_cli.commands.console.print")
def test_help_command_displays_and_returns_true(mock_print, session_state, token_tracker):
    """Test /help displays help and returns True."""
    result = run_command("/help", session_state, token_tracker)

    assert result is True
    mock_print.assert_called()  # Verify help was displayed


def test_tokens_command_calls_display_session(session_state, token_tracker):
    """Test /tokens invokes TokenTracker.display_session()."""
    result = run_command("/tokens", session_state, token_tracker)

    assert result is True
    # Spy pattern allows direct assertion
    token_tracker.display_session.assert_called_once()


@patch("deepagents_cli.commands.console.print")
def test_unknown_command_shows_warning(mock_print, session_state, token_tracker):
    """Test unknown command shows warning and returns True."""
    result = run_command("/foobar", session_state, token_tracker)

    assert result is True

    # Robust assertion checking Rich output
    assert any(
        "unknown command" in (args[0].lower() if args else "")
        for args, _ in mock_print.call_args_list
    )


# ============================================================================
# Thread Management Tests
# ============================================================================


@patch("deepagents_cli.commands.console.print")
def test_new_command_with_name(mock_print, session_state, token_tracker):
    """Test /new with name creates thread with that name."""
    result = run_command("/new My Project", session_state, token_tracker)

    assert result is True
    session_state.thread_manager.create_thread.assert_called_once_with(name="My Project")


@patch("deepagents_cli.commands.console.print")
def test_new_command_without_name(mock_print, session_state, token_tracker):
    """Test /new without name creates thread with name=None."""
    result = run_command("/new", session_state, token_tracker)

    assert result is True
    session_state.thread_manager.create_thread.assert_called_once_with(name=None)


@patch("deepagents_cli.commands.console.print")
def test_threads_with_args_shows_unknown_message(mock_print, session_state, token_tracker):
    """Test /threads with unsupported subcommand shows helpful warning."""
    result = run_command("/threads continue abc123", session_state, token_tracker)

    assert result is True
    assert any(
        "unknown /threads" in (args[0].lower() if args else "")
        for args, _ in mock_print.call_args_list
    )


@patch("deepagents_cli.commands.sys.stdin.isatty", return_value=True)
@patch("deepagents_cli.commands._run_threads_dashboard", new_callable=AsyncMock)
def test_threads_uses_dashboard_when_tty(mock_dashboard, mock_isatty, session_state, token_tracker, monkeypatch):
    """Test /threads invokes the Rich dashboard when running in a TTY."""
    mock_console = MagicMock()
    mock_console.is_terminal = True
    mock_console.print = MagicMock()
    mock_console.clear = MagicMock()
    mock_console.input = MagicMock(return_value="")
    monkeypatch.setattr("deepagents_cli.commands.console", mock_console, raising=False)
    mock_dashboard.return_value = True

    session_state.thread_manager.list_threads.return_value = [
        {"id": "thread-111", "name": "First", "last_used": "2025-01-11T10:00:00Z"}
    ]

    result = run_command("/threads", session_state, token_tracker)

    assert result is True
    mock_dashboard.assert_awaited_once()


@patch("deepagents_cli.commands._print_thread_list")
@patch("deepagents_cli.commands._run_threads_dashboard", new_callable=AsyncMock)
def test_threads_falls_back_without_tty(mock_dashboard, mock_print_list, session_state, token_tracker, monkeypatch):
    """Test /threads prints a static list when no interactive terminal is available."""
    mock_console = MagicMock()
    mock_console.is_terminal = False
    mock_console.print = MagicMock()
    monkeypatch.setattr("deepagents_cli.commands.console", mock_console, raising=False)
    monkeypatch.setattr("deepagents_cli.commands.sys.stdin.isatty", lambda: False, raising=False)

    session_state.thread_manager.list_threads.return_value = [
        {"id": "thread-111", "name": "First", "last_used": "2025-01-11T10:00:00Z"}
    ]

    result = run_command("/threads", session_state, token_tracker)

    assert result is True
    mock_dashboard.assert_not_called()
    mock_print_list.assert_called_once()


# ============================================================================
# Graceful Failure Tests
# ============================================================================


@patch("deepagents_cli.commands.console.clear")
@patch("deepagents_cli.commands.console.print")
def test_clear_without_thread_manager_shows_warning(mock_print, mock_clear, token_tracker):
    """Test /clear without thread manager shows warning but still resets tracker."""
    session_state_no_manager = SessionState(auto_approve=False, thread_manager=None)

    result = run_command("/clear", session_state_no_manager, token_tracker)

    assert result is True

    # Verify warning shown
    assert any(
        "thread manager not available" in (args[0].lower() if args else "")
        for args, _ in mock_print.call_args_list
    )

    # Verify token tracker still reset
    assert token_tracker.current_context == token_tracker.baseline_context

    # Verify screen still cleared
    mock_clear.assert_called_once()


@patch("deepagents_cli.commands.console.clear")
@patch("deepagents_cli.commands.console.print")
def test_clear_with_thread_manager_creates_new_thread(
    mock_print, mock_clear, session_state, token_tracker
):
    """Test /clear creates new thread and resets token tracker."""
    result = run_command("/clear", session_state, token_tracker)

    assert result is True

    # Critical assertions from feedback
    session_state.thread_manager.create_thread.assert_called_once_with(name="New conversation")
    mock_clear.assert_called_once()

    # Verify token tracker was reset
    assert token_tracker.current_context == token_tracker.baseline_context


# ============================================================================
# LangSmith Metrics Format Tests
# ============================================================================


def test_format_thread_summary_with_metrics():
    """Test _format_thread_summary() with LangSmith metrics."""
    from deepagents_cli.commands import _format_thread_summary

    thread = {
        "id": "abc123def456",
        "display_name": "Test Thread",
        "trace_count": 42,
        "langsmith_tokens": 15234,
        "preview": "Some preview text",
        "last_used": "2025-01-15T10:00:00Z",
    }

    summary = _format_thread_summary(thread, None)

    assert "abc123de" in summary  # Short ID
    assert "Test Thread" in summary
    assert "42 traces" in summary
    assert "15.2K tokens" in summary  # K abbreviation
    assert "Some preview text" in summary


def test_format_thread_summary_error_state():
    """Test _format_thread_summary() shows ?? when LangSmith unavailable."""
    from deepagents_cli.commands import _format_thread_summary

    thread = {
        "id": "abc123def456",
        "display_name": "Test Thread",
        "trace_count": None,  # Error state
        "langsmith_tokens": 5000,
        "preview": "Some preview text",
        "last_used": "2025-01-15T10:00:00Z",
    }

    summary = _format_thread_summary(thread, None)

    assert "?? traces" in summary  # Error indicator
    assert "5.0K tokens" in summary  # K abbreviation for 5000


def test_format_thread_summary_zero_traces():
    """Test _format_thread_summary() with zero traces."""
    from deepagents_cli.commands import _format_thread_summary

    thread = {
        "id": "abc123def456",
        "display_name": "Empty Thread",
        "trace_count": 0,  # Zero is valid (new thread)
        "langsmith_tokens": 100,
        "preview": None,
        "last_used": "2025-01-15T10:00:00Z",
    }

    summary = _format_thread_summary(thread, None)

    assert "0 traces" in summary  # Shows 0, not ??
    assert "100 tokens" in summary  # No abbreviation


def test_format_thread_summary_large_numbers():
    """Test _format_thread_summary() formats large token counts."""
    from deepagents_cli.commands import _format_thread_summary

    thread = {
        "id": "abc123def456",
        "display_name": "Large Thread",
        "trace_count": 150,
        "langsmith_tokens": 2_500_000,  # 2.5M
        "preview": None,
        "last_used": "2025-01-15T10:00:00Z",
    }

    summary = _format_thread_summary(thread, None)

    assert "150 traces" in summary
    assert "2.5M tokens" in summary  # M abbreviation
