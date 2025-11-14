"""Workspace bootstrap helpers.

These utilities ensure local monorepo installs can import the ``deepagents``
package (and other sibling libs) without an editable install. This keeps the
LangGraph server and CLI usable directly from a repo checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

__all__ = ["ensure_workspace_on_path"]


def _iter_candidate_paths() -> Iterable[str]:
    current = Path(__file__).resolve()
    workspace_root: Path | None = None

    for parent in current.parents:
        candidate = parent / "libs"
        if candidate.is_dir():
            workspace_root = parent

    if workspace_root is None:
        return ()

    libs_dir = workspace_root / "libs"
    paths: list[str] = [str(workspace_root), str(libs_dir)]

    for project_dir in libs_dir.iterdir():
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue

        src_dir = project_dir / "src"
        paths.append(str(src_dir if src_dir.exists() else project_dir))

    # Deduplicate while preserving order
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        yield path


def ensure_workspace_on_path() -> None:
    """Ensure repo-local libs can be imported before CLI/server boot."""

    for path in _iter_candidate_paths():
        if path not in sys.path:
            sys.path.insert(0, path)
