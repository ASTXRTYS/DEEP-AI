"""Tests for the interactive thread picker."""

from __future__ import annotations

from collections import deque

import pytest

from deepagents_cli.commands import _select_thread_interactively
from deepagents_cli.config import SessionState


def _sample_thread(idx: int) -> dict:
    return {
        "id": f"thread-{idx:02d}-abcdef0123456789",
        "assistant_id": "unit-test",
        "created": "2025-01-11T10:00:00Z",
        "last_used": "2025-01-11T11:00:00Z",
        "message_count": 10 + idx,
        "token_count": 1500 + idx,
        "name": f"Thread {idx}",
    }


@pytest.mark.asyncio
async def test_thread_picker_switch_action(monkeypatch):
    """Ensure picker returns (thread_id, action) when selections succeed."""
    threads = [_sample_thread(1), _sample_thread(2)]
    actions = deque([threads[1]["id"], "switch"])

    class PromptStub:
        def __init__(self, *_: object, **__: object) -> None:
            self.select_async_call_count = 0

        async def select_async(self, **_: object) -> str | None:
            self.select_async_call_count += 1
            return actions.popleft()

    monkeypatch.setattr("deepagents_cli.commands.RichPrompt", PromptStub)
    monkeypatch.setattr("deepagents_cli.commands.check_server_availability", lambda: False)

    session_state = SessionState(auto_approve=False, thread_manager=None)

    selected_id, action = await _select_thread_interactively(
        threads,
        current_thread_id=threads[0]["id"],
        session_state=session_state,
        prompt_session=None,
    )

    assert selected_id == threads[1]["id"]
    assert action == "switch"


@pytest.mark.asyncio
async def test_thread_picker_cancel_path(monkeypatch):
    """Ensure picker gracefully handles cancellation in either phase."""
    threads = [_sample_thread(1), _sample_thread(2)]

    # First select returns None to simulate cancellation during thread selection.
    class PromptStub:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def select_async(self, **_: object) -> str | None:
            return None

    monkeypatch.setattr("deepagents_cli.commands.RichPrompt", PromptStub)
    monkeypatch.setattr("deepagents_cli.commands.check_server_availability", lambda: False)

    session_state = SessionState(auto_approve=False, thread_manager=None)
    selected_id, action = await _select_thread_interactively(
        threads,
        current_thread_id=threads[0]["id"],
        session_state=session_state,
        prompt_session=None,
    )

    assert selected_id is None
    assert action is None
