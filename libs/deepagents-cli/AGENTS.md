# Repository Guidelines

## Project Structure & Module Organization
The CLI source lives in `deepagents_cli/`, with `main.py` and `commands.py` orchestrating the prompt loop, `agent.py`/`execution.py` driving LangGraph steps, and persistence handled by `thread_manager.py`, `thread_store.py`, and `agent_memory.py`. Package data such as `default_agent_prompt.md` is declared in `pyproject.toml`. Integration and regression specs live in `tests/`, mirroring module names (e.g., `tests/test_thread_manager.py`). Utility scripts—`start-dev.sh`, `start-dev-server.sh`, and `start-tmux.sh`—spin up the LangGraph server plus CLI for manual verification.

## Build, Test, and Development Commands
- `python3.11 -m pip install -e . --break-system-packages`: install the CLI locally with editable imports.
- `langgraph dev`: launch the local LangGraph server required by the CLI.
- `deepagents [--agent foo] [--auto-approve]`: run the CLI against the dev server; keep `~/.deepagents/` clean to avoid stale state.
- `make test [TEST_FILE=tests/test_thread_manager.py]`: run pytest via `uv run`, optionally scoped to a path.
- `make lint` / `make format`: execute Ruff formatting and linting, with `_diff` targets for staged-only edits.

## Coding Style & Naming Conventions
Follow Python 3.11 idioms with 4-space indentation and line length ≤100 enforced by `ruff format`. Modules use `snake_case.py`, functions/methods are `snake_case`, classes use `PascalCase`, and constants stay in `UPPER_SNAKE_CASE`. The repo is `py.typed`, so add or update annotations when touching public APIs, but prefer pragmatic typing (strict mypy is disabled). Google-style docstrings are required for new public helpers.

## Testing Guidelines
Pytest plus `pytest-asyncio`, `pytest-timeout`, and `pytest-socket` run via `uv run pytest --disable-socket --allow-unix-socket`. Write tests under `tests/` mirroring the package structure, naming files `test_<area>.py` and coroutines `async def test_<scenario>()`. Cover new commands, error paths, and persistence edge cases, and use `make test_watch` for rapid feedback before opening a PR.

## Commit & Pull Request Guidelines
Commits follow the conventional `<type>: <summary>` style (`refactor: consolidate agent instructions`, `fix: handle 404 gracefully`), with optional issue references such as `(fixes #35)`. Each PR should describe the user-facing change, testing performed (`make test`, `deepagents --agent demo` logs), and any new configuration or migration steps. Link related LangGraph or CLI issues, attach screenshots or terminal captures for UX changes, and request review before merging.

## Environment & Agent Notes
Store secrets in `.env` (Anthropic, Tavily, LangChain, `DEEPAGENTS_DATABASE_URL`). The CLI persists memory under `~/.deepagents/<agent_name>/` and requires PostgreSQL or SQLite checkpoints to match `langgraph dev`. Run `brew services start postgresql@14` plus `/opt/homebrew/opt/postgresql@14/bin/createdb deepagents` before testing persistence flows.
