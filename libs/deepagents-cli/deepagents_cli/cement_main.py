"""Cement-based CLI application for DeepAgents.

This module provides the main Cement App class and entry point,
replacing the Questionary-based interactive system with a structured
command-line interface enhanced with Rich visual components.
"""

import sys
from pathlib import Path
from typing import Any

from cement import App, Controller, ex
from cement.core.exc import CaughtSignal

from .config import COLORS, DEEP_AGENTS_ASCII, SessionState, console, create_model
from .rich_ui import (
    RichPrompt,
    display_ascii_banner,
    display_connection_status,
    display_server_error,
    display_tavily_warning,
    display_welcome,
)


# App configuration defaults
CONFIG = {
    "deepagents": {
        "agent": "agent",
        "auto_approve": False,
        "debug": False,
    }
}


class DeepAgentsError(Exception):
    """DeepAgents application exception."""


class BaseController(Controller):
    """Base controller for DeepAgents CLI.

    Provides core functionality and the interactive mode entry point.
    """

    class Meta:
        label = "base"
        description = "DeepAgents - AI Coding Assistant with Planning & Memory"
        epilog = """
Examples:
  deepagents                    Start interactive mode (default)
  deepagents list               List all available agents
  deepagents reset --agent foo  Reset agent 'foo'
  deepagents help               Show detailed help

Interactive Mode:
  Once started, you can:
  • Type your coding requests naturally
  • Press Ctrl+M to open the menu system
  • Use /commands for slash commands
  • Use !command for bash execution

For more information: https://github.com/langchain-ai/deepagents
"""

        # Controller level arguments
        arguments = [
            (
                ["-v", "--version"],
                {
                    "action": "version",
                    "version": "DeepAgents CLI 0.0.7",
                },
            ),
            (
                ["--agent"],
                {
                    "help": "Agent identifier for separate memory stores",
                    "action": "store",
                    "dest": "agent",
                    "default": "agent",
                },
            ),
            (
                ["--auto-approve"],
                {
                    "help": "Auto-approve tool usage (disable human-in-the-loop)",
                    "action": "store_true",
                    "dest": "auto_approve",
                },
            ),
        ]

    def _default(self):
        """Default action - start interactive mode."""
        # Import here to avoid circular imports
        from .cement_interactive import start_interactive_mode

        # Create session state from args
        session_state = SessionState(auto_approve=self.app.pargs.auto_approve)

        # Start interactive mode (async)
        import asyncio

        try:
            asyncio.run(start_interactive_mode(self.app.pargs.agent, session_state))
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted[/yellow]")
            sys.exit(0)

    @ex(
        help="list all available agents",
        arguments=[],
    )
    def list(self):
        """List all available agents."""
        from .agent import list_agents

        list_agents()

    @ex(
        help="show detailed help information",
        arguments=[],
    )
    def help(self):
        """Show detailed help information."""
        from .ui import show_help

        show_help()

    @ex(
        help="reset an agent's memory and configuration",
        arguments=[
            (
                ["--agent"],
                {
                    "help": "Name of agent to reset",
                    "action": "store",
                    "dest": "agent_name",
                    "required": True,
                },
            ),
            (
                ["--target"],
                {
                    "help": "Copy prompt from another agent",
                    "action": "store",
                    "dest": "source_agent",
                },
            ),
        ],
    )
    def reset(self):
        """Reset an agent."""
        from .agent import reset_agent

        reset_agent(self.app.pargs.agent_name, self.app.pargs.source_agent)


class DeepAgentsApp(App):
    """DeepAgents CLI application."""

    class Meta:
        label = "deepagents"
        config_defaults = CONFIG
        exit_on_close = True

        # Load extensions
        extensions = []

        # Handlers (use defaults)

        # Register controllers
        handlers = [BaseController]

        # Hooks
        hooks = []


def setup_rich_console(app: App) -> None:
    """Hook to set up Rich console on app.

    Makes console available as app.console.
    """
    from .config import console as rich_console

    app.extend("console", rich_console)
    app.extend("rich_prompt", RichPrompt(rich_console))


def check_cli_dependencies() -> None:
    """Check if CLI optional dependencies are installed."""
    missing = []

    try:
        import rich  # noqa: F401
    except ImportError:
        missing.append("rich")

    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    try:
        import dotenv  # noqa: F401
    except ImportError:
        missing.append("python-dotenv")

    try:
        import tavily  # noqa: F401
    except ImportError:
        missing.append("tavily-python")

    try:
        import cement  # noqa: F401
    except ImportError:
        missing.append("cement")

    if missing:
        console.print("[bold red]Missing required CLI dependencies:[/bold red]")
        for pkg in missing:
            console.print(f"  • {pkg}")
        console.print()
        console.print(
            "Install them with: [cyan]pip install 'deepagents[cli]' cement[/cyan]"
        )
        sys.exit(1)


def cement_main() -> None:
    """Main entry point for Cement-based CLI."""
    # Check dependencies first
    check_cli_dependencies()

    with DeepAgentsApp() as app:
        try:
            # Setup Rich console
            setup_rich_console(app)

            # Run the application
            app.run()

        except AssertionError as e:
            console.print(f"[bold red]AssertionError:[/bold red] {e.args[0]}")
            app.exit_code = 1

            if app.debug is True:
                import traceback

                traceback.print_exc()

        except DeepAgentsError as e:
            console.print(f"[bold red]DeepAgentsError:[/bold red] {e.args[0]}")
            app.exit_code = 1

            if app.debug is True:
                import traceback

                traceback.print_exc()

        except CaughtSignal as e:
            console.print(f"\n{e}")
            app.exit_code = 0


if __name__ == "__main__":
    cement_main()
