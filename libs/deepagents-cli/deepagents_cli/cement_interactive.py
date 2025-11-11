"""Interactive mode for Cement-based DeepAgents CLI.

This module provides the interactive REPL loop with menu integration,
replacing the Questionary-based system with Cement prompts and Rich UI.
"""

import asyncio
import sys
from pathlib import Path

from .cement_menu_system import CementMenuSystem
from .commands import execute_bash_command, handle_command
from .config import SessionState, console
from .execution import execute_task
from .input import create_prompt_session
from .rich_ui import (
    display_ascii_banner,
    display_connection_status,
    display_server_error,
    display_tavily_warning,
    display_welcome,
)
from .tools import tavily_client
from .ui import TokenTracker


async def simple_cli_loop(
    agent, assistant_id: str | None, session_state: SessionState, baseline_tokens: int = 0
) -> None:
    """Main CLI loop with Cement/Rich integration.

    Args:
        agent: Compiled agent instance
        assistant_id: Agent identifier
        session_state: Session state object
        baseline_tokens: Baseline token count for tracking
    """
    from .server_client import is_server_available

    # Display banner and status
    display_ascii_banner()
    display_connection_status(is_server_available())

    if tavily_client is None:
        display_tavily_warning()

    display_welcome(session_state.auto_approve)

    # Create prompt session and token tracker
    session = create_prompt_session(assistant_id, session_state)
    token_tracker = TokenTracker()
    token_tracker.set_baseline(baseline_tokens)

    # Create menu system
    menu_system = CementMenuSystem(session_state, agent, token_tracker)

    while True:
        try:
            user_input = await session.prompt_async()
            user_input = user_input.strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            # Ctrl+C at prompt - exit the program
            console.print("\n[cyan]Goodbye! Happy coding! 👋[/cyan]", style="bold")
            break

        # Check if menu was requested via Ctrl+M
        if session_state.menu_requested:
            session_state.menu_requested = False  # Reset flag
            result = menu_system.show_main_menu()
            if result == "exit":
                console.print("\n[cyan]Goodbye! Happy coding! 👋[/cyan]", style="bold")
                break
            continue  # Return to prompt after menu

        if not user_input:
            continue

        # Check for slash commands first
        if user_input.startswith("/"):
            result = await handle_command(user_input, agent, token_tracker, session_state)
            if result == "exit":
                console.print("\n[cyan]Goodbye! Happy coding! 👋[/cyan]", style="bold")
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
            console.print("\n[cyan]Goodbye! Happy coding! 👋[/cyan]", style="bold")
            break

        await execute_task(user_input, agent, assistant_id, session_state, token_tracker)

        # Check if handoff was approved and needs thread switch
        if session_state.pending_handoff_child_id:
            child_id = session_state.pending_handoff_child_id
            session_state.thread_manager.switch_thread(child_id)
            session_state.pending_handoff_child_id = None  # Clear flag
            console.print()
            console.print(f"[green]✓ Switched to new thread: {child_id}[/green]")
            console.print()


async def start_interactive_mode(assistant_id: str, session_state: SessionState) -> None:
    """Start interactive mode with server management.

    Args:
        assistant_id: Agent identifier
        session_state: Session state object
    """
    from .config import USE_ASYNC_CHECKPOINTER, create_model
    from .server_client import is_server_available, start_server_if_needed

    # Check if server is running, offer to start if not
    if not is_server_available():
        console.print("[yellow]⚠ LangGraph server is not running[/yellow]")
        console.print()
        console.print(
            "The DeepAgents CLI requires the LangGraph server for thread management."
        )
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
            display_server_error(error_message)
            sys.exit(1)

    # Create the model (checks API keys)
    model = create_model()
    session_state.model = model

    # Initialize thread manager
    agent_dir = Path.home() / ".deepagents" / assistant_id
    from .thread_manager import ThreadManager

    thread_manager = ThreadManager(agent_dir, assistant_id)
    session_state.thread_manager = thread_manager

    # Create agent with conditional tools
    from .tools import http_request, web_search

    tools = [http_request]
    if tavily_client is not None:
        tools.append(web_search)

    if not USE_ASYNC_CHECKPOINTER:
        console.print(
            "[yellow]⚠ Warning: Async checkpointer disabled (not recommended)[/yellow]"
        )
        console.print(
            "[dim]Set DEEPAGENTS_USE_ASYNC_CHECKPOINTER=1 to enable (required for proper operation)[/dim]"
        )
        console.print()

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .agent import create_agent_with_config, get_system_prompt
    from .token_utils import calculate_baseline_tokens

    # Ensure agent directory exists before creating database
    agent_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_db = agent_dir / "checkpoints.db"

    try:
        # Keep context manager open for entire CLI session
        async with AsyncSqliteSaver.from_conn_string(
            str(checkpoint_db.resolve())
        ) as checkpointer:
            # Create agent with async checkpointer
            agent = create_agent_with_config(
                model, assistant_id, tools, checkpointer=checkpointer
            )

            # Calculate baseline token count for accurate token tracking
            system_prompt = get_system_prompt()
            baseline_tokens = calculate_baseline_tokens(model, agent_dir, system_prompt)

            # Run CLI loop - checkpointer stays open for entire session
            await simple_cli_loop(agent, assistant_id, session_state, baseline_tokens)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]❌ Error:[/bold red] {e}\n")
        raise
