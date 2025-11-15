"""Core menu navigation system.

Provides the MenuSystem class that manages hierarchical menu navigation,
breadcrumb trails, and menu state.
"""

from typing import Any

import questionary

from ..config import SessionState, console
from ..ui import TokenTracker
from ..ui_components import create_header_panel
from ..ui_constants import Icons
from .handlers import MenuHandlers
from .menus import get_main_menu_choices
from .styles import PRIMARY_STYLE


class MenuSystem:
    """Central menu navigation and state management.

    Manages a stack-based navigation system with breadcrumb trails,
    menu history, and context-aware menu generation.
    """

    def __init__(self, session_state: SessionState, agent, token_tracker: TokenTracker):
        """Initialize the menu system.

        Args:
            session_state: Current session state with thread manager and settings
            agent: The compiled agent instance
            token_tracker: Token usage tracker
        """
        self.session_state = session_state
        self.agent = agent
        self.token_tracker = token_tracker
        self.menu_stack: list[str] = []  # For breadcrumb trail
        self.history: dict[str, Any] = {}  # Remember last selections per menu
        self.handlers = MenuHandlers(self)

    async def show_main_menu(self) -> str | None:
        """Display the main menu and handle user selection.

        Returns:
            The selected action value, or None if cancelled (Ctrl+C)
        """
        self.push_menu("Main Menu")

        # Get dynamic choices based on current state
        choices = get_main_menu_choices(self.session_state)

        # Show header with branding
        console.print()
        header = create_header_panel(f"{Icons.AGENT} DEEP AGENTS", "Main Menu")
        console.print(header)
        console.print()

        try:
            choice = await questionary.select(
                "Choose an action:",
                choices=choices,
                style=PRIMARY_STYLE,
                use_arrow_keys=True,
                use_shortcuts=False,
                qmark="▶",
                pointer="●",
                instruction="(↑↓ navigate, Enter select)",
            ).ask_async()

            if choice is None:  # Ctrl+C pressed
                self.pop_menu()
                return None

            # Route to appropriate handler
            result = await self.handlers.handle_action(choice)
            self.pop_menu()
            return result

        except KeyboardInterrupt:
            self.pop_menu()
            return None

    async def navigate_to(self, menu_name: str, context: dict | None = None) -> Any:
        """Navigate to a specific menu with optional context.

        Args:
            menu_name: Name of the menu to show
            context: Optional context data for the menu

        Returns:
            Result from the menu handler
        """
        return await self.handlers.handle_action(menu_name, context or {})

    def push_menu(self, menu_name: str) -> None:
        """Push a menu onto the navigation stack.

        Args:
            menu_name: Name of the menu to push
        """
        self.menu_stack.append(menu_name)

    def pop_menu(self) -> str | None:
        """Pop a menu from the navigation stack.

        Returns:
            Name of the popped menu, or None if stack is empty
        """
        if self.menu_stack:
            return self.menu_stack.pop()
        return None

    def get_breadcrumb(self) -> str:
        """Get the current menu path as a breadcrumb trail.

        Returns:
            Breadcrumb string like "Main Menu → Threads → Actions"
        """
        if not self.menu_stack:
            return ""
        return " → ".join(self.menu_stack)

    def show_breadcrumb(self) -> None:
        """Display the breadcrumb trail in the console."""
        breadcrumb = self.get_breadcrumb()
        if breadcrumb:
            console.print(f"[dim]{breadcrumb}[/dim]")
            console.print()
