"""Tests for workspace bootstrap utilities."""

from __future__ import annotations

import sys
from pathlib import Path

from deepagents_cli._bootstrap import ensure_workspace_on_path


def test_ensure_workspace_on_path_adds_repo_and_libs() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    libs_dir = repo_root / "libs"

    original_path = list(sys.path)
    try:
        sys.path = [
            entry
            for entry in sys.path
            if entry not in {str(repo_root), str(libs_dir)}
        ]

        ensure_workspace_on_path()

        assert str(repo_root) in sys.path
        assert str(libs_dir) in sys.path
    finally:
        sys.path[:] = original_path
