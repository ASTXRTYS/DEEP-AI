"""Action handlers for menu selections.

Implements the logic for each menu action, coordinating with
existing CLI components (thread manager, commands, etc.).
"""

from typing import TYPE_CHECKING, Any

import questionary

from ..config import console
from ..ui import show_help
from ..ui_components import create_header_panel, create_warning_panel
from ..ui_constants import Icons
from .menus import (
    get_settings_menu_choices,
    get_thread_action_choices,
    get_thread_list_choices,
)
from .styles import PRIMARY_STYLE, WARNING_STYLE

if TYPE_CHECKING:
    from .core import MenuSystem


class MenuHandlers:
    """Handles menu action execution.

    Each handler corresponds to a menu selection and coordinates
    with existing CLI functionality.
    """

    def __init__(self, menu_system: "MenuSystem"):
        """Initialize handlers with reference to menu system.

        Args:
            menu_system: The MenuSystem instance
        """
        self.menu_system = menu_system
        self.session_state = menu_system.session_state
        self.agent = menu_system.agent
        self.token_tracker = menu_system.token_tracker

    async def handle_action(self, action: str, context: dict | None = None) -> Any:
        """Route action to appropriate handler.

        Args:
            action: The action value from menu selection
            context: Optional context data

        Returns:
            Result from the handler
        """
        context = context or {}

        # Main menu actions
        handlers = {
            "threads": self.handle_threads_menu,
            "new_thread": self.handle_new_thread,
            "tokens": self.handle_tokens,
            "handoff": self.handle_handoff,
            "settings": self.handle_settings_menu,
            "help": self.handle_help,
            "exit": self.handle_exit,
        }

        handler = handlers.get(action)
        if handler:
            return await handler(context)

        # Unknown action
        console.print(f"[yellow]Unknown action: {action}[/yellow]")
        return None

    async def handle_threads_menu(self, context: dict) -> None:
        """Handle the threads submenu flow.

        Shows thread list, allows selection, then shows thread actions.
        """
        self.menu_system.push_menu("Threads")

        try:
            # Get all threads
            thread_manager = self.session_state.thread_manager
            threads = thread_manager.list_threads()
            current_id = thread_manager.get_current_thread_id()

            # Show header
            console.print()
            header = create_header_panel(
                f"{Icons.THREAD} Thread Management", "Use ↑↓ to navigate, Enter to select"
            )
            console.print(header)
            console.print()

            # Get thread choices
            choices = get_thread_list_choices(threads, current_id)

            # Show thread list with search if > 5 threads
            use_search = len(threads) > 5

            selected_thread_id = await questionary.select(
                "Select a thread:" if not use_search else "Select a thread:\n  (type to search...)",
                choices=choices,
                style=PRIMARY_STYLE,
                use_arrow_keys=True,
                use_shortcuts=False,  # Thread IDs would conflict
                use_search_filter=use_search,
                qmark="▶",
                pointer="●",
                instruction="(↑↓ navigate, Enter select, type to search)"
                if use_search
                else "(↑↓ navigate, Enter select)",
            ).ask_async()

            if selected_thread_id is None:  # Cancelled
                self.menu_system.pop_menu()
                return

            # Show thread actions submenu
            await self.handle_thread_actions(selected_thread_id, current_id)

        except KeyboardInterrupt:
            pass
        finally:
            self.menu_system.pop_menu()

    async def handle_thread_actions(self, thread_id: str, current_id: str) -> None:
        """Handle thread action submenu.

        Args:
            thread_id: Selected thread ID
            current_id: Current active thread ID
        """
        self.menu_system.push_menu("Thread Actions")

        try:
            # Get thread info for header
            thread_manager = self.session_state.thread_manager
            thread = thread_manager.get_thread(thread_id)
            if not thread:
                console.print("[red]Thread not found[/red]")
                self.menu_system.pop_menu()
                return

            thread_name = thread.get("name", "Untitled")
            thread_id_short = thread_id[:8] if len(thread_id) > 8 else thread_id

            # Show header
            console.print()
            header = create_header_panel(
                f"{Icons.THREAD} {thread_name}", f"Thread ID: {thread_id_short}"
            )
            console.print(header)
            console.print()

            # Get action choices
            choices = get_thread_action_choices(thread_id, current_id)

            action = await questionary.select(
                "Choose an action:",
                choices=choices,
                style=PRIMARY_STYLE,
                use_arrow_keys=True,
                use_shortcuts=True,
                qmark="▶",
                pointer="●",
                instruction="(↑↓ navigate, Enter select, or press shortcut key)",
            ).ask_async()

            if action is None or action == "back":
                self.menu_system.pop_menu()
                return

            # Execute action
            if action == "switch":
                thread_manager.switch_thread(thread_id)
                console.print(f"[green]✓[/green] Switched to thread: {thread_name}")
            elif action == "rename":
                await self.handle_rename_thread(thread_id, thread_name)
            elif action == "delete":
                await self.handle_delete_thread(thread_id, thread_name)

        except KeyboardInterrupt:
            pass
        finally:
            self.menu_system.pop_menu()

    async def handle_rename_thread(self, thread_id: str, current_name: str) -> None:
        """Handle thread renaming.

        Args:
            thread_id: Thread ID to rename
            current_name: Current thread name
        """
        new_name = await questionary.text(
            f"New name for thread (current: {current_name}):",
            default=current_name,
            style=PRIMARY_STYLE,
            qmark="✎",
            instruction="(Enter to confirm, Ctrl+C to cancel)",
        ).ask_async()

        if new_name and new_name != current_name:
            self.session_state.thread_manager.rename_thread(thread_id, new_name)
            console.print(f"[green]✓[/green] Renamed thread to: {new_name}")

    async def handle_delete_thread(self, thread_id: str, thread_name: str) -> None:
        """Handle thread deletion with confirmation.

        Args:
            thread_id: Thread ID to delete
            thread_name: Thread name for confirmation
        """
        # Get thread stats for confirmation
        thread_manager = self.session_state.thread_manager
        thread = thread_manager.get_thread(thread_id)

        message_count = thread.get("message_count", 0) if thread else 0
        tokens = thread.get("total_tokens", 0) if thread else 0

        # Show warning
        console.print()
        warning_content = (
            f"Thread: [bold]{thread_name}[/bold]\n"
            f"Messages: {message_count}\n"
            f"Tokens: {tokens:,}\n\n"
            "[yellow]This action cannot be undone![/yellow]"
        )
        warning_panel = create_warning_panel(warning_content, "Delete Thread")
        console.print(warning_panel)
        console.print()

        # Confirm deletion
        confirmed = await questionary.confirm(
            'Type "DELETE" to confirm deletion:',
            default=False,
            style=WARNING_STYLE,
            qmark="⚠️",
            instruction="(this will permanently delete the thread)",
        ).ask_async()

        if confirmed:
            try:
                thread_manager.delete_thread(thread_id, self.agent)
                console.print(f"[green]✓[/green] Deleted thread: {thread_name}")
            except Exception as e:
                console.print(f"[red]Failed to delete thread: {e}[/red]")

    async def handle_new_thread(self, context: dict) -> None:
        """Handle creating a new thread."""
        # Get optional thread name
        name = await questionary.text(
            "Thread name (optional):",
            default="",
            style=PRIMARY_STYLE,
            qmark="📝",
            instruction="(Enter to create with default name, Ctrl+C to cancel)",
        ).ask_async()

        if name is None:  # Cancelled
            return

        # Create thread
        thread_manager = self.session_state.thread_manager
        new_thread_id = thread_manager.create_thread(name=name if name else None)

        thread_name = thread_manager.get_thread(new_thread_id).get("name", "New thread")
        console.print(f"[green]✓[/green] Created new thread: {thread_name}")

    async def handle_tokens(self, context: dict) -> None:
        """Handle showing token statistics."""
        console.print()
        self.token_tracker.display_session()
        console.print()

        # Wait for keypress to return
        await questionary.press_any_key_to_continue(
            "Press any key to return to menu...",
            style=PRIMARY_STYLE,
        ).ask_async()

    async def handle_handoff(self, context: dict) -> None:
        """Handle thread handoff."""
        console.print()
        console.print("[yellow]Handoff functionality - coming soon![/yellow]")
        console.print("This will create a child thread with a summary of the current conversation.")
        console.print()

        await questionary.press_any_key_to_continue(
            "Press any key to return to menu...",
            style=PRIMARY_STYLE,
        ).ask_async()

    async def handle_settings_menu(self, context: dict) -> None:
        """Handle settings submenu."""
        self.menu_system.push_menu("Settings")

        try:
            # Show header
            console.print()
            header = create_header_panel(f"{Icons.SETTINGS} Settings", "Configure CLI options")
            console.print(header)
            console.print()

            choices = get_settings_menu_choices(self.session_state)

            action = await questionary.select(
                "Configure options:",
                choices=choices,
                style=PRIMARY_STYLE,
                use_arrow_keys=True,
                use_shortcuts=True,
                qmark="▶",
                pointer="●",
                instruction="(↑↓ navigate, Enter select, or press shortcut key)",
            ).ask_async()

            if action is None or action == "back":
                self.menu_system.pop_menu()
                return

            # Handle settings actions
            if action == "toggle_auto_approve":
                self.session_state.auto_approve = not self.session_state.auto_approve
                status = "enabled" if self.session_state.auto_approve else "disabled"
                console.print(f"[green]✓[/green] Auto-approve {status}")

                # Show menu again to reflect new state
                await self.handle_settings_menu(context)

        except KeyboardInterrupt:
            pass
        finally:
            self.menu_system.pop_menu()

    async def handle_help(self, context: dict) -> None:
        """Handle showing help."""
        console.print()
        show_help(self.session_state.banner_variant)
        console.print()

        await questionary.press_any_key_to_continue(
            "Press any key to return to menu...",
            style=PRIMARY_STYLE,
        ).ask_async()

    async def handle_exit(self, context: dict) -> str:
        """Handle exit confirmation.

        Returns:
            "exit" to signal the CLI should quit
        """
        confirmed = await questionary.confirm(
            "Exit DeepAgents CLI?",
            default=True,
            style=PRIMARY_STYLE,
            qmark="🚪",
        ).ask_async()

        if confirmed:
            return "exit"
        return None
