"""Configuration, constants, and model creation for the CLI."""

import os
import sys
from pathlib import Path
from typing import Any

import dotenv
from rich.console import Console

dotenv.load_dotenv()

# Color scheme
COLORS = {
    "primary": "#10b981",
    "dim": "#6b7280",
    "user": "#ffffff",
    "agent": "#10b981",
    "thinking": "#34d399",
    "tool": "#fbbf24",
}

# ASCII art banner (default - current Deep Agents branding)
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

# Experimental Deep-Ai banner variants.
# These are opt-in via CLI flags (e.g., --v1, --v2, ...).
DEEP_AI_ASCII_V1 = r"""
 ██████╗  ███████╗ ███████╗ ██████╗
 ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗
 ██║  ██║ █████╗   █████╗   ██████╔╝
 ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝
 ██████╔╝ ███████╗ ███████╗ ██║
 ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝

  █████╗        ██╗
 ██╔══██╗       ██║
 ███████║       ██║
 ██╔══██║       ██║
 ██║  ██║       ██║
 ╚═╝  ╚═╝       ╚═╝
"""

DEEP_AI_ASCII_V2 = r"""
DeepAI banner variant slot (v2).
"""

DEEP_AI_ASCII_V3 = r"""
Deep-Ai banner variant slot (v3).
"""

DEEP_AI_ASCII_V4 = r"""
[bright_cyan] ██████╗  ███████╗ ███████╗ ██████╗[/bright_cyan]      [cyan] █████╗[/cyan]        [#10b981]██╗[/#10b981]
[bright_cyan] ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗[/bright_cyan]    [cyan]██╔══██╗[/cyan]       [#10b981]██║[/#10b981]
[bright_cyan] ██║  ██║ █████╗   █████╗   ██████╔╝[/bright_cyan]    [cyan]███████║[/cyan]       [#10b981]██║[/#10b981]
[cyan] ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝[/cyan]     [#10b981]██╔══██║[/#10b981]       [#10b981]██║[/#10b981]
[cyan] ██████╔╝ ███████╗ ███████╗ ██║[/cyan]         [#10b981]██║  ██║[/#10b981]       [#10b981]██║[/#10b981]
[cyan] ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝[/cyan]         [#10b981]╚═╝  ╚═╝[/#10b981]       [#10b981]╚═╝[/#10b981]
"""

DEEP_AI_ASCII_V5 = r"""
[bold bright_cyan] ██████╗  ███████╗ ███████╗ ██████╗[/bold bright_cyan]      [bold bright_magenta] █████╗        ██╗[/bold bright_magenta]
[bold bright_cyan] ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗[/bold bright_cyan]    [bold bright_magenta]██╔══██╗       ██║[/bold bright_magenta]
[bold bright_cyan] ██║  ██║ █████╗   █████╗   ██████╔╝[/bold bright_cyan]    [bold bright_magenta]███████║       ██║[/bold bright_magenta]
[bold bright_cyan] ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝[/bold bright_cyan]     [bold bright_magenta]██╔══██║       ██║[/bold bright_magenta]
[bold bright_cyan] ██████╔╝ ███████╗ ███████╗ ██║[/bold bright_cyan]         [bold bright_magenta]██║  ██║       ██║[/bold bright_magenta]
[bold bright_cyan] ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝[/bold bright_cyan]         [bold bright_magenta]╚═╝  ╚═╝       ╚═╝[/bold bright_magenta]
"""

DEEP_AI_ASCII_V6 = r"""
[bold yellow on black] ██████╗  ███████╗ ███████╗ ██████╗ [/bold yellow on black]     [bold bright_yellow on black] █████╗        ██╗[/bold bright_yellow on black]
[bold yellow on black] ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗[/bold yellow on black]    [bold bright_yellow on black]██╔══██╗       ██║[/bold bright_yellow on black]
[bold bright_yellow on black] ██║  ██║ █████╗   █████╗   ██████╔╝[/bold bright_yellow on black]    [bold bright_white on black]███████║       ██║[/bold bright_white on black]
[bold bright_yellow on black] ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝[/bold bright_yellow on black]     [bold bright_white on black]██╔══██║       ██║[/bold bright_white on black]
[bold bright_white on black] ██████╔╝ ███████╗ ███████╗ ██║[/bold bright_white on black]         [bold bright_white on black]██║  ██║       ██║[/bold bright_white on black]
[bold bright_white on black] ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝[/bold bright_white on black]         [bold bright_white on black]╚═╝  ╚═╝       ╚═╝[/bold bright_white on black]
"""

DEEP_AI_ASCII_V7 = r"""
[dim bright_cyan] ██████╗  ███████╗ ███████╗ ██████╗[/dim bright_cyan]      [white] █████╗        ██╗[/white]
[dim bright_cyan] ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗[/dim bright_cyan]    [white]██╔══██╗       ██║[/white]
[dim bright_cyan] ██║  ██║ █████╗   █████╗   ██████╔╝[/dim bright_cyan]    [bold white]███████║       ██║[/bold white]
[dim bright_cyan] ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝[/dim bright_cyan]     [bold white]██╔══██║       ██║[/bold white]
[dim cyan] ██████╔╝ ███████╗ ███████╗ ██║[/dim cyan]         [bold white]██║  ██║       ██║[/bold white]
[dim cyan] ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝[/dim cyan]         [bold white]╚═╝  ╚═╝       ╚═╝[/bold white]
"""

BANNER_VARIANTS: dict[str, str] = {
    "v1": DEEP_AI_ASCII_V1,
    "v2": DEEP_AI_ASCII_V2,
    "v3": DEEP_AI_ASCII_V3,
    "v4": DEEP_AI_ASCII_V4,
    "v5": DEEP_AI_ASCII_V5,
    "v6": DEEP_AI_ASCII_V6,
    "v7": DEEP_AI_ASCII_V7,
}


def get_banner_ascii(banner_variant: str | None) -> str:
    """Return the appropriate banner ASCII art for the given variant.

    Args:
        banner_variant: Variant key such as "v1", "v2", etc., or None.

    Returns:
        ASCII art string for the selected banner. Defaults to DEEP_AGENTS_ASCII
        when no variant (or an unknown variant) is provided.
    """
    if not banner_variant:
        return DEEP_AGENTS_ASCII
    return BANNER_VARIANTS.get(banner_variant, DEEP_AGENTS_ASCII)

# Interactive commands (shown in autocomplete)
# Only essential, high-signal commands are listed here for clean UX.
# Advanced commands still work but are hidden from autocomplete.
COMMANDS = {
    "help": "Show help and available commands",
    "new": "Create a new thread (/new [name])",
    "threads": "Switch threads (interactive)",
    "handoff": "Summarize current thread and start a child",
    "tokens": "Show token usage statistics",
    "clear": "Clear screen",
    "quit": "Exit (also: /exit)",
    "exit": "Exit the CLI",
}


# Maximum argument length for display
MAX_ARG_LENGTH = 150

# Agent configuration
config = {"recursion_limit": 1000}

# Rich console instance
console = Console(highlight=False)

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

    def __init__(
        self,
        auto_approve: bool = False,
        thread_manager: Any | None = None,
        banner_variant: str | None = None,
    ) -> None:
        self.auto_approve = auto_approve
        self.thread_manager = thread_manager
        self.banner_variant = banner_variant
        self.model = None
        self.pending_handoff_child_id: str | None = None  # Deferred handoff target
        self.menu_requested: bool = False  # Reserved for manual menu triggers
        self.exit_hint_until: float | None = None
        self.exit_hint_handle = None

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
        )
    if anthropic_key:
        from langchain_anthropic import ChatAnthropic

        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        console.print(f"[dim]Using Anthropic model: {model_name}[/dim]")
        return ChatAnthropic(
            model_name=model_name,
            max_tokens=20000,
        )
    console.print("[bold red]Error:[/bold red] No API key configured.")
    console.print("\nPlease set one of the following environment variables:")
    console.print("  - OPENAI_API_KEY     (for OpenAI models like gpt-5-mini)")
    console.print("  - ANTHROPIC_API_KEY  (for Claude models)")
    console.print("\nExample:")
    console.print("  export OPENAI_API_KEY=your_api_key_here")
    console.print("\nOr add it to your .env file.")
    sys.exit(1)
