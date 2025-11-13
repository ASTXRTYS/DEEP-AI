"""Async tests for RichPrompt dangerous confirmation flow."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from deepagents_cli.rich_ui import RichPrompt, SelectionState


@pytest.mark.asyncio
async def test_dangerous_confirmation_whitespace_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace-only input should be rejected before comparison."""
    rich_prompt = RichPrompt(Console())

    async def fake_text_input_async(*args: Any, **kwargs: Any) -> str:
        validate = kwargs.get("validate")
        assert validate is not None
        # Validator should reject whitespace-only input explicitly.
        assert validate("   \t  ") == "Confirmation cannot be empty or whitespace-only"
        return "   \t  "

    monkeypatch.setattr(rich_prompt, "text_input_async", fake_text_input_async)

    confirmed = await rich_prompt.dangerous_confirmation_async(
        action="Delete Thread",
        target="test-thread",
        details={"messages": 3},
        confirmation_text="DELETE",
    )

    assert confirmed is False


@pytest.mark.asyncio
async def test_dangerous_confirmation_exact_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact confirmation text should still succeed."""
    rich_prompt = RichPrompt(Console())

    async def fake_text_input_async(*args: Any, **kwargs: Any) -> str:
        validate = kwargs.get("validate")
        assert validate is not None
        assert validate("DELETE") is True
        return "DELETE"

    monkeypatch.setattr(rich_prompt, "text_input_async", fake_text_input_async)

    confirmed = await rich_prompt.dangerous_confirmation_async(
        action="Delete Thread",
        target="test-thread",
        details={"messages": 3},
        confirmation_text="DELETE",
    )

    assert confirmed is True


class _DummyAsyncApp:
    async def run_in_terminal_async(self, func):
        await asyncio.to_thread(func)


class _DummySyncApp:
    def run_in_terminal(self, func):
        func()


@pytest.mark.asyncio
async def test_modal_runner_handles_running_loop_async_app() -> None:
    """_run_modal_in_terminal should not raise when loop already running."""
    prompt = RichPrompt(Console())
    prompt.prompt_session = SimpleNamespace(app=_DummyAsyncApp())

    async def modal() -> str:
        await asyncio.sleep(0)
        return "ok"

    result = await prompt._run_modal_in_terminal(lambda: modal())

    assert result == "ok"


@pytest.mark.asyncio
async def test_modal_runner_handles_sync_fallback_app() -> None:
    """Fallback to run_in_terminal still resolves modal execution."""
    prompt = RichPrompt(Console())
    prompt.prompt_session = SimpleNamespace(app=_DummySyncApp())

    async def modal() -> str:
        return "value"

    result = await prompt._run_modal_in_terminal(lambda: modal())

    assert result == "value"


@pytest.mark.asyncio
async def test_modal_runner_uses_existing_loop_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a running loop exists on another thread, reuse it via run_coroutine_threadsafe."""
    prompt = RichPrompt(Console())
    prompt.prompt_session = SimpleNamespace(app=_DummyAsyncApp())

    main_loop = asyncio.get_running_loop()

    # Force the worker thread to "see" the main event loop so `_thread_id` differs.
    monkeypatch.setattr("deepagents_cli.rich_ui.asyncio.get_event_loop", lambda: main_loop)

    async def modal() -> str:
        await asyncio.sleep(0)
        return "shared-loop"

    result = await prompt._run_modal_in_terminal(lambda: modal())

    assert result == "shared-loop"


def test_selection_state_renders_without_numbering():
    """SelectionState should not include numeric prefixes or quick-select hints."""
    state = SelectionState(
        choices=[("a", "Alpha option"), ("b", "Beta option")],
        default_value="a",
    )

    rendered = "".join(fragment for _, fragment in state.render_choices())
    assert "1." not in rendered
    assert "2." not in rendered
    assert "> " in rendered  # Arrow pointer highlights current row
