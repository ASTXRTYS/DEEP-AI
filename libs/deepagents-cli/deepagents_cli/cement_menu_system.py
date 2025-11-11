"""Cement-based menu system for DeepAgents CLI.

Replaces the Questionary menu system with Cement prompts and Rich UI components.
Provides numbered menu selection with beautiful visual presentation.
"""

from typing import Any

from rich.panel import Panel

from .config import SessionState, console
from .rich_ui import RichPrompt, create_thread_table
from .ui import TokenTracker, show_help


class CementMenuSystem:
    """Menu system using Cement prompts and Rich UI.

    Provides hierarchical navigation with numbered selection,
    beautiful panels, and enhanced visual feedback.
    """

    def __init__(self, session_state: SessionState, agent, token_tracker: TokenTracker):
        """Initialize the Cement menu system.

        Args:
            session_state: Current session state
            agent: Compiled agent instance
            token_tracker: Token usage tracker
        """
        self.session_state = session_state
        self.agent = agent
        self.token_tracker = token_tracker
        self.prompt = RichPrompt(console)

    def show_main_menu(self) -> str | None:
        """Display the main menu and handle user selection.

        Returns:
            The action result ("exit" to quit, None to continue)
        """
        options = [
            ("threads", "🧵  Thread Management    Browse and manage conversation threads"),
            ("new_thread", "🚀  New Thread          Start a fresh conversation"),
            ("tokens", "📊  Token Statistics    View usage and cost information"),
            ("settings", "⚙️   Settings            Configure CLI preferences"),
            ("help", "❓  Help & Commands     Show available commands"),
            ("exit", "🚪  Exit                Quit the application"),
        ]

        choice = self.prompt.menu(
            title="🤖 DEEP AGENTS - Main Menu",
            options=options,
            subtitle="What would you like to do?",
        )

        if choice is None:  # Cancelled
            return None

        # Route to appropriate handler
        return self._handle_main_menu_action(choice)

    def _handle_main_menu_action(self, action: str) -> str | None:
        """Handle main menu action selection.

        Args:
            action: Selected action

        Returns:
            Action result
        """
        handlers = {
            "threads": self._show_thread_menu,
            "new_thread": self._handle_new_thread,
            "tokens": self._handle_tokens,
            "settings": self._show_settings_menu,
            "help": self._handle_help,
            "exit": self._handle_exit,
        }

        handler = handlers.get(action)
        if handler:
            return handler()

        console.print(f"[yellow]Unknown action: {action}[/yellow]")
        return None

    def _show_thread_menu(self) -> str | None:
        """Show thread management menu.

        Returns:
            Action result
        """
        # Get all threads
        thread_manager = self.session_state.thread_manager
        threads = thread_manager.list_threads()
        current_id = thread_manager.get_current_thread_id()

        if not threads:
            console.clear()
            panel = Panel(
                "[yellow]No threads available yet.[/yellow]\n\n"
                "Create your first thread from the main menu!",
                title="[bold]📋 Thread Management[/bold]",
                border_style="yellow",
            )
            console.print(panel)
            console.print()
            input("Press Enter to return to main menu...")
            return None

        # Display thread table
        console.clear()
        table = create_thread_table(threads, current_id)
        console.print(table)
        console.print()

        # Build options for thread selection
        options = []
        for i, thread in enumerate(threads):
            thread_id = thread["id"]
            name = thread.get("name", "Untitled")
            thread_id_short = thread_id[:8] if len(thread_id) > 8 else thread_id
            options.append((thread_id, f"{name}  ({thread_id_short})"))

        options.append(("back", "« Back to Main Menu"))

        choice = self.prompt.menu(
            title="Select a Thread",
            options=options,
            subtitle="Choose a thread to view actions",
            show_numbers=True,
        )

        if choice is None or choice == "back":
            return None

        # Show thread actions submenu
        return self._show_thread_actions(choice, current_id)

    def _show_thread_actions(self, thread_id: str, current_id: str) -> str | None:
        """Show actions for a selected thread.

        Args:
            thread_id: Selected thread ID
            current_id: Current active thread ID

        Returns:
            Action result
        """
        # Get thread info
        thread_manager = self.session_state.thread_manager
        thread = thread_manager.get_thread(thread_id)

        if not thread:
            console.print("[red]Thread not found[/red]")
            return None

        thread_name = thread.get("name", "Untitled")
        thread_id_short = thread_id[:8] if len(thread_id) > 8 else thread_id

        # Build action menu
        options = []

        if thread_id != current_id:
            options.append(("switch", "🔄  Switch to this thread"))

        options.extend(
            [
                ("rename", "✏️   Rename this thread"),
                ("delete", "🗑️   Delete this thread"),
                ("back", "« Back to Thread List"),
            ]
        )

        choice = self.prompt.menu(
            title=f"Thread: {thread_name}",
            options=options,
            subtitle=f"ID: {thread_id_short}",
        )

        if choice is None or choice == "back":
            return None

        # Execute action
        if choice == "switch":
            thread_manager.switch_thread(thread_id)
            console.print(f"[green]✓ Switched to thread: {thread_name}[/green]")
            console.print()
            input("Press Enter to continue...")

        elif choice == "rename":
            new_name = self.prompt.text_input(
                f"New name for '{thread_name}':", default=thread_name
            )
            if new_name and new_name != thread_name:
                thread_manager.rename_thread(thread_id, new_name)
                console.print(f"[green]✓ Renamed thread to: {new_name}[/green]")
                console.print()
                input("Press Enter to continue...")

        elif choice == "delete":
            # Confirm deletion
            message_count = thread.get("message_count", 0)
            tokens = thread.get("total_tokens", 0)

            console.print()
            panel = Panel(
                f"[bold]Thread:[/bold] {thread_name}\n"
                f"[bold]Messages:[/bold] {message_count}\n"
                f"[bold]Tokens:[/bold] {tokens:,}\n\n"
                "[yellow]⚠ This action cannot be undone![/yellow]",
                title="[bold red]Delete Thread[/bold red]",
                border_style="red",
            )
            console.print(panel)
            console.print()

            confirmed = self.prompt.confirm(
                f"Delete thread '{thread_name}'?", default=False
            )

            if confirmed:
                try:
                    thread_manager.delete_thread(thread_id, self.agent)
                    console.print(f"[green]✓ Deleted thread: {thread_name}[/green]")
                except Exception as e:
                    console.print(f"[red]Failed to delete thread: {e}[/red]")

                console.print()
                input("Press Enter to continue...")

        return None

    def _handle_new_thread(self) -> str | None:
        """Handle creating a new thread.

        Returns:
            Action result
        """
        console.clear()
        console.print("[bold cyan]Create New Thread[/bold cyan]")
        console.print()

        name = self.prompt.text_input(
            "Thread name (optional, press Enter for default):", default=""
        )

        if name is None:  # Cancelled
            return None

        # Create thread
        thread_manager = self.session_state.thread_manager
        new_thread_id = thread_manager.create_thread(name=name if name else None)

        thread_name = thread_manager.get_thread(new_thread_id).get("name", "New thread")
        console.print()
        console.print(f"[green]✓ Created new thread: {thread_name}[/green]")
        console.print()
        input("Press Enter to continue...")

        return None

    def _handle_tokens(self) -> str | None:
        """Handle showing token statistics.

        Returns:
            Action result
        """
        console.clear()
        console.print("[bold cyan]📊 Token Statistics[/bold cyan]")
        console.print()
        self.token_tracker.display_session()
        console.print()
        input("Press Enter to return to menu...")

        return None

    def _show_settings_menu(self) -> str | None:
        """Show settings submenu.

        Returns:
            Action result
        """
        # Get current settings
        auto_approve_status = "ON" if self.session_state.auto_approve else "OFF"

        options = [
            (
                "toggle_auto_approve",
                f"⚡  Auto-approve: {auto_approve_status}     Toggle tool auto-approval",
            ),
            ("back", "« Back to Main Menu"),
        ]

        choice = self.prompt.menu(
            title="⚙️  Settings",
            options=options,
            subtitle="Configure CLI Options",
        )

        if choice is None or choice == "back":
            return None

        # Handle settings actions
        if choice == "toggle_auto_approve":
            self.session_state.auto_approve = not self.session_state.auto_approve
            status = "enabled" if self.session_state.auto_approve else "disabled"
            console.print(f"[green]✓ Auto-approve {status}[/green]")
            console.print()
            input("Press Enter to continue...")

            # Show menu again to reflect new state
            return self._show_settings_menu()

        return None

    def _handle_help(self) -> str | None:
        """Handle showing help.

        Returns:
            Action result
        """
        console.clear()
        show_help()
        console.print()
        input("Press Enter to return to menu...")

        return None

    def _handle_exit(self) -> str:
        """Handle exit confirmation.

        Returns:
            "exit" to signal the CLI should quit
        """
        confirmed = self.prompt.confirm("Exit DeepAgents CLI?", default=True)

        if confirmed:
            return "exit"
        return None
