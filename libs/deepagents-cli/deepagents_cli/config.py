"""Configuration, constants, and model creation for the CLI."""

import logging
import os
import sys
from pathlib import Path

import dotenv
from rich.console import Console
from rich.panel import Panel

from .ui_constants import DEFAULT_THEME, Colors

dotenv.load_dotenv()

logger = logging.getLogger(__name__)

# Color scheme
# NOTE: Deprecated - use Colors class from ui_constants.py instead
# This dict is maintained for backward compatibility with existing code
from .ui_constants import Colors as _ColorsClass

COLORS = {
    "primary": _ColorsClass.PRIMARY_HEX,
    "dim": "#6b7280",  # No equivalent in Colors class yet
    "user": "#ffffff",
    "agent": _ColorsClass.PRIMARY_HEX,
    "thinking": "#34d399",  # No equivalent in Colors class yet
    "tool": "#fbbf24",  # No equivalent in Colors class yet
}

# ASCII art banner
DEEP_AGENTS_ASCII = """
 ██████╗  ███████╗ ███████╗ ██████╗
 ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗
 ██║  ██║ █████╗   █████╗   ██████╔╝
 ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝
 ██████╔╝ ███████╗ ███████╗ ██║
 ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝

  █████╗   ██████╗  ███████╗ ███╗   ██╗ ████████╗ ███████╗
 ██╔══██╗ ██╔════╝  ██╔════╝ ████╗  ██║ ╚══██╔══╝ ██╔════╝
 ███████║ ██║  ███╗ █████╗   ██╔██╗ ██║    ██║    ███████╗
 ██╔══██║ ██║   ██║ ██╔══╝   ██║╚██╗██║    ██║    ╚════██║
 ██║  ██║ ╚██████╔╝ ███████╗ ██║ ╚████║    ██║    ███████║
 ╚═╝  ╚═╝  ╚═════╝  ╚══════╝ ╚═╝  ╚═══╝    ╚═╝    ╚══════╝
"""

# Interactive commands (shown in autocomplete)
# Only essential, high-signal commands are listed here for clean UX.
# Advanced commands still work but are hidden from autocomplete.
COMMANDS = {
    "menu": "Open main menu (also: Ctrl+M)",
    "help": "Show help and available commands",
    "new [name]": "Create a new thread",
    "threads": "Switch threads (interactive)",
    "handoff": "Summarize current thread and start a child",
    "tokens": "Show token usage statistics",
    "clear": "Clear screen",
    "quit": "Exit",
}


# Maximum argument length for display
MAX_ARG_LENGTH = 150

# Agent configuration
config = {"recursion_limit": 1000}

# Rich console instance (SINGLETON)
#
# CRITICAL: This is the ONLY Console instance for the entire application.
# DO NOT create new Console() instances elsewhere - always import this singleton.
#
# Why singleton pattern:
# 1. Consistent output state - All components share the same console state
# 2. Thread safety - Multiple Console instances can cause output interleaving
# 3. Performance - Single instance avoids repeated initialization overhead
# 4. Testing - Easier to mock/patch a single import point
#
# Theme integration:
# - Console is initialized with DEFAULT_THEME for semantic style names
# - Use semantic names: console.print("[success]Message[/success]")
# - Legacy Colors.SUCCESS still works for backward compatibility
#
# Usage (correct):
#   from .config import console
#   console.print("[success]Message[/success]")  # Semantic theme name
#   console.print("[bold]Message[/bold]")        # Direct style
#
# Anti-patterns to AVOID:
#   from rich.console import Console
#   Console().print("message")  # ❌ Creates new instance - breaks singleton
#   console = Console()          # ❌ Shadows singleton - causes confusion
#
# See deepagents_cli/ui_constants.py for theme + UI architecture details.
console = Console(highlight=False, theme=DEFAULT_THEME)

# Server request timeout (seconds)
try:
    SERVER_REQUEST_TIMEOUT: float = float(os.getenv("LANGGRAPH_SERVER_TIMEOUT", "5"))
except ValueError:
    SERVER_REQUEST_TIMEOUT = 5.0

# Async checkpointer (required since execute_task is async)
# Set to "0" only for debugging/compatibility testing
USE_ASYNC_CHECKPOINTER = os.getenv("DEEPAGENTS_USE_ASYNC_CHECKPOINTER", "1") in {
    "1",
    "true",
    "True",
}


class SessionState:
    """Holds mutable session state (auto-approve mode, thread manager, etc)."""

    def __init__(self, auto_approve: bool = False, thread_manager=None) -> None:
        self.auto_approve = auto_approve
        self.thread_manager = thread_manager
        self.model = None
        self.pending_handoff_child_id: str | None = None  # Deferred handoff target
        self.menu_requested: bool = False  # Flag for Ctrl+M menu trigger

    def toggle_auto_approve(self) -> bool:
        """Toggle auto-approve and return new state."""
        self.auto_approve = not self.auto_approve
        return self.auto_approve


def get_default_coding_instructions() -> str:
    """Get the default coding agent instructions.

    These are the immutable base instructions that cannot be modified by the agent.
    Long-term memory (agent.md) is handled separately by the middleware.
    """
    default_prompt_path = Path(__file__).parent / "default_agent_prompt.md"
    return default_prompt_path.read_text()


def create_model():
    """Create the appropriate model based on available API keys.

    Returns:
        ChatModel instance (OpenAI or Anthropic)

    Raises:
        SystemExit if no API key is configured
    """
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if openai_key:
        from langchain_openai import ChatOpenAI

        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        console.print(f"[dim]Using OpenAI model: {model_name}[/dim]")
        return ChatOpenAI(
            model=model_name,
            temperature=0.7,
        )
    if anthropic_key:
        from langchain_anthropic import ChatAnthropic

        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        console.print(f"[dim]Using Anthropic model: {model_name}[/dim]")
        return ChatAnthropic(
            model_name=model_name,
            max_tokens=20000,
        )
    console.print(f"[bold {Colors.ERROR}]Error:[/bold {Colors.ERROR}] No API key configured.")
    console.print("\nPlease set one of the following environment variables:")
    console.print("  - OPENAI_API_KEY     (for OpenAI models like gpt-5-mini)")
    console.print("  - ANTHROPIC_API_KEY  (for Claude models)")
    console.print("\nExample:")
    console.print("  export OPENAI_API_KEY=your_api_key_here")
    console.print("\nOr add it to your .env file.")
    sys.exit(1)


def handle_error(
    error: Exception,
    context: str,
    fatal: bool = False,
    show_traceback: bool = False,
    log_level: str = "error",
) -> None:
    """Centralized error handler with consistent styling across all components.

    Args:
        error: The exception that was caught
        context: Description of where/what was happening when error occurred
        fatal: If True, re-raises the exception after displaying
        show_traceback: If True and debug logging enabled, shows full traceback
        log_level: Logging level to use ('error', 'warning', 'info')

    Example:
        try:
            risky_operation()
        except Exception as e:
            handle_error(e, context="bash command execution", fatal=False)
    """
    # Display styled error panel
    console.print()
    error_panel = Panel(
        f"[bold]{error}[/bold]",
        title=f"[bold {Colors.ERROR}]Error in {context}[/bold {Colors.ERROR}]",
        border_style=Colors.ERROR,
        padding=(0, 1),
    )
    console.print(error_panel)
    console.print()

    # Log with appropriate level
    log_func = getattr(logger, log_level, logger.error)
    log_func(f"Error in {context}: {error}", exc_info=show_traceback)

    # Show full traceback in debug mode
    if show_traceback and logger.isEnabledFor(logging.DEBUG):
        console.print_exception()

    # Re-raise if fatal
    if fatal:
        raise
