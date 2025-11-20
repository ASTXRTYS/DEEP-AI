"""Unit tests for deepagents_cli.input."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from deepagents_cli.input import (
    CommandCompleter,
    FilePathCompleter,
    create_prompt_session,
    parse_file_mentions,
)
from prompt_toolkit.document import Document


@pytest.fixture
def command_completer():
    return CommandCompleter()


@pytest.fixture
def file_path_completer():
    return FilePathCompleter()


def test_command_completer(command_completer):
    """Test command completion."""
    # Should complete /help
    doc = Document("/hel", cursor_position=4)
    completions = list(command_completer.get_completions(doc, None))
    assert len(completions) > 0
    assert any(c.text == "help" for c in completions)

    # Should not complete if not starting with /
    doc = Document("hel", cursor_position=3)
    completions = list(command_completer.get_completions(doc, None))
    assert len(completions) == 0


def test_file_path_completer(file_path_completer):
    """Test file path completion."""
    # Mock PathCompleter
    file_path_completer.path_completer = MagicMock()
    file_path_completer.path_completer.get_completions.return_value = [
        MagicMock(text="file.txt", start_position=0, display="file.txt", display_meta="")
    ]

    # Should complete @file
    doc = Document("Check @fi", cursor_position=9)
    completions = list(file_path_completer.get_completions(doc, None))
    assert len(completions) > 0
    assert completions[0].text == "file.txt"

    # Should not complete if no @
    doc = Document("Check fi", cursor_position=8)
    completions = list(file_path_completer.get_completions(doc, None))
    assert len(completions) == 0


def test_parse_file_mentions():
    """Test parsing of @file mentions."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch("pathlib.Path.resolve", return_value=Path("/abs/file.txt")):
        
        text = "Read @file.txt please"
        cleaned, files = parse_file_mentions(text)
        
        assert len(files) == 1
        assert str(files[0]) == "/abs/file.txt"
        # The text itself isn't modified by parse_file_mentions, it just extracts files
        assert cleaned == text


def test_create_prompt_session():
    """Test prompt session creation."""
    session_state = MagicMock()
    session_state.auto_approve = False
    
    with patch("deepagents_cli.input.PromptSession") as MockSession:
        session = create_prompt_session("agent-id", session_state)
        
        # Verify keybindings are created
        assert MockSession.call_args[1]["key_bindings"] is not None
        assert MockSession.call_args[1]["bottom_toolbar"] is not None
