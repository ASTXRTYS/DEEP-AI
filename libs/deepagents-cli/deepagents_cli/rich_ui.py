"""Rich-enhanced UI components for DeepAgents CLI.

This module provides beautiful terminal UI components using the Rich library,
including panels, tables, progress bars, and interactive prompts.
"""


from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .config import COLORS, DEEP_AGENTS_ASCII, console


class RichPrompt:
    """Enhanced prompt system using Rich.

    Provides beautiful, numbered menus with Rich panels for display
    and Rich's prompts for user input (IntPrompt, Confirm, Prompt).
    """

    def __init__(self, console: Console):
        """Initialize the Rich prompt system.

        Args:
            console: Rich Console instance for output
        """
        self.console = console

    def menu(
        self,
        title: str,
        options: list[tuple[str, str]],
        subtitle: str | None = None,
        show_numbers: bool = True,
    ) -> str | None:
        """Display a beautiful numbered menu and get user selection.

        Args:
            title: Menu title
            options: List of (value, description) tuples
            subtitle: Optional subtitle
            show_numbers: Whether to show numbers (default: True)

        Returns:
            Selected value or None if cancelled
        """
        from rich.prompt import IntPrompt

        # Clear screen for clean display
        self.console.clear()

        # Create menu panel
        menu_content = self._create_menu_content(title, options, subtitle)
        panel = Panel(
            menu_content,
            border_style=COLORS["primary"],
            title=f"[bold]{title}[/bold]",
            subtitle=subtitle if subtitle else None,
            padding=(1, 2),
        )

        self.console.print(panel)
        self.console.print()

        # Get user input with Rich's IntPrompt
        try:
            # Build valid choices (1-indexed for user display)
            option_values = [opt[0] for opt in options]
            valid_choices = list(range(1, len(options) + 1))

            # Prompt for selection
            choice = IntPrompt.ask(
                "[bold cyan]Enter your choice[/bold cyan]",
                choices=[str(i) for i in valid_choices],
                show_choices=False,  # We already displayed choices in the panel
                console=self.console,
            )

            # Map back to value (convert from 1-indexed to 0-indexed)
            return option_values[choice - 1]

        except KeyboardInterrupt:
            return None

    def confirm(self, message: str, default: bool = False) -> bool:
        """Display a confirmation prompt.

        Args:
            message: Confirmation message
            default: Default response

        Returns:
            True if confirmed, False otherwise
        """
        from rich.prompt import Confirm

        try:
            return Confirm.ask(
                f"[bold yellow]{message}[/bold yellow]",
                default=default,
                console=self.console,
            )
        except KeyboardInterrupt:
            return False

    def text_input(self, prompt: str, default: str = "", password: bool = False) -> str | None:
        """Get text input from user.

        Args:
            prompt: Input prompt
            default: Default value
            password: Whether to suppress input display

        Returns:
            User input or None if cancelled
        """
        from rich.prompt import Prompt

        try:
            return Prompt.ask(
                f"[bold cyan]{prompt}[/bold cyan]",
                default=default if default else ...,  # Use ellipsis for no default
                password=password,
                console=self.console,
            )
        except KeyboardInterrupt:
            return None

    def _create_menu_content(
        self, title: str, options: list[tuple[str, str]], subtitle: str | None
    ) -> Group:
        """Create beautiful menu content with Rich formatting.

        Args:
            title: Menu title
            options: List of (value, description) tuples
            subtitle: Optional subtitle

        Returns:
            Rich Group with formatted menu items
        """
        items = []

        # Add subtitle if provided
        if subtitle:
            items.append(Text(subtitle, style="dim"))
            items.append(Text(""))

        # Add numbered options
        for i, (value, description) in enumerate(options, 1):
            # Parse emoji/icon if present
            if description.startswith(("🔹", "📊", "🚀", "⚙️", "❓", "🚪", "🧵")):
                icon = description[0]
                desc = description[1:].strip()
                text = Text()
                text.append(f"{i:2}. ", style="bold cyan")
                text.append(icon + " ")
                text.append(desc, style="bold white")
            else:
                text = Text()
                text.append(f"{i:2}. ", style="bold cyan")
                text.append(description, style="bold white")

            items.append(text)

        # Add hint
        items.append(Text(""))
        items.append(
            Text(
                "Type the number and press Enter • Ctrl+C to cancel",
                style=f"dim {COLORS['dim']}",
            )
        )

        return Group(*items)


class ProgressDisplay:
    """Rich progress display for long-running operations."""

    def __init__(self, console: Console):
        """Initialize progress display.

        Args:
            console: Rich Console instance
        """
        self.console = console
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,  # Clean up completed progress bars
        )

    def __enter__(self):
        """Enter context manager."""
        self.progress.start()
        return self.progress

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        self.progress.stop()


def create_status_table(title: str, items: list[tuple[str, str, str | None]]) -> Table:
    """Create a beautiful status table.

    Args:
        title: Table title
        items: List of (label, value, style) tuples

    Returns:
        Formatted Rich Table
    """
    table = Table(
        title=title,
        show_header=False,
        border_style=COLORS["primary"],
        padding=(0, 1),
    )

    table.add_column("Label", style="dim", width=20)
    table.add_column("Value", style="bold")

    for label, value, style in items:
        val_style = style if style else "white"
        table.add_row(label, value, style=val_style)

    return table


def create_thread_table(threads: list[dict], current_id: str) -> Table:
    """Create a beautiful table of threads.

    Args:
        threads: List of thread metadata
        current_id: Current thread ID

    Returns:
        Formatted Rich Table
    """
    table = Table(
        title="📋 Available Threads",
        border_style=COLORS["primary"],
        header_style="bold cyan",
        show_lines=True,
    )

    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("ID", style="cyan", width=12)
    table.add_column("Name", style="bold white")
    table.add_column("Messages", justify="right", style="yellow")
    table.add_column("Tokens", justify="right", style="magenta")
    table.add_column("Status", justify="center", width=10)

    for i, thread in enumerate(threads, 1):
        thread_id = thread["id"]
        thread_id_short = thread_id[:8] if len(thread_id) > 8 else thread_id
        name = escape(thread.get("name", "Untitled"))  # Escape user input
        message_count = thread.get("message_count", 0)
        tokens = thread.get("total_tokens", 0)

        # Format tokens with K suffix
        tokens_str = f"{tokens / 1000:.1f}K" if tokens >= 1000 else str(tokens)

        # Status indicator
        status = "● ACTIVE" if thread_id == current_id else "○"
        status_style = "green" if thread_id == current_id else "dim"

        table.add_row(
            str(i),
            thread_id_short,
            name,
            str(message_count),
            tokens_str,
            f"[{status_style}]{status}[/{status_style}]",
        )

    return table


def create_syntax_panel(code: str, language: str, title: str = "Code") -> Panel:
    """Create a beautiful syntax-highlighted code panel.

    Args:
        code: Code to display
        language: Programming language
        title: Panel title

    Returns:
        Formatted Panel with syntax highlighting
    """
    syntax = Syntax(code, language, theme="monokai", line_numbers=True)
    return Panel(
        syntax,
        title=f"[bold]{title}[/bold]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )


def create_tree_view(title: str, data: dict) -> Tree:
    """Create a beautiful tree view of nested data.

    Args:
        title: Tree title
        data: Nested dictionary to display

    Returns:
        Rich Tree
    """
    tree = Tree(f"[bold cyan]{title}[/bold cyan]")

    def add_items(parent, items):
        if isinstance(items, dict):
            for key, value in items.items():
                if isinstance(value, dict):
                    branch = parent.add(f"[yellow]{key}[/yellow]")
                    add_items(branch, value)
                else:
                    parent.add(f"[yellow]{key}[/yellow]: [green]{value}[/green]")
        elif isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    add_items(parent, item)
                else:
                    parent.add(f"[green]{item}[/green]")

    add_items(tree, data)
    return tree


# Display functions for main CLI


def display_ascii_banner() -> None:
    """Display the DeepAgents ASCII banner."""
    console.clear()
    console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
    console.print()


def display_connection_status(connected: bool) -> None:
    """Display server connection status.

    Args:
        connected: Whether server is connected
    """
    if connected:
        console.print("[green]● Connected to LangGraph server[/green]")
    else:
        console.print("[red]● Not connected to LangGraph server[/red]")
    console.print()


def display_tavily_warning() -> None:
    """Display Tavily API warning."""
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


def display_welcome(auto_approve: bool = False) -> None:
    """Display welcome message.

    Args:
        auto_approve: Whether auto-approve is enabled
    """
    from pathlib import Path

    console.print("... Ready to code! What would you like to build?", style=COLORS["agent"])
    console.print(f"  [dim]Working directory: {Path.cwd()}[/dim]")
    console.print()

    if auto_approve:
        console.print(
            "  [yellow]⚡ Auto-approve: ON[/yellow] [dim](tools run without confirmation)[/dim]"
        )
        console.print()

    console.print(
        "  Tips: Ctrl+M for menu • /help for commands • !cmd for bash • Ctrl+C to exit",
        style=f"dim {COLORS['dim']}",
    )
    console.print()


def display_server_error(error_message: str | None = None) -> None:
    """Display server connection error.

    Args:
        error_message: Optional error details
    """
    console.print("[red]✗ Failed to start server automatically[/red]")
    console.print()

    if error_message:
        panel = Panel(
            error_message,
            title="[bold red]Error Details[/bold red]",
            border_style="red",
        )
        console.print(panel)
        console.print()

    console.print("Please start the server manually in another terminal:")
    console.print("  [cyan]langgraph dev[/cyan]")
    console.print()
    console.print("Then restart the CLI.")
