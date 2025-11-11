"""Unified styling system for the TUI menu system.

Provides consistent questionary styles matching the DeepAgents CLI theme.
"""

from questionary import Style

# Primary theme matching current CLI (#10b981 green)
PRIMARY_STYLE = Style(
    [
        ("qmark", "#10b981 bold"),  # Question mark indicator
        ("question", "bold"),  # Question text
        ("answer", "#10b981 bold"),  # Selected answer
        ("pointer", "#10b981 bold"),  # Current selection pointer
        ("highlighted", "#ffffff bg:#10b981 bold"),  # Highlighted item (white on green)
        ("selected", "#10b981"),  # Selected checkbox items
        ("instruction", "#888888 italic"),  # Help text
        ("text", ""),  # Regular text
        ("separator", "#888888"),  # Separators
    ]
)

# Warning style for destructive actions (amber/orange)
WARNING_STYLE = Style(
    [
        ("qmark", "#f59e0b bold"),  # Amber
        ("question", "bold"),
        ("answer", "#ef4444 bold"),  # Red for emphasis
        ("pointer", "#f59e0b bold"),
        ("highlighted", "#ffffff bg:#f59e0b bold"),  # White on amber
        ("selected", "#f59e0b"),
        ("instruction", "#888888 italic"),
        ("text", ""),
        ("separator", "#888888"),
    ]
)

# Info style for read-only displays (blue)
INFO_STYLE = Style(
    [
        ("qmark", "#3b82f6 bold"),  # Blue
        ("question", "bold"),
        ("answer", "#3b82f6 bold"),
        ("pointer", "#3b82f6 bold"),
        ("highlighted", "#ffffff bg:#3b82f6 bold"),  # White on blue
        ("selected", "#3b82f6"),
        ("instruction", "#888888 italic"),
        ("text", ""),
        ("separator", "#888888"),
    ]
)


def get_style_for_context(context: str) -> Style:
    """Return appropriate style based on context.

    Args:
        context: One of 'default', 'warning', 'destructive', 'info'

    Returns:
        Appropriate Style object for the context
    """
    mapping = {
        "default": PRIMARY_STYLE,
        "warning": WARNING_STYLE,
        "destructive": WARNING_STYLE,
        "info": INFO_STYLE,
    }
    return mapping.get(context, PRIMARY_STYLE)
