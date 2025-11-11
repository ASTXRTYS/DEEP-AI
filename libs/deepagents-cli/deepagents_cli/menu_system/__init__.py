"""TUI Menu System for DeepAgents CLI.

This module provides a hierarchical, navigable menu system that enhances
discoverability and usability while maintaining backward compatibility with
all existing slash commands.

Key components:
- MenuSystem: Core navigation engine with stack-based menu management
- Styling: Unified questionary styling matching CLI theme
- Menus: Menu definition and choice generation
- Handlers: Action handlers for menu selections
"""

from .core import MenuSystem
from .styles import INFO_STYLE, PRIMARY_STYLE, WARNING_STYLE, get_style_for_context

__all__ = [
    "INFO_STYLE",
    "PRIMARY_STYLE",
    "WARNING_STYLE",
    "MenuSystem",
    "get_style_for_context",
]
