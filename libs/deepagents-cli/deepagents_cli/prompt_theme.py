"""Shared prompt_toolkit style definitions for the DeepAgents CLI.

The CLI relies on prompt_toolkit for both the primary REPL and
contextual slash-command dialogs (for example, `/threads`). This module
centralizes the Style definitions so every PromptSession can share the
same palette, toolbar treatments, and completion menu colors.

See ``STYLEGUIDE.md`` for the high-level conventions every prompt should
follow before introducing new style classes.
"""

from prompt_toolkit.styles import Style, merge_styles

from .config import COLORS

# Base prompt style used by the main REPL and any child dialogs.
BASE_PROMPT_STYLE = Style.from_dict(
    {
        # Prompt glyph / text color
        "prompt": f"{COLORS['primary']} bold",

        # Toolbar + hint colors
        "bottom-toolbar": "noreverse",
        "toolbar-green": "bg:#10b981 #000000",
        "toolbar-orange": "bg:#f59e0b #000000",
        "toolbar-hint": "bg:#1f2937 #f9fafb",
        "toolbar-exit": "bg:#2563eb #ffffff",

        # Completion menu (columns + meta blocks)
        "completion-menu": "bg:#041f1a #a7f3d0",
        "completion-menu.completion": "bg:#022c22 #d1fae5",
        # Muted highlight to keep text legible on dark backgrounds
        "completion-menu.completion.current": "bg:#0a4037 #e0fffa bold",
        "completion-menu.meta": "bg:#05241c #6ee7b7",
        "completion-menu.meta.completion": "bg:#05241c #6ee7b7",
        "completion-menu.meta.completion.current": "bg:#0d4037 #d6fff4",

        # Thread dashboard specific classes (used inside FormattedText)
        "threads-menu.index": "#67e8f9 bold",
        "threads-menu.name": "#ecfccb bold",
        "threads-menu.id": "#94a3b8",
        # Meta preview panel for the currently selected thread. Use a
        # dedicated gray band with light text so the "Hello, I'm here
        # to help..." preview is crisp and legible above the toolbar.
        "threads-menu.meta-header": "bg:#111827 #e5e7eb",
        "threads-menu.meta-footer": "bg:#111827 #9ca3af",
        # Minimal toolbar hint styling (transparent background, darker bold text)
        "threads-menu.hint": "#0f9d7a bold",
        # Subtle separator under the `/threads` picker; use the shared
        # dim neutral so it stays readable on dark terminals without
        # overpowering the completion menu itself.
        "threads-menu.hint-sep": COLORS["dim"],
    }
)

# Thread dashboard specific overrides.
# We keep the shared palette from BASE_PROMPT_STYLE but introduce a
# dedicated bottom-toolbar band so the `/threads` hint line stands out
# cleanly under the completion grid (similar weight to the main menu).
THREAD_PROMPT_OVERRIDES = Style.from_dict(
    {
        # Dark slate band with light neutral text. Key hints (toolbar-green /
        # toolbar-orange) still render on top of this background.
        "bottom-toolbar": "bg:#111827 #9ca3af",
    }
)


def build_thread_prompt_style() -> Style:
    """Return the Style for the `/threads` dialog.

    For the thread dashboard, layer thread-specific overrides on top of
    the shared base style so we can adjust the toolbar band without
    affecting the main REPL.
    """

    return merge_styles([BASE_PROMPT_STYLE, THREAD_PROMPT_OVERRIDES])
