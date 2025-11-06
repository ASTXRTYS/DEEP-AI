"""Main entry point and CLI loop for deepagents."""

import argparse
import asyncio
import sys
from pathlib import Path

from .agent import create_agent_with_config, list_agents, reset_agent
from .commands import execute_bash_command, handle_command
from .config import COLORS, DEEP_AGENTS_ASCII, SessionState, console, create_model
from .execution import execute_task
from .input import create_prompt_session
from .thread_manager import ThreadManager
from .tools import http_request, tavily_client, web_search
from .ui import TokenTracker, show_help


def check_cli_dependencies() -> None:
    """Check if CLI optional dependencies are installed."""
    missing = []

    try:
        import rich
    except ImportError:
        missing.append("rich")

    try:
        import requests
    except ImportError:
        missing.append("requests")

    try:
        import dotenv
    except ImportError:
        missing.append("python-dotenv")

    try:
        import tavily
    except ImportError:
        missing.append("tavily-python")

    try:
        import prompt_toolkit
    except ImportError:
        missing.append("prompt-toolkit")

    if missing:
        console.print("[bold red]Missing required CLI dependencies:[/bold red]")
        for pkg in missing:
            console.print(f"  • {pkg}")
        console.print()
        console.print(
            "Install them with: [cyan]pip install 'deepagents[cli]'[/cyan] or add them to your environment."
        )
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DeepAgents - AI Coding Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List command
    subparsers.add_parser("list", help="List all available agents")

    # Help command
    subparsers.add_parser("help", help="Show help information")

    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Reset an agent")
    reset_parser.add_argument("--agent", required=True, help="Name of agent to reset")
    reset_parser.add_argument(
        "--target", dest="source_agent", help="Copy prompt from another agent"
    )

    # Default interactive mode
    parser.add_argument(
        "--agent",
        default="agent",
        help="Agent identifier for separate memory stores (default: agent).",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve tool usage without prompting (disables human-in-the-loop)",
    )

    return parser.parse_args()


async def simple_cli(
    agent, assistant_id: str | None, session_state, baseline_tokens: int = 0
) -> None:
    """Main CLI loop."""
    from .server_client import is_server_available

    console.clear()
    console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
    console.print()

    # Show server status
    if is_server_available():
        console.print("[green]● Connected to LangGraph server[/green]")
        console.print()

    if tavily_client is None:
        console.print(
            "[yellow]⚠ Web search disabled:[/yellow] TAVILY_API_KEY not found.",
            style=COLORS["dim"],
        )
        console.print("  To enable web search, set your Tavily API key:", style=COLORS["dim"])
        console.print("    export TAVILY_API_KEY=your_api_key_here", style=COLORS["dim"])
        console.print(
            "  Or add it to your .env file. Get your key at: https://tavily.com",
            style=COLORS["dim"],
        )
        console.print()

    console.print("... Ready to code! What would you like to build?", style=COLORS["agent"])
    console.print(f"  [dim]Working directory: {Path.cwd()}[/dim]")
    console.print()

    if session_state.auto_approve:
        console.print(
            "  [yellow]⚡ Auto-approve: ON[/yellow] [dim](tools run without confirmation)[/dim]"
        )
        console.print()

    console.print(
        "  Tips: Enter to submit, Alt+Enter for newline, Ctrl+E for editor, Ctrl+T to toggle auto-approve, Ctrl+C to interrupt",
        style=f"dim {COLORS['dim']}",
    )
    console.print()

    # Create prompt session and token tracker
    session = create_prompt_session(assistant_id, session_state)
    token_tracker = TokenTracker()
    token_tracker.set_baseline(baseline_tokens)

    while True:
        try:
            user_input = await session.prompt_async()
            user_input = user_input.strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            # Ctrl+C at prompt - exit the program
            console.print("\nGoodbye!", style=COLORS["primary"])
            break

        if not user_input:
            continue

        # Check for slash commands first
        if user_input.startswith("/"):
            result = handle_command(user_input, agent, token_tracker, session_state)
            if result == "exit":
                console.print("\nGoodbye!", style=COLORS["primary"])
                break
            if result:
                # Command was handled, continue to next input
                continue

        # Check for bash commands (!)
        if user_input.startswith("!"):
            execute_bash_command(user_input)
            continue

        # Handle regular quit keywords
        if user_input.lower() in ["quit", "exit", "q"]:
            console.print("\nGoodbye!", style=COLORS["primary"])
            break

        await execute_task(user_input, agent, assistant_id, session_state, token_tracker)


async def main(assistant_id: str, session_state) -> None:
    """Main entry point."""
    from .server_client import is_server_available, start_server_if_needed

    # Check if server is running, offer to start if not
    if not is_server_available():
        console.print("[yellow]⚠ LangGraph server is not running[/yellow]")
        console.print()
        console.print("The DeepAgents CLI now requires the LangGraph server for thread management.")
        console.print(
            "This enables features like message history, thread naming, and Studio integration."
        )
        console.print()

        # Try to start server automatically
        console.print("[dim]Starting LangGraph dev server...[/dim]")
        started, error_message = start_server_if_needed()
        if started:
            console.print("[green]✓ Server started successfully![/green]")
            console.print()
        else:
            console.print("[red]✗ Failed to start server automatically[/red]")
            console.print()
            if error_message:
                console.print(f"[red]{error_message}[/red]")
                console.print()
            console.print("Please start the server manually in another terminal:")
            console.print("  [cyan]langgraph dev[/cyan]")
            console.print()
            console.print("Then restart the CLI.")
            import sys

            sys.exit(1)

    # Create the model (checks API keys)
    model = create_model()

    # Initialize thread manager
    agent_dir = Path.home() / ".deepagents" / assistant_id
    thread_manager = ThreadManager(agent_dir, assistant_id)
    session_state.thread_manager = thread_manager

    # Create agent with conditional tools
    tools = [http_request]
    if tavily_client is not None:
        tools.append(web_search)

    # REQUIRED: AsyncSqliteSaver because execute_task is async (uses agent.astream())
    # Upstream merge 5f8516c made execute_task async, so sync SqliteSaver no longer works
    from .config import USE_ASYNC_CHECKPOINTER

    if not USE_ASYNC_CHECKPOINTER:
        console.print("[yellow]⚠ Warning: Async checkpointer disabled (not recommended)[/yellow]")
        console.print("[dim]Set DEEPAGENTS_USE_ASYNC_CHECKPOINTER=1 to enable (required for proper operation)[/dim]")
        console.print()

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    # Ensure agent directory exists before creating database
    agent_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_db = agent_dir / "checkpoints.db"

    # AsyncSqliteSaver.from_conn_string expects a SQLite URI
    db_uri = f"sqlite:///{checkpoint_db.resolve()}"

    try:
        async with AsyncSqliteSaver.from_conn_string(db_uri) as checkpointer:
            await checkpointer.asetup()

            # Create agent with async checkpointer
            agent = create_agent_with_config(model, assistant_id, tools, checkpointer=checkpointer)

            # Calculate baseline token count for accurate token tracking
            from .agent import get_system_prompt
            from .token_utils import calculate_baseline_tokens

            system_prompt = get_system_prompt()
            baseline_tokens = calculate_baseline_tokens(model, agent_dir, system_prompt)

            # Run CLI loop inside async context (keeps connection alive)
            await simple_cli(agent, assistant_id, session_state, baseline_tokens)

    except KeyboardInterrupt:
        # Context manager exits cleanly on Ctrl+C
        console.print("\n[yellow]Interrupted[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]❌ Error:[/bold red] {e}\n")
        raise


def cli_main() -> None:
    """Entry point for console script."""
    # Check dependencies first
    check_cli_dependencies()

    try:
        args = parse_args()

        if args.command == "help":
            show_help()
        elif args.command == "list":
            list_agents()
        elif args.command == "reset":
            reset_agent(args.agent, args.source_agent)
        else:
            # Create session state from args
            session_state = SessionState(auto_approve=args.auto_approve)

            # API key validation happens in create_model()
            asyncio.run(main(args.agent, session_state))
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - suppress ugly traceback
        console.print("\n\n[yellow]Interrupted[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
