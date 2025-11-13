"""Cement-based menu system for DeepAgents CLI with Rich/prompt_toolkit UX."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph
    from prompt_toolkit import PromptSession

from rich.markup import escape
from rich.panel import Panel

from .config import SessionState, console
from .rich_ui import RichPrompt, create_thread_table
from .thread_display import (
    check_server_availability,
    enrich_thread_with_server_data,
    format_thread_summary,
)
from .ui import TokenTracker, show_help
from .ui_constants import Colors

logger = logging.getLogger(__name__)


class CementMenuSystem:
    """Menu system using Rich prompts with arrow-key navigation and filtering."""

    def __init__(
        self,
        session_state: SessionState,
        token_tracker: TokenTracker,
        agent: CompiledStateGraph | None,
        prompt_session: PromptSession | None = None,
    ) -> None:
        """Initialize the Cement menu system.

        Args:
            session_state: Current session state
            token_tracker: Token usage tracker
            agent: Compiled agent (needed for persistence-aware deletes)
            prompt_session: Main PromptSession for unified lifecycle (REQUIRED for production)
        """
        self.session_state = session_state
        self.token_tracker = token_tracker
        self.agent = agent
        self.prompt_session = prompt_session

        # Warn if prompt_session is None (causes fallback to nested Application anti-pattern)
        if prompt_session is None:
            logger.warning(
                "CementMenuSystem initialized without prompt_session - "
                "menu selections will use fallback nested Application pattern. "
                "This may cause toolbar flickering and keyboard shortcut issues."
            )

        self.prompt = RichPrompt(console, session_state, prompt_session)

    async def show_main_menu(self) -> str | None:
        """Display the main menu and handle user selection."""
        panel = Panel(
            "[bold]Welcome to DeepAgents[/bold]\nUse arrows to navigate, Enter to select.",
            title="DeepAgents - Main Menu",
            border_style=Colors.PRIMARY,
            padding=(1, 2),
        )

        options = [
            ("threads", "[Threads] Browse and manage conversation history"),
            ("new_thread", "[New Thread] Start a fresh conversation"),
             ("handoff", "[Handoff Current Thread] Route through approval/refine flow"),
            ("tokens", "[Token Stats] View usage and cost information"),
            ("settings", "[Settings] Configure CLI preferences"),
            ("help", "[Help] Show available commands"),
            ("exit", "[Exit] Quit the application"),
        ]

        choice = await self.prompt.select_async(
            question="Choose an action:",
            choices=options,
            context_panel=panel,
        )

        if choice is None:
            return None

        return await self._handle_main_menu_action(choice)

    async def _handle_main_menu_action(self, action: str) -> str | None:
        """Route main menu selections to handlers."""
        handlers: dict[str, Any] = {
            "threads": self._show_thread_menu,
            "new_thread": self._handle_new_thread,
            "handoff": self._handle_handoff,
            "tokens": self._handle_tokens,
            "settings": self._show_settings_menu,
            "help": self._handle_help,
            "exit": self._handle_exit,
        }

        handler = handlers.get(action)
        if handler:
            return await handler()

        console.print(f"[yellow]Unknown action: {action}[/yellow]")
        return None

    async def _show_thread_menu(self) -> str | None:
        """Show thread management menu.

        Loop continues when user completes a thread action (returns 'back_to_threads').
        Loop exits when user selects 'back' (returns None) or result needs propagation.
        """
        import asyncio

        try:
            while True:
                try:
                    thread_manager = self.session_state.thread_manager
                    threads = thread_manager.list_threads()
                    current_id = thread_manager.get_current_thread_id()

                    if not threads:
                        panel = Panel(
                            f"[{Colors.WARNING}]No threads available yet.[/{Colors.WARNING}]\n\n"
                            "Create your first thread from the main menu!",
                            title="[bold]Thread Management[/bold]",
                            border_style=Colors.WARNING,
                        )
                        console.print(panel)
                        console.print()
                        await self._pause("Press Enter to return to main menu:")
                        return None

                    # Check server availability once for all threads
                    server_available = check_server_availability()

                    # Enrich threads with server data (or fallback to cached data)
                    enriched_threads = [
                        enrich_thread_with_server_data(
                            dict(thread), server_available=server_available
                        )
                        for thread in threads
                    ]

                    table = create_thread_table(enriched_threads, current_id)

                    # Add server-offline warning if applicable
                    if not server_available:
                        from rich.console import Group
                        from rich.text import Text

                        warning = Text()
                        warning.append("⚠  ", style="yellow bold")
                        warning.append("LangGraph server offline", style="yellow")
                        warning.append(" – showing local metadata only\n", style="dim")
                        warning.append(
                            "   Previews and metrics may be stale. Start server with: ",
                            style="dim",
                        )
                        warning.append("langgraph dev", style="cyan")

                        table_with_warning = Group(warning, table)
                        table_panel = Panel(
                            table_with_warning,
                            title=f"[bold {Colors.PRIMARY}]Thread Management[/bold {Colors.PRIMARY}]",
                            border_style=Colors.PRIMARY,
                            padding=(0, 1),
                        )
                    else:
                        table_panel = Panel(
                            table,
                            title=f"[bold {Colors.PRIMARY}]Thread Management[/bold {Colors.PRIMARY}]",
                            border_style=Colors.PRIMARY,
                            padding=(0, 1),
                        )

                    options = [
                        (thread["id"], format_thread_summary(thread, current_id))
                        for thread in enriched_threads
                    ]
                    options.append(("back", "[Back] Return to main menu"))

                    choice = await self.prompt.select_async(
                        question="Select a thread:",
                        choices=options,
                        default=current_id,
                        context_panel=table_panel,
                    )

                    if choice is None or choice == "back":
                        return None

                    result = await self._show_thread_actions(choice, current_id)
                    if result != "back_to_threads":
                        return result
                    # If result is "back_to_threads", loop continues

                except asyncio.CancelledError:
                    # Task cancelled - perform cleanup and propagate cancellation
                    raise

        finally:
            # Cleanup that always runs regardless of exit method
            # (Currently no resources to clean up, but pattern is in place)
            pass

    async def _show_thread_actions(self, thread_id: str, current_id: str) -> str | None:
        """Show actions for a selected thread."""
        thread_manager = self.session_state.thread_manager
        thread = thread_manager.get_thread(thread_id)
        if not thread:
            console.print("[red]Thread not found (may have been deleted)[/red]")
            return "back_to_threads"

        thread_name = thread.get("name", "Untitled")
        short_id = thread_id[:8] if len(thread_id) > 8 else thread_id

        options = []
        if thread_id != current_id:
            options.append(("switch", "[Switch] Activate this thread"))
        options.extend(
            [
                ("rename", "[Rename] Update this thread's name"),
                ("delete", "[Delete] Remove this thread"),
                ("back", "[Back] Return to thread list"),
            ]
        )

        choice = await self.prompt.select_async(
            question=f"Thread: {thread_name} ({short_id})",
            choices=options,
        )

        if choice is None:
            return "back_to_threads"

        if choice == "back":
            return "back_to_threads"

        if choice == "switch":
            thread_manager.switch_thread(thread_id)
            safe_name = escape(thread_name)
            console.print(f"[{Colors.SUCCESS}]✓ Switched to thread: {safe_name}[/{Colors.SUCCESS}]")
            console.print()
            await self._pause("Press Enter to return to menu:")
            return "back_to_threads"

        if choice == "rename":
            safe_old_name = escape(thread_name)

            def validate_name(text: str) -> bool | str:
                if len(text.strip()) == 0:
                    return "Thread name cannot be empty"
                return True

            new_name = await self.prompt.text_input_async(
                prompt_text=f"New name for '{safe_old_name}':",
                default=thread_name,
                validate=validate_name,
            )
            if new_name and new_name.strip() and new_name != thread_name:
                thread_manager.rename_thread(thread_id, new_name.strip())
                safe_new = escape(new_name.strip())
                console.print(
                    f"[{Colors.SUCCESS}]✓ Renamed thread to: {safe_new}[/{Colors.SUCCESS}]"
                )
            else:
                console.print("[dim]✓ Rename cancelled.[/dim]")
            console.print()
            await self._pause("Press Enter to return to menu:")
            return "back_to_threads"

        if choice == "delete":
            message_count = thread.get("message_count", 0)
            tokens = thread.get("total_tokens", 0)
            details = {
                "Messages": message_count,
                "Tokens": f"{tokens:,}",
            }

            confirmed = await self.prompt.dangerous_confirmation_async(
                action="Delete Thread",
                target=thread_name,
                details=details,
                confirmation_text="DELETE",
            )
            if confirmed:
                try:
                    thread_manager.delete_thread(thread_id, self.agent)
                    safe_name = escape(thread_name)
                    console.print(
                        f"[{Colors.SUCCESS}]✓ Deleted thread: {safe_name}[/{Colors.SUCCESS}]"
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    console.print(
                        f"[{Colors.ERROR}]Failed to delete thread: {exc}[/{Colors.ERROR}]"
                    )
            console.print()
            await self._pause("Press Enter to return to menu:")
            return "back_to_threads"

        # Defensive fallback - should never be reached if all choices are handled above
        error_message = (
            f"Unexpected choice '{choice}' in _show_thread_actions. "
            f"This should never happen - all valid choices should be handled explicitly above."
        )
        logger.error(error_message, exc_info=True)  # Log before raising for audit trail
        raise RuntimeError(error_message)

    async def _handle_new_thread(self) -> str | None:
        """Handle creating a new thread."""
        console.print(f"[bold {Colors.PRIMARY}]Create New Thread[/bold {Colors.PRIMARY}]")
        console.print()

        name = await self.prompt.text_input_async(
            prompt_text="Thread name (optional, press Enter for default):",
            default="",
        )
        if name is None:
            return None

        thread_manager = self.session_state.thread_manager
        new_thread_id = thread_manager.create_thread(name=name if name else None)
        thread_name = thread_manager.get_thread(new_thread_id).get("name", "New thread")
        console.print()
        console.print(f"[{Colors.SUCCESS}]✓ Created new thread: {thread_name}[/{Colors.SUCCESS}]")
        console.print()
        await self._pause("Press Enter to return to menu:")
        return None

    async def _handle_tokens(self) -> str | None:
        """Handle showing token statistics."""
        console.print(f"[bold {Colors.PRIMARY}]Token Statistics[/bold {Colors.PRIMARY}]")
        console.print()
        self.token_tracker.display_session()
        console.print()
        await self._pause("Press Enter to return to menu:")
        return None

    async def _show_settings_menu(self) -> str | None:
        """Show settings submenu."""
        auto_approve_status = "ON" if self.session_state.auto_approve else "OFF"
        options = [
            (
                "toggle_auto_approve",
                f"[Auto-approve: {auto_approve_status}] Toggle tool execution approval",
            ),
            ("back", "[Back] Return to main menu"),
        ]

        choice = await self.prompt.select_async(
            question="Settings:",
            choices=options,
        )

        if choice is None or choice == "back":
            return None

        if choice == "toggle_auto_approve":
            self.session_state.auto_approve = not self.session_state.auto_approve
            status = "enabled" if self.session_state.auto_approve else "disabled"
            console.print(f"[{Colors.SUCCESS}]✓ Auto-approve {status}[/{Colors.SUCCESS}]")
            console.print()
            await self._pause("Press Enter to return to menu:")
            return None

        return None

    async def _handle_help(self) -> str | None:
        """Handle showing help information."""
        show_help()
        console.print()
        await self._pause("Press Enter to return to menu:")
        return None

    async def _handle_exit(self) -> str | None:
        """Handle exit confirmation."""
        confirmed = await self.prompt.confirm_async("Exit DeepAgents CLI?", default=True)
        if confirmed:
            return "exit"
        return None

    async def _handle_handoff(self) -> str | None:
        """Route to the handoff flow used by slash commands."""
        if not self.session_state:
            console.print()
            console.print("[red]Session state not available for handoff.[/red]")
            console.print()
            return None

        if self.agent is None:
            console.print()
            console.print("[red]Agent is not initialized; cannot run handoff.[/red]")
            console.print()
            return None

        # Import lazily to avoid circular dependency at module load time
        from .commands import handle_handoff_command

        await handle_handoff_command(
            args="",
            agent=self.agent,
            session_state=self.session_state,
            prompt_session=self.prompt_session,
        )
        console.print()
        await self._pause("Press Enter to return to menu:")
        return None

    async def _pause(self, message: str) -> None:
        """Display a press-enter style pause without blocking the event loop."""
        await self.prompt.text_input_async(prompt_text=message, default="")
