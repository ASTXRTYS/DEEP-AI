"""Main entry point and CLI loop for deepagents."""

import argparse
import asyncio
import sys
from pathlib import Path

from deepagents_cli.agent import create_agent_with_config, list_agents, reset_agent
from deepagents_cli.commands import execute_bash_command, handle_command
from deepagents_cli.config import (
    COLORS,
    DEEP_AGENTS_ASCII,
    SessionState,
    console,
    create_model,
    USE_ASYNC_CHECKPOINTER,
)
from deepagents_cli.execution import execute_task
from deepagents_cli.input import create_prompt_session
from deepagents_cli.integrations.sandbox_factory import (
    create_sandbox,
    get_default_working_dir,
)
from deepagents_cli.backends_compat import SandboxBackendProtocol
from deepagents_cli.thread_manager import ThreadManager
from deepagents_cli.tools import fetch_url, http_request, tavily_client, web_search
from deepagents_cli.ui import TokenTracker, show_help


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
        console.print("[bold red]Missing required CLI dependencies![/bold red]")
        console.print()
        console.print("The following packages are required to use the deepagents CLI:")
        for pkg in missing:
            console.print(f"  • {pkg}")
        console.print()
        console.print(
            "Install them with: [cyan]pip install 'deepagents[cli]'[/cyan] "
            "or add them to your environment."
        )
        console.print("Full dependency set:")
        console.print("  [cyan]pip install 'deepagents[cli]'[/cyan]")
        sys.exit(1)


def parse_args(argv: list[str] | None = None):
    """Parse command line arguments."""
    commands = {"list", "help", "reset"}

    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)

    if argv:
        first = argv[0]
        if not first.startswith("-") and first not in commands:
            console.print(
                f"[dim]Interpreting '{first}' as --agent {first} (legacy positional syntax)[/dim]"
            )
            argv = ["--agent", first, *argv[1:]]

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
    parser.add_argument(
        "--sandbox",
        choices=["none", "modal", "daytona", "runloop"],
        default="none",
        help="Remote sandbox for code execution (default: none - local only)",
    )
    parser.add_argument(
        "--sandbox-id",
        help="Existing sandbox ID to reuse (skips creation and cleanup)",
    )
    parser.add_argument(
        "--sandbox-setup",
        help="Path to setup script to run in sandbox after creation",
    )
    parser.add_argument(
        "-h",
        "--help",
        action="help",
        help="Show this help message and exit (same as 'deepagents help').",
    )

    return parser.parse_args(argv)


async def simple_cli(
    agent,
    assistant_id: str | None,
    session_state,
    baseline_tokens: int = 0,
    backend=None,
    sandbox_type: str | None = None,
    setup_script_path: str | None = None,
):
    """Main CLI loop.

    Args:
        backend: Backend for file operations (CompositeBackend)
        sandbox_type: Type of sandbox being used (e.g., "modal", "runloop", "daytona").
                     If None, running in local mode.
        sandbox_id: ID of the active sandbox
        setup_script_path: Path to setup script that was run (if any)
    """
    console.clear()
    console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
    console.print()

    if backend and isinstance(backend, SandboxBackendProtocol):
        sandbox_id: str | None = backend.id
    else:
        sandbox_id = None

    try:
        from deepagents_cli.server_client import is_server_available

        if is_server_available():
            console.print("[green]● Connected to LangGraph server[/green]")
            console.print()
    except Exception:
        console.print("[yellow]⚠ Unable to reach LangGraph server[/yellow]")
        console.print()

    # Display sandbox info persistently (survives console.clear())
    if sandbox_type and sandbox_id:
        console.print(f"[yellow]⚡ {sandbox_type.capitalize()} sandbox: {sandbox_id}[/yellow]")
        if setup_script_path:
            console.print(
                f"[green]✓ Setup script ({setup_script_path}) completed successfully[/green]"
            )
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

    if sandbox_type:
        working_dir = get_default_working_dir(sandbox_type)
        console.print(f"  [dim]Local CLI directory: {Path.cwd()}[/dim]")
        console.print(f"  [dim]Code execution: Remote sandbox ({working_dir})[/dim]")
    else:
        console.print(f"  [dim]Working directory: {Path.cwd()}[/dim]")

    console.print()

    if session_state.auto_approve:
        console.print(
            "  [yellow]⚡ Auto-approve: ON[/yellow] [dim](tools run without confirmation)[/dim]"
        )
        console.print()

    console.print(
        "  Tips: Enter to submit, Alt+Enter for newline, Ctrl+E for editor, "
        "Ctrl+T to toggle auto-approve, Ctrl+C to interrupt",
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
            if session_state.exit_hint_handle:
                session_state.exit_hint_handle.cancel()
                session_state.exit_hint_handle = None
            session_state.exit_hint_until = None
            user_input = user_input.strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            console.print("\nGoodbye!", style=COLORS["primary"])
            break

        if session_state.menu_requested:
            session_state.menu_requested = False
            from deepagents_cli.menu_system import MenuSystem

            menu_system = MenuSystem(session_state, agent, token_tracker)
            result = await menu_system.show_main_menu()
            if result == "exit":
                console.print("\nGoodbye!", style=COLORS["primary"])
                break
            # Regardless of selection (handled or cancelled), return to prompt
            continue

        if not user_input:
            continue

        # Check for slash commands first
        if user_input.startswith("/"):
            result = await handle_command(user_input, agent, token_tracker, session_state)
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

        await execute_task(
            user_input, agent, assistant_id, session_state, token_tracker, backend=backend
        )

        if session_state.pending_handoff_child_id:
            child_id = session_state.pending_handoff_child_id
            if session_state.thread_manager:
                session_state.thread_manager.switch_thread(child_id)
            session_state.pending_handoff_child_id = None
            console.print()
            console.print(f"[green]✓ Switched to new thread: {child_id}[/green]")
            console.print()


def _warn_if_async_checkpointer_disabled() -> None:
    if not USE_ASYNC_CHECKPOINTER:
        console.print("[yellow]⚠ Warning: Async checkpointer disabled (not recommended)[/yellow]")
        console.print(
            "[dim]Set DEEPAGENTS_USE_ASYNC_CHECKPOINTER=1 to enable (required for proper operation)[/dim]"
        )
        console.print()


async def _run_agent_session(
    model,
    assistant_id: str,
    session_state,
    sandbox_backend=None,
    sandbox_type: str | None = None,
    setup_script_path: str | None = None,
):
    """Helper to create agent and run CLI session.

    Extracted to avoid duplication between sandbox and local modes.

    Args:
        model: LLM model to use
        assistant_id: Agent identifier for memory storage
        session_state: Session state with auto-approve settings
        sandbox_backend: Optional sandbox backend for remote execution
        sandbox_type: Type of sandbox being used
        setup_script_path: Path to setup script that was run (if any)
    """
    # Create agent with conditional tools
    tools = [http_request, fetch_url]
    if tavily_client is not None:
        tools.append(web_search)

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from .agent import get_system_prompt
    from .token_utils import calculate_baseline_tokens

    agent_dir = Path.home() / ".deepagents" / assistant_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_db = agent_dir / "checkpoints.db"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_db.resolve())) as checkpointer:
        agent, composite_backend = create_agent_with_config(
            model,
            assistant_id,
            tools,
            checkpointer=checkpointer,
            sandbox=sandbox_backend,
            sandbox_type=sandbox_type,
        )

        system_prompt = get_system_prompt()
        baseline_tokens = calculate_baseline_tokens(model, agent_dir, system_prompt)

        await simple_cli(
            agent,
            assistant_id,
            session_state,
            baseline_tokens,
            backend=composite_backend,
            sandbox_type=sandbox_type,
            setup_script_path=setup_script_path,
        )


def _ensure_server_running() -> None:
    from deepagents_cli.server_client import is_server_available, start_server_if_needed

    if is_server_available():
        return

    console.print("[yellow]⚠ LangGraph server is not running[/yellow]")
    console.print()
    console.print("The DeepAgents CLI requires the LangGraph server for thread management.")
    console.print(
        "This enables features like message history, thread naming, and Studio integration."
    )
    console.print()

    console.print("[dim]Starting LangGraph dev server...[/dim]")
    started, error_message = start_server_if_needed()
    if started:
        console.print("[green]✓ Server started successfully![/green]")
        console.print()
        return

    console.print("[red]✗ Failed to start server automatically[/red]")
    console.print()
    if error_message:
        console.print(f"[red]{error_message}[/red]")
        console.print()
    console.print("Please start the server manually in another terminal:")
    console.print("  [cyan]langgraph dev[/cyan]")
    console.print()
    console.print("Then restart the CLI.")
    sys.exit(1)


async def main(
    assistant_id: str,
    session_state,
    sandbox_type: str = "none",
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
):
    """Main entry point with conditional sandbox support.

    Args:
        assistant_id: Agent identifier for memory storage
        session_state: Session state with auto-approve settings
        sandbox_type: Type of sandbox ("none", "modal", "runloop", "daytona")
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run in sandbox
    """
    _ensure_server_running()
    _warn_if_async_checkpointer_disabled()

    model = create_model()
    session_state.model = model

    agent_dir = Path.home() / ".deepagents" / assistant_id
    thread_manager = ThreadManager(agent_dir, assistant_id)
    session_state.thread_manager = thread_manager

    # Branch 1: User wants a sandbox
    if sandbox_type != "none":
        # Try to create sandbox
        try:
            console.print()
            with create_sandbox(
                sandbox_type, sandbox_id=sandbox_id, setup_script_path=setup_script_path
            ) as sandbox_backend:
                console.print(f"[yellow]⚡ Remote execution enabled ({sandbox_type})[/yellow]")
                console.print()

                await _run_agent_session(
                    model,
                    assistant_id,
                    session_state,
                    sandbox_backend,
                    sandbox_type=sandbox_type,
                    setup_script_path=setup_script_path,
                )
        except (ImportError, ValueError, RuntimeError, NotImplementedError) as e:
            # Sandbox creation failed - fail hard (no silent fallback)
            console.print()
            console.print("[red]❌ Sandbox creation failed[/red]")
            console.print(f"[dim]{e}[/dim]")
            sys.exit(1)
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted[/yellow]")
            sys.exit(0)
        except Exception as e:
            console.print(f"\n[bold red]❌ Error:[/bold red] {e}\n")
            console.print_exception()
            sys.exit(1)

    # Branch 2: User wants local mode (none or default)
    else:
        try:
            await _run_agent_session(model, assistant_id, session_state, sandbox_backend=None)
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted[/yellow]")
            sys.exit(0)
        except Exception as e:
            console.print(f"\n[bold red]❌ Error:[/bold red] {e}\n")
            console.print_exception()
            sys.exit(1)


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
            asyncio.run(
                main(
                    args.agent,
                    session_state,
                    args.sandbox,
                    args.sandbox_id,
                    args.sandbox_setup,
                )
            )
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - suppress ugly traceback
        console.print("\n\n[yellow]Interrupted[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
