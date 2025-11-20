"""Unit tests for deepagents_cli.commands."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from deepagents_cli.commands import (
    execute_bash_command,
    handle_command,
    handle_handoff_command,
    handle_thread_commands_async,
)
from deepagents_cli.ui import TokenTracker


@pytest.fixture
def mock_console():
    with patch("deepagents_cli.commands.console") as mock:
        yield mock


@pytest.fixture
def mock_thread_manager():
    manager = MagicMock()
    manager.list_threads.return_value = [
        {"id": "thread-1", "name": "Thread 1", "updated_at": "2024-01-01T00:00:00Z"},
        {"id": "thread-2", "name": "Thread 2", "updated_at": "2024-01-02T00:00:00Z"},
    ]
    manager.get_current_thread_id.return_value = "thread-1"
    return manager


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    agent.aget_state.return_value = MagicMock(values={"messages": []})
    return agent


@pytest.fixture
def mock_session_state(mock_thread_manager):
    state = MagicMock()
    state.thread_manager = mock_thread_manager
    state.model = MagicMock()
    return state


@pytest.fixture
def token_tracker():
    return TokenTracker()


@pytest.mark.asyncio
async def test_handle_command_exit(mock_agent, token_tracker):
    """Test exit commands."""
    assert await handle_command("/quit", mock_agent, token_tracker) == "exit"
    assert await handle_command("/exit", mock_agent, token_tracker) == "exit"
    assert await handle_command("/q", mock_agent, token_tracker) == "exit"


@pytest.mark.asyncio
async def test_handle_command_help(mock_console, mock_agent, token_tracker):
    """Test help command."""
    with patch("deepagents_cli.commands.show_interactive_help") as mock_help:
        assert await handle_command("/help", mock_agent, token_tracker) is True
        mock_help.assert_called_once()


@pytest.mark.asyncio
async def test_handle_command_tokens(mock_console, mock_agent, token_tracker):
    """Test tokens command."""
    token_tracker.display_session = MagicMock()
    assert await handle_command("/tokens", mock_agent, token_tracker) is True
    token_tracker.display_session.assert_called_once()


@pytest.mark.asyncio
async def test_handle_command_new(
    mock_console, mock_agent, token_tracker, mock_session_state
):
    """Test new thread command."""
    mock_session_state.thread_manager.create_thread.return_value = "new-thread-id"
    
    assert await handle_command(
        "/new My Thread", mock_agent, token_tracker, session_state=mock_session_state
    ) is True
    
    mock_session_state.thread_manager.create_thread.assert_called_with(name="My Thread")
    mock_console.print.assert_called()


@pytest.mark.asyncio
async def test_handle_command_clear(
    mock_console, mock_agent, token_tracker, mock_session_state
):
    """Test clear command."""
    mock_session_state.thread_manager.create_thread.return_value = "new-thread-id"
    token_tracker.reset = MagicMock()
    
    assert await handle_command(
        "/clear", mock_agent, token_tracker, session_state=mock_session_state
    ) is True
    
    mock_console.clear.assert_called()
    mock_session_state.thread_manager.create_thread.assert_called()
    token_tracker.reset.assert_called()


@pytest.mark.asyncio
async def test_handle_command_unknown(mock_console, mock_agent, token_tracker):
    """Test unknown command."""
    assert await handle_command("/unknown", mock_agent, token_tracker) is True
    mock_console.print.assert_called()
    assert "Unknown command" in str(mock_console.print.call_args_list)


@pytest.mark.asyncio
async def test_handle_thread_commands_list(mock_console, mock_thread_manager, mock_agent):
    """Test /threads list."""
    # Mock _load_enriched_threads to avoid external calls
    with patch("deepagents_cli.commands._load_enriched_threads") as mock_load:
        mock_load.return_value = mock_thread_manager.list_threads()
        
        await handle_thread_commands_async("list", mock_thread_manager, mock_agent)
        
        # Should print the list
        assert mock_console.print.call_count >= 3


@pytest.mark.asyncio
async def test_handle_thread_commands_switch(mock_console, mock_thread_manager, mock_agent):
    """Test /threads switch."""
    with patch("deepagents_cli.commands._load_enriched_threads") as mock_load:
        mock_load.return_value = mock_thread_manager.list_threads()
        
        # Switch by ID
        await handle_thread_commands_async("switch thread-2", mock_thread_manager, mock_agent)
        mock_thread_manager.switch_thread.assert_called_with("thread-2")
        
        # Switch by index
        mock_thread_manager.switch_thread.reset_mock()
        await handle_thread_commands_async("switch 1", mock_thread_manager, mock_agent)
        mock_thread_manager.switch_thread.assert_called_with("thread-1")


@pytest.mark.asyncio
async def test_handle_thread_commands_rename(mock_console, mock_thread_manager, mock_agent):
    """Test /threads rename."""
    with patch("deepagents_cli.commands._load_enriched_threads") as mock_load:
        mock_load.return_value = mock_thread_manager.list_threads()
        
        await handle_thread_commands_async("rename 1 New Name", mock_thread_manager, mock_agent)
        mock_thread_manager.rename_thread.assert_called_with("thread-1", "New Name")


@pytest.mark.asyncio
async def test_handle_thread_commands_delete(mock_console, mock_thread_manager, mock_agent):
    """Test /threads delete."""
    with patch("deepagents_cli.commands._load_enriched_threads") as mock_load:
        mock_load.return_value = mock_thread_manager.list_threads()
        
        # Without force
        await handle_thread_commands_async("delete 1", mock_thread_manager, mock_agent)
        mock_thread_manager.delete_thread.assert_not_called()
        
        # With force
        await handle_thread_commands_async("delete 1 --force", mock_thread_manager, mock_agent)
        mock_thread_manager.delete_thread.assert_called_with("thread-1", mock_agent)


@pytest.mark.asyncio
async def test_handle_handoff_command_validation(mock_console, mock_agent, mock_session_state):
    """Test handoff command validation."""
    # No thread manager
    mock_session_state.thread_manager = None
    assert await handle_handoff_command("", mock_agent, mock_session_state) is True
    assert "Thread manager not available" in str(mock_console.print.call_args_list)
    
    # No agent
    mock_session_state.thread_manager = MagicMock()
    assert await handle_handoff_command("", None, mock_session_state) is True
    assert "Agent is not initialized" in str(mock_console.print.call_args_list)


def test_execute_bash_command(mock_console):
    """Test bash command execution."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="output", stderr="", returncode=0
        )
        
        assert execute_bash_command("!ls -la") is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == "ls -la"
