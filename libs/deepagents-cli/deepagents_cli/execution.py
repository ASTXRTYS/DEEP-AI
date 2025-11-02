"""Task execution and streaming logic for the CLI."""

import json
import sys
import termios
import threading
import time
import tty
from datetime import datetime
from typing import Optional, Dict, List, Any
import re

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from rich import box
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from .config import COLORS, console
from .file_ops import FileOpTracker, build_approval_preview
from .input import parse_file_mentions
from .ui import (
    AgentStateMonitor,
    TokenTracker,
    create_working_indicator,
    format_tool_display,
    format_tool_message_content,
    render_agent_state_panel,
    render_agent_transparency_dashboard,
    render_enhanced_tool_call,
    render_reasoning_display,
    render_diff_block,
    render_file_operation,
    render_summary_panel,
    render_todo_list,
    truncate_value,
)


# Hacker Terminal Enhancement Classes
class HackerTerminalCursor:
    """Blinking cursor effect for hacker terminal aesthetic."""
    
    def __init__(self):
        self.is_visible = True
        self.cursor_char = "█"  # Solid block cursor
        self.blink_rate = 0.5  # seconds
        self._stop_event = threading.Event()
        self._blink_thread = None
    
    def start_blinking(self):
        """Start the blinking cursor effect."""
        if self._blink_thread and self._blink_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._blink_thread = threading.Thread(target=self._blink_loop, daemon=True)
        self._blink_thread.start()
    
    def stop_blinking(self):
        """Stop the blinking cursor effect."""
        self._stop_event.set()
        if self._blink_thread:
            self._blink_thread.join(timeout=1.0)
    
    def _blink_loop(self):
        """Internal blinking loop."""
        while not self._stop_event.is_set():
            self.is_visible = not self.is_visible
            time.sleep(self.blink_rate)
    
    def get_cursor_display(self) -> str:
        """Get the current cursor character for display."""
        if self.is_visible:
            return f"[{COLORS['cursor']}]{self.cursor_char}[/{COLORS['cursor']}]"
        return " "  # Invisible when not visible
    
    def print_cursor(self):
        """Print the cursor at current position."""
        console.print(self.get_cursor_display(), end="", markup=False)
        console.file.flush()


# Global cursor instance
hacker_cursor = HackerTerminalCursor()