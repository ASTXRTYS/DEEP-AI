"""Test backward compatibility for CLI entry points."""

import sys
from unittest.mock import patch

import pytest


def test_cli_main_exists():
    """cli_main is still importable (alias to cement_main)."""
    from deepagents_cli import cli_main

    assert callable(cli_main)


def test_cement_main_exists():
    """cement_main entry point exists."""
    from deepagents_cli import cement_main

    assert callable(cement_main)


def test_all_exports():
    """All expected entry points are exported."""
    from deepagents_cli import __all__

    expected = {"cli_main", "cement_main"}
    assert set(__all__) == expected


def test_cement_main_help_works():
    """cement_main --help works without errors."""
    from deepagents_cli import cement_main

    with patch.object(sys, "argv", ["deepagents", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            cement_main()
        # Help should exit with code 0
        assert exc_info.value.code == 0


def test_cli_main_is_alias():
    """cli_main is an alias to cement_main."""
    from deepagents_cli import cement_main, cli_main

    assert cli_main == cement_main
