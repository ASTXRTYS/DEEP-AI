"""Reusable UI components using rich library.

Provides helper functions for creating consistent panels, tables,
and other UI elements throughout the CLI.
"""

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .ui_constants import Colors, Icons, PanelStyles


def create_header_panel(title: str, subtitle: str | None = None) -> Panel:
    """Create a styled header panel for menu sections.

    Args:
        title: Main title text
        subtitle: Optional subtitle (e.g., keyboard hints)

    Returns:
        Rich Panel object
    """
    if subtitle:
        content = f"[bold]{title}[/bold]\n[dim]{subtitle}[/dim]"
    else:
        content = f"[bold]{title}[/bold]"

    return Panel(
        content,
        border_style=PanelStyles.HEADER["border_style"],
        padding=PanelStyles.HEADER["padding"],
        expand=False,
    )


def create_info_panel(content: str, title: str | None = None) -> Panel:
    """Create an informational panel.

    Args:
        content: Panel content text (supports rich markup)
        title: Optional panel title

    Returns:
        Rich Panel object
    """
    return Panel(
        content,
        title=title,
        border_style=PanelStyles.INFO["border_style"],
        padding=PanelStyles.INFO["padding"],
    )


def create_warning_panel(content: str, title: str | None = None) -> Panel:
    """Create a warning panel.

    Args:
        content: Warning message text (supports rich markup)
        title: Optional panel title

    Returns:
        Rich Panel object
    """
    return Panel(
        content,
        title=f"{Icons.WARNING} {title}" if title else f"{Icons.WARNING} Warning",
        border_style=PanelStyles.WARNING["border_style"],
        padding=PanelStyles.WARNING["padding"],
    )


def create_success_panel(content: str, title: str | None = None) -> Panel:
    """Create a success panel.

    Args:
        content: Success message text (supports rich markup)
        title: Optional panel title

    Returns:
        Rich Panel object
    """
    return Panel(
        content,
        title=f"{Icons.SUCCESS} {title}" if title else None,
        border_style=PanelStyles.SUCCESS["border_style"],
        padding=PanelStyles.SUCCESS["padding"],
    )


def create_thread_table() -> Table:
    """Create a styled table for thread listings.

    Returns:
        Rich Table object configured for thread data
    """
    table = Table(
        show_header=True,
        header_style=f"bold {Colors.PRIMARY}",
        border_style=Colors.BORDER_DIM,
        padding=(0, 1),
        expand=False,
    )

    table.add_column("ID", style="dim", width=10)
    table.add_column("Name", style="bold", no_wrap=False)
    table.add_column("Messages", justify="right", style=Colors.PRIMARY)
    table.add_column("Tokens", justify="right", style=Colors.PRIMARY)
    table.add_column("Status", justify="center", width=10)

    return table


def create_token_stats_table() -> Table:
    """Create a styled table for token statistics.

    Returns:
        Rich Table object configured for token data
    """
    table = Table(
        show_header=True,
        header_style=f"bold {Colors.PRIMARY}",
        border_style=Colors.BORDER_DIM,
        padding=(0, 2),
        expand=False,
    )

    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right", style=Colors.PRIMARY)
    table.add_column("Cost", justify="right", style=Colors.PRIMARY)

    return table


def create_settings_panel(settings: dict) -> Panel:
    """Create a settings display panel.

    Args:
        settings: Dictionary of setting name to current value

    Returns:
        Rich Panel object showing current settings
    """
    lines = []
    for key, value in settings.items():
        # Format boolean values with color
        if isinstance(value, bool):
            value_str = "[green]ON[/green]" if value else "[dim]OFF[/dim]"
        else:
            value_str = str(value)

        lines.append(f"{key}: {value_str}")

    content = "\n".join(lines)

    return Panel(
        content,
        title=f"{Icons.SETTINGS} Current Settings",
        border_style=Colors.PRIMARY,
        padding=PanelStyles.PRIMARY["padding"],
    )


def format_thread_summary(
    thread_id: str,
    name: str,
    message_count: int,
    tokens: int,
    is_current: bool = False,
) -> str:
    """Format a thread summary line with consistent styling.

    Args:
        thread_id: Thread UUID
        name: Thread name
        message_count: Number of messages in thread
        tokens: Total token count
        is_current: Whether this is the current thread

    Returns:
        Formatted string with rich markup
    """
    thread_id_short = thread_id[:8] if len(thread_id) > 8 else thread_id

    # Format tokens with K suffix if > 1000
    tokens_str = f"{tokens / 1000:.1f}K" if tokens >= 1000 else str(tokens)

    # Build parts
    parts = [
        f"[dim]{thread_id_short}[/dim]",
        f"[bold]{name}[/bold]",
        f"{Icons.BULLET} {message_count} msgs",
        f"{Icons.BULLET} {tokens_str} tokens",
    ]

    if is_current:
        parts.append(f"{Icons.BULLET} [{Colors.PRIMARY}]current[/{Colors.PRIMARY}]")

    return "  ".join(parts)


def format_token_count(tokens: int) -> Text:
    """Format a token count with color coding.

    Args:
        tokens: Number of tokens

    Returns:
        Rich Text object with appropriate styling
    """
    # Color code based on magnitude
    if tokens < 1000:
        style = Colors.SUCCESS
    elif tokens < 10000:
        style = Colors.WARNING
    else:
        style = Colors.ERROR

    # Format with K suffix if >= 1000
    if tokens >= 1000:
        text = f"{tokens / 1000:.1f}K"
    else:
        text = str(tokens)

    return Text(text, style=style)


def format_cost(cost: float) -> Text:
    """Format a cost value with currency.

    Args:
        cost: Cost in dollars

    Returns:
        Rich Text object with currency formatting
    """
    if cost < 0.01:
        return Text(f"${cost:.4f}", style=Colors.SUCCESS)
    if cost < 0.10:
        return Text(f"${cost:.3f}", style=Colors.WARNING)
    return Text(f"${cost:.2f}", style=Colors.ERROR)


def create_divider(char: str = "─", style: str = "dim") -> Text:
    """Create a horizontal divider line.

    Args:
        char: Character to repeat for divider
        style: Rich style for the divider

    Returns:
        Rich Text object
    """
    return Text(char * 60, style=style)
