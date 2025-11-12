"""Main entry point for the DeepAgents CLI using Cement + Rich architecture.

This module provides the command-line interface for running DeepAgents,
replacing the Questionary-based system with Cement framework and Rich UI components.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .cement_interactive import start_interactive_mode
from .config import SessionState, console


def cement_main() -> None:
    """Entry point for the DeepAgents CLI with Cement + Rich architecture.

    This is the main entry point for the CLI, handling argument parsing
    and launching the interactive mode.
    """
    parser = argparse.ArgumentParser(
        description="DeepAgents - AI-powered coding assistant with interactive CLI"
    )

    parser.add_argument(
        "--agent",
        type=str,
        default="agent",
        help="Agent name/ID to use (default: agent)",
    )

    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve tool executions without confirmation prompts",
    )

    parser.add_argument(
        "command",
        nargs="?",
        choices=["list", "reset", "help"],
        help="Command to execute (optional)",
    )

    # Additional arguments for reset command
    parser.add_argument(
        "--target",
        type=str,
        help="Target agent to copy prompt from (for reset command)",
    )

    args = parser.parse_args()

    # Handle non-interactive commands
    if args.command == "list":
        from .agent import list_agents
        list_agents()
        return

    elif args.command == "reset":
        from .agent import reset_agent
        reset_agent(args.agent, args.target)
        return

    elif args.command == "help":
        parser.print_help()
        return

    # Start interactive mode
    session_state = SessionState(auto_approve=args.auto_approve)

    try:
        asyncio.run(start_interactive_mode(args.agent, session_state))
    except KeyboardInterrupt:
        console.print("\n[cyan]Goodbye! Happy coding! 👋[/cyan]", style="bold")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]❌ Error:[/bold red] {e}\n")
        raise


if __name__ == "__main__":
    cement_main()
