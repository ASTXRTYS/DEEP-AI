"""DeepAgents CLI - Interactive AI coding assistant.

The CLI has a broad set of optional dependencies. Importing :mod:`deepagents_cli`
should *not* require those extras up front (e.g., when LangGraph loads the
package just to build the agent graph). To keep import-time side effects light,
`cli_main` is loaded lazily the first time it is called.
"""

from typing import Any

from deepagents_cli._bootstrap import ensure_workspace_on_path

ensure_workspace_on_path()

__all__ = ["cli_main"]


def cli_main(*args: Any, **kwargs: Any):  # pragma: no cover - thin wrapper
    from deepagents_cli.main import cli_main as _cli_main

    return _cli_main(*args, **kwargs)
