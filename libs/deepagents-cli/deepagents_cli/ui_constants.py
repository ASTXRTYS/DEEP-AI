"""UI constants for consistent theming and styling across the CLI.

Defines color palette, icons, and styling constants used throughout
the application for a cohesive visual experience.

## Theme System Usage

This module provides a centralized theme system to ensure consistent styling
across the entire CLI. All UI code should use these constants instead of
hardcoded color values.

### Available Theme Systems

1. **DEFAULT_THEME** - Rich Theme with semantic style names (RECOMMENDED)
   Use for: All new code, semantic styling, readable markup

Example:
   ```python
   from .config import console

   # Status indicators using semantic names
   console.print("[success]Operation completed[/success]")
   console.print("[warning]Proceed with caution[/warning]")
   console.print("[error]Operation failed[/error]")

   # UI elements with theme names
   border_style = "border.primary"
   Panel("Content", border_style="border.primary", title="[header]Title[/header]")
   ```

2. **Colors class** - Direct color constants (LEGACY, backward compatible)
   Use for: Existing code, gradual migration

Example:
   ```python
   from .ui_constants import Colors

   # Status indicators
   style = Colors.SUCCESS  # For successful operations
   style = Colors.WARNING  # For warnings or cautions
   style = Colors.ERROR  # For errors

   # UI elements
   border_style = Colors.PRIMARY  # Primary theme color
   text_style = Colors.TEXT_DIM  # Dimmed text
   ```

3. **COLORS dict** (from config.py) - Hex color values (DEPRECATED)
   Use for: Backward compatibility only

Example:
   ```python
   from .config import COLORS

   text.append(f"{label}", style=f"bold {COLORS['primary']}")
   ```

### Migration Guidelines

**New code (RECOMMENDED):**
```python
# Use semantic theme names
console.print("[success]Message[/success]")
border_style = "border.primary"
Panel("Content", border_style="border.primary", title="[header]Title[/header]")
```

**Legacy code (still works):**
```python
# Colors class constants
border_style = Colors.PRIMARY
console.print(f"[{Colors.SUCCESS}]Message[/{Colors.SUCCESS}]")
```

**Gradual migration:**
Both patterns work simultaneously. Theme names provide better readability,
but Colors class constants remain functional for backward compatibility.

### Semantic Style Mapping (Theme Names)

- **success** → green - Successful operations, positive states
- **warning** → yellow - Warnings, cautions, confirmations
- **error** → red - Errors, failures, destructive actions
- **info** → blue - Informational messages
- **primary** → #10b981 (emerald) - Primary theme color for highlights
- **border.primary** → #10b981 - Primary border color
- **border.dim** → dim #10b981 - Dimmed border color
- **border.info** → blue - Info border
- **border.warning** → yellow - Warning border
- **border.success** → green - Success border
- **border.error** → red - Error border
- **text.dim** → dim - Dimmed text
- **text.bold** → bold - Bold emphasis
- **text.highlight** → bold #10b981 - Highlighted text
- **text.white** → white - White text
- **header** → bold #10b981 - Header text

### Benefits

1. **Maintainability** - Change theme colors in one place (Theme definition)
2. **Consistency** - All UI elements use the same color palette
3. **Readability** - Semantic names like [success] are more readable than [green]
4. **External configuration** - Theme can be loaded from config files if needed
5. **Type safety** - Console validates theme style names at runtime
6. **Self-documenting** - Semantic names make intent clear
"""

from rich.theme import Theme

# Rich Theme - Semantic Style Definitions
# This Theme provides semantic style names that map to colors/styles.
# Use these semantic names in markup: console.print("[success]Message[/success]")
DEFAULT_THEME = Theme(
    {
        # Status indicators
        "success": "green",
        "warning": "yellow",
        "error": "red",
        "info": "blue",
        # Primary theme color
        "primary": "#10b981",
        # Borders
        "border.primary": "#10b981",
        "border.dim": "dim #10b981",
        "border.info": "blue",
        "border.warning": "yellow",
        "border.success": "green",
        "border.error": "red",
        # Text styles
        "text.dim": "dim",
        "text.bold": "bold",
        "text.highlight": "bold #10b981",
        "text.white": "white",
        # Headers
        "header": "bold #10b981",
        # Menu highlighting
        "menu.highlight": "bold",
    }
)


# Color Palette
class Colors:
    """Color constants using rich color names and hex codes."""

    # Primary colors
    PRIMARY = "#10b981"  # Emerald green
    PRIMARY_HEX = "#10b981"

    # Accent colors
    ACCENT = "#10b981"  # Green
    SUCCESS = "green"
    WARNING = "yellow"
    WARNING_HEX = "#f59e0b"  # Orange
    ERROR = "red"
    INFO = "blue"

    # Text colors
    TEXT_DIM = "dim"
    TEXT_BOLD = "bold"
    TEXT_HIGHLIGHT = f"bold {PRIMARY}"
    TEXT_WHITE = "white"

    # Hex constants for prompt_toolkit and precise color control
    QUESTION_HEX = "#facc15"  # Yellow for questions
    DIVIDER_HEX = "#1f2937"  # Dark gray for dividers
    NUMBER_HEX = "#9ca3af"  # Light gray for numbers
    NUMBER_SELECTED_HEX = "#0f172a"  # Very dark gray for selected number text
    BASH_MODE_HEX = "#ff1493"  # Deep pink for bash mode indicator

    # UI elements
    BORDER = PRIMARY
    BORDER_DIM = f"dim {PRIMARY}"
    HEADER = f"bold {PRIMARY}"
    MENU_HIGHLIGHT = "bold"


# Status Icons
class Icons:
    """Unicode icons for consistent visual feedback."""

    # Status
    SUCCESS = "✓"  # Check mark
    ERROR = "✗"  # X mark
    WARNING = "⚠"  # Warning triangle
    INFO = "ℹ"  # Info symbol

    # Actions
    THREAD = "⎇"  # Thread/branch symbol
    NEW = "+"  # Plus symbol
    RENAME = "✏"  # Pencil symbol
    DELETE = "×"  # Multiplication X
    SWITCH = "⇄"  # Switch arrows
    BACK = "←"  # Left arrow

    # Features
    AGENT = "◆"  # Diamond
    TOKENS = "#"  # Hash/number sign
    SETTINGS = "⚙"  # Gear symbol
    HELP = "?"  # Question mark
    EXIT = "→"  # Right arrow
    HANDOFF = "⇆"  # Bidirectional arrow

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


# Prompt Toolkit Theme
class PromptTheme:
    """Styling constants for prompt_toolkit components.

    These values are used to configure prompt_toolkit.styles.Style instances,
    ensuring consistent theming between Rich (terminal output) and prompt_toolkit
    (interactive input/toolbar).

    Format: "bg:BACKGROUND_HEX FOREGROUND_HEX [attributes]"
    - bg:COLOR sets background color (hex with #)
    - First bare hex/color sets foreground text color
    - Attributes (positive): bold, italic, underline, blink, reverse, hidden
    - Attributes (negative): nobold, noitalic, nounderline, noblink, noreverse, nohidden
    - Negation: Prefix "no" to disable attributes (e.g., "noreverse" disables reverse video)
    - Multiple attributes: Use space-separated values

    Example: "bg:#10b981 #000000" = green background, black text (matches TOOLBAR_ENABLED below)
    """

    # Toolbar styles
    TOOLBAR_ENABLED = f"bg:{Colors.PRIMARY_HEX} #000000"  # Green background for auto-approve ON
    TOOLBAR_MANUAL = f"bg:{Colors.WARNING_HEX} #000000"  # Orange background for manual approval

    # Base toolbar configuration
    TOOLBAR_BASE = "noreverse"  # Disable default reverse video
