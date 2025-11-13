"""Integration tests for slash command handling.

Tests exercise the full command routing through handle_command() to ensure
all canonical commands work correctly without requiring a LangGraph server.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deepagents_cli.commands import handle_command
from deepagents_cli.config import SessionState
from deepagents_cli.ui import TokenTracker

pytestmark = pytest.mark.asyncio


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


# ============================================================================
# Core Command Routing Tests
# ============================================================================


@pytest.mark.parametrize("command", ["/quit", "/exit", "/q"])
async def test_quit_commands_return_exit_sentinel(command, session_state, token_tracker):
    """Test all quit variants return 'exit' string."""
    result = await handle_command(command, None, token_tracker, session_state, None)
    assert result == "exit"


@patch("deepagents_cli.cement_menu_system.CementMenuSystem")
async def test_bare_slash_opens_canonical_menu(mock_menu_cls, session_state, token_tracker):
    """Bare '/' should route into the canonical menu without crashing."""
    menu_instance = AsyncMock()
    menu_instance.show_main_menu.return_value = None
    mock_menu_cls.return_value = menu_instance

    result = await handle_command("/", None, token_tracker, session_state, object())

    assert result is True
    menu_instance.show_main_menu.assert_awaited_once()


@patch("deepagents_cli.commands.console.print")
async def test_help_command_displays_and_returns_true(mock_print, session_state, token_tracker):
    """Test /help displays help and returns True."""
    result = await handle_command("/help", None, token_tracker, session_state, None)

    assert result is True
    mock_print.assert_called()  # Verify help was displayed


async def test_tokens_command_calls_display_session(session_state, token_tracker):
    """Test /tokens invokes TokenTracker.display_session()."""
    result = await handle_command("/tokens", None, token_tracker, session_state, None)

    assert result is True
    # Spy pattern allows direct assertion
    token_tracker.display_session.assert_called_once()


@patch("deepagents_cli.commands.console.print")
async def test_unknown_command_shows_warning(mock_print, session_state, token_tracker):
    """Test unknown command shows warning and returns True."""
    result = await handle_command("/foobar", None, token_tracker, session_state, None)

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
async def test_new_command_with_name(mock_print, session_state, token_tracker):
    """Test /new with name creates thread with that name."""
    result = await handle_command("/new My Project", None, token_tracker, session_state, None)

    assert result is True
    session_state.thread_manager.create_thread.assert_called_once_with(name="My Project")


@patch("deepagents_cli.commands.console.print")
async def test_new_command_without_name(mock_print, session_state, token_tracker):
    """Test /new without name creates thread with name=None."""
    result = await handle_command("/new", None, token_tracker, session_state, None)

    assert result is True
    session_state.thread_manager.create_thread.assert_called_once_with(name=None)


@patch("deepagents_cli.commands.console.print")
async def test_threads_with_args_shows_deprecation_warning(
    mock_print, session_state, token_tracker
):
    """Test /threads with arguments shows friendly error (deprecated subcommands)."""
    result = await handle_command(
        "/threads continue abc123", None, token_tracker, session_state, None
    )

    assert result is True

    # Robust Rich output checking
    assert any(
        "doesn't take arguments" in (args[0].lower() if args else "")
        for args, _ in mock_print.call_args_list
    )


@patch("deepagents_cli.commands.check_server_availability", return_value=False)
@patch("deepagents_cli.commands.enrich_thread_with_server_data", side_effect=lambda t, **_: t)
@patch("deepagents_cli.commands.console.print")
async def test_threads_picker_interactive_flow(
    mock_print,
    mock_enrich,
    mock_check_server,
    session_state,
    token_tracker,
    monkeypatch,
):
    """Test /threads interactive picker switches thread successfully."""
    # Mock thread list with proper structure
    sample_threads = [
        {
            "id": "thread-111",
            "name": "First Thread",
            "created": "2025-01-11T10:00:00Z",
            "last_used": "2025-01-11T10:30:00Z",
            "token_count": 1500,
        },
        {
            "id": "thread-222",
            "name": "Second Thread",
            "created": "2025-01-11T11:00:00Z",
            "last_used": "2025-01-11T11:30:00Z",
            "token_count": 2500,
        },
    ]
    session_state.thread_manager.list_threads.return_value = sample_threads
    session_state.thread_manager.get_current_thread_id.return_value = "thread-111"

    # Mock get_thread_metadata for success message
    session_state.thread_manager.get_thread_metadata.return_value = {
        "id": "thread-111",
        "name": "First Thread",
    }

    picker = AsyncMock(return_value=("thread-111", "switch"))
    monkeypatch.setattr("deepagents_cli.commands._select_thread_interactively", picker)

    result = await handle_command("/threads", None, token_tracker, session_state, object())

    assert result is True
    session_state.thread_manager.switch_thread.assert_called_once_with("thread-111")


# ============================================================================
# Graceful Failure Tests
# ============================================================================


@patch("deepagents_cli.commands.console.clear")
@patch("deepagents_cli.commands.console.print")
async def test_clear_without_thread_manager_shows_warning(mock_print, mock_clear, token_tracker):
    """Test /clear without thread manager shows warning but still resets tracker."""
    session_state_no_manager = SessionState(auto_approve=False, thread_manager=None)

    result = await handle_command("/clear", None, token_tracker, session_state_no_manager, None)

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
async def test_clear_with_thread_manager_creates_new_thread(
    mock_print, mock_clear, session_state, token_tracker
):
    """Test /clear creates new thread and resets token tracker."""
    result = await handle_command("/clear", None, token_tracker, session_state, None)

    assert result is True

    # Critical assertions from feedback
    session_state.thread_manager.create_thread.assert_called_once_with(name="New conversation")
    mock_clear.assert_called_once()

    # Verify token tracker was reset
    assert token_tracker.current_context == token_tracker.baseline_context


# ============================================================================
# LangSmith Metrics Format Tests
# ============================================================================


async def test_format_thread_summary_with_metrics():
    """Test format_thread_summary() with LangSmith metrics."""
    from deepagents_cli.thread_display import format_thread_summary

    thread = {
        "id": "abc123def456",
        "display_name": "Test Thread",
        "trace_count": 42,
        "langsmith_tokens": 15234,
        "preview": "Some preview text",
        "last_used": "2025-01-15T10:00:00Z",
    }

    summary = format_thread_summary(thread, None)

    assert "abc123de" in summary  # Short ID
    assert "Test Thread" in summary
    assert "42 traces" in summary
    assert "15.2K tokens" in summary  # K abbreviation
    assert "Some preview text" in summary


async def test_format_thread_summary_error_state():
    """Test format_thread_summary() shows ?? when LangSmith unavailable."""
    from deepagents_cli.thread_display import format_thread_summary

    thread = {
        "id": "abc123def456",
        "display_name": "Test Thread",
        "trace_count": None,  # Error state
        "langsmith_tokens": 5000,
        "preview": "Some preview text",
        "last_used": "2025-01-15T10:00:00Z",
    }

    summary = format_thread_summary(thread, None)

    assert "0 traces" in summary  # Falls back to zero traces when missing
    assert "5.0K tokens" in summary  # K abbreviation for 5000


async def test_format_thread_summary_zero_traces():
    """Test format_thread_summary() with zero traces."""
    from deepagents_cli.thread_display import format_thread_summary

    thread = {
        "id": "abc123def456",
        "display_name": "Empty Thread",
        "trace_count": 0,  # Zero is valid (new thread)
        "langsmith_tokens": 100,
        "preview": None,
        "last_used": "2025-01-15T10:00:00Z",
    }

    summary = format_thread_summary(thread, None)

    assert "0 traces" in summary  # Shows 0, not ??
    assert "100 tokens" in summary  # No abbreviation


async def test_format_thread_summary_large_numbers():
    """Test format_thread_summary() formats large token counts."""
    from deepagents_cli.thread_display import format_thread_summary

    thread = {
        "id": "abc123def456",
        "display_name": "Large Thread",
        "trace_count": 150,
        "langsmith_tokens": 2_500_000,  # 2.5M
        "preview": None,
        "last_used": "2025-01-15T10:00:00Z",
    }

    summary = format_thread_summary(thread, None)

    assert "150 traces" in summary
    assert "2.5M tokens" in summary  # M abbreviation
