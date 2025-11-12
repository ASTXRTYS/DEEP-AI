"""DeepAgents CLI - Interactive AI coding assistant."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_workspace_on_path() -> None:
    """Add the monorepo root/libs to sys.path when running from sources."""
    current = Path(__file__).resolve()
    workspace_root = None

    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "libs").exists():
            workspace_root = parent  # favor the outermost workspace (monorepo root)

    if workspace_root is None:
        return

    root_str = str(workspace_root)
    libs_str = str(workspace_root / "libs")

    for path in (libs_str, root_str):
        if path not in sys.path:
            sys.path.insert(0, path)


_ensure_workspace_on_path()

# Main entry point
from .cement_main import cement_main

# For backwards compatibility (though not recommended)
cli_main = cement_main

__all__ = ["cement_main", "cli_main"]
