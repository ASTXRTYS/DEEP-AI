"""UI constants for consistent theming and styling across the CLI.

Defines color palette, icons, and styling constants used throughout
the application for a cohesive visual experience.
"""


# Color Palette
class Colors:
    """Color constants using rich color names and hex codes."""

    # Primary colors
    PRIMARY = "cyan"
    PRIMARY_HEX = "#06b6d4"

    # Accent colors
    ACCENT = "#10b981"  # Green
    SUCCESS = "green"
    WARNING = "yellow"
    ERROR = "red"
    INFO = "blue"

    # Text colors
    TEXT_DIM = "dim"
    TEXT_BOLD = "bold"
    TEXT_HIGHLIGHT = "bold cyan"

    # UI elements
    BORDER = "cyan"
    BORDER_DIM = "dim cyan"
    HEADER = "bold cyan"
    MENU_HIGHLIGHT = "bold"


# Status Icons
class Icons:
    """Unicode icons for consistent visual feedback."""

    # Status
    SUCCESS = "✓"
    ERROR = "✗"
    WARNING = "⚠️"
    INFO = "ℹ️"

    # Actions
    THREAD = "💬"
    NEW = "✨"
    RENAME = "✎"
    DELETE = "🗑️"
    SWITCH = "↻"
    BACK = "←"

    # Features
    AGENT = "🤖"
    TOKENS = "💰"
    SETTINGS = "⚙️"
    HELP = "❓"
    EXIT = "🚪"
    HANDOFF = "🤝"

    # UI
    POINTER = "●"
    QMARK = "▶"
    BULLET = "•"
    ARROW_RIGHT = "→"
    ARROW_DOWN = "↓"
    ARROW_UP = "↑"


# Box Drawing Characters
class BoxChars:
    """Box drawing characters for borders and dividers."""

    # Single line
    HORIZONTAL = "─"
    VERTICAL = "│"
    TOP_LEFT = "┌"
    TOP_RIGHT = "┐"
    BOTTOM_LEFT = "└"
    BOTTOM_RIGHT = "┘"

    # Double line
    HORIZONTAL_DOUBLE = "═"
    VERTICAL_DOUBLE = "║"
    TOP_LEFT_DOUBLE = "╔"
    TOP_RIGHT_DOUBLE = "╗"
    BOTTOM_LEFT_DOUBLE = "╚"
    BOTTOM_RIGHT_DOUBLE = "╝"


# Spacing and Layout
class Layout:
    """Layout constants for consistent spacing."""

    PADDING_SMALL = (0, 1)
    PADDING_MEDIUM = (1, 2)
    PADDING_LARGE = (2, 4)

    MAX_WIDTH = 80
    MIN_WIDTH = 60


# Panel Styles
class PanelStyles:
    """Panel styling presets for different contexts."""

    # Primary panel (main menus, important info)
    PRIMARY = {
        "border_style": Colors.PRIMARY,
        "padding": Layout.PADDING_MEDIUM,
    }

    # Header panel (section headers)
    HEADER = {
        "border_style": Colors.BORDER,
        "padding": Layout.PADDING_SMALL,
        "style": Colors.HEADER,
    }

    # Info panel (help text, descriptions)
    INFO = {
        "border_style": Colors.INFO,
        "padding": Layout.PADDING_MEDIUM,
    }

    # Warning panel (confirmations, warnings)
    WARNING = {
        "border_style": Colors.WARNING,
        "padding": Layout.PADDING_MEDIUM,
    }

    # Success panel (confirmations)
    SUCCESS = {
        "border_style": Colors.SUCCESS,
        "padding": Layout.PADDING_SMALL,
    }
