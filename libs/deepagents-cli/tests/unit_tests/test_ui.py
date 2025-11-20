"""Unit tests for deepagents_cli.ui."""

from unittest.mock import MagicMock, patch

import pytest
from deepagents_cli.ui import (
    TokenTracker,
    format_diff_rich,
    format_tool_display,
    truncate_value,
)


def test_truncate_value():
    """Test string truncation."""
    assert truncate_value("short") == "short"
    assert truncate_value("a" * 100, max_length=10) == "aaaaaaaaaa..."


def test_format_tool_display():
    """Test tool display formatting."""
    # Read file
    # /abs/path/to/file.py is short enough (<60 chars) to be shown fully
    assert format_tool_display("read_file", {"file_path": "/abs/path/to/file.py"}) == "read_file(/abs/path/to/file.py)"
    
    # Web search
    assert format_tool_display("web_search", {"query": "python testing"}) == 'web_search("python testing")'
    
    # Shell
    assert format_tool_display("shell", {"command": "ls -la"}) == 'shell("ls -la")'
    
    # Generic
    assert format_tool_display("unknown_tool", {"arg1": "val1"}) == "unknown_tool(arg1=val1)"


def test_format_diff_rich():
    """Test diff formatting."""
    diff = [
        "@@ -1,2 +1,2 @@",
        "-old line",
        "+new line",
        " context line"
    ]
    
    formatted = format_diff_rich(diff)
    
    # Check for presence of content
    assert "old line" in formatted
    assert "new line" in formatted
    assert "context line" in formatted
    
    # Check for rich markup (colors)
    assert "dark_red" in formatted
    assert "dark_green" in formatted


def test_token_tracker():
    """Test token tracking logic."""
    tracker = TokenTracker()
    
    # Initial state
    assert tracker.baseline_context == 0
    assert tracker.current_context == 0
    
    # Set baseline
    tracker.set_baseline(1000)
    assert tracker.baseline_context == 1000
    assert tracker.current_context == 1000
    
    # Add tokens (simulating response)
    # Input tokens = 1200 (context grew), Output = 50
    tracker.add(1200, 50)
    assert tracker.current_context == 1200
    assert tracker.last_output == 50
    
    # Reset
    tracker.reset()
    assert tracker.current_context == 1000  # Back to baseline
    assert tracker.last_output == 0
