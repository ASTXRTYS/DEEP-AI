"""Unit coverage for the manual /handoff command."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deepagents_cli import commands as commands_module
from deepagents_cli.commands import handle_handoff_command
from deepagents_cli.handoff_ui import HandoffDecision


class _StubAgent:
    def __init__(self, messages: list) -> None:
        self._state = SimpleNamespace(values={"messages": messages})
        self.config_seen: dict | None = None

    async def aget_state(self, config):  # type: ignore[override]
        self.config_seen = config
        return self._state


class _StubThreadManager:
    def __init__(self) -> None:
        self.assistant_id = "assistant-cli"
        self.switch_calls: list[str] = []

    def get_current_thread_id(self) -> str:
        return "thread-123"

    def switch_thread(self, thread_id: str) -> None:
        self.switch_calls.append(thread_id)


@pytest.mark.asyncio
async def test_handle_handoff_command_accepts_and_switches_thread(monkeypatch) -> None:
    messages = [HumanMessage(content="Need summary."), AIMessage(content="Working on it.")]
    agent = _StubAgent(messages)
    session_state = SimpleNamespace(model="fake-model", thread_manager=_StubThreadManager())

    summary = SimpleNamespace(
        handoff_id="handoff-demo",
        summary_json={"title": "Demo", "tldr": "TLDR", "body": ["line"]},
        summary_md="**Demo summary**",
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "generate_handoff_summary",
        lambda **kwargs: summary,
    )

    def _fake_prompt(proposal, preview_only=False):
        captured["proposal"] = proposal
        return HandoffDecision(
            status="accepted",
            summary_md=proposal.summary_md,
            summary_json=proposal.summary_json,
        )

    monkeypatch.setattr(commands_module, "prompt_handoff_decision", _fake_prompt)

    def _fake_apply(**kwargs):
        captured["apply_kwargs"] = kwargs
        return "child-789"

    monkeypatch.setattr(commands_module, "apply_handoff_acceptance", _fake_apply)

    result = await handle_handoff_command("--messages 5", agent, session_state)

    assert result is True
    assert session_state.thread_manager.switch_calls == ["child-789"]
    assert captured["proposal"].parent_thread_id == "thread-123"  # type: ignore[attr-defined]
    assert captured["apply_kwargs"]["parent_thread_id"] == "thread-123"  # type: ignore[index]


@pytest.mark.asyncio
async def test_handle_handoff_command_preview_mode_skips_persistence(monkeypatch) -> None:
    messages = [HumanMessage(content="Need summary."), AIMessage(content="Working on it.")]
    agent = _StubAgent(messages)
    session_state = SimpleNamespace(model="fake-model", thread_manager=_StubThreadManager())

    summary = SimpleNamespace(
        handoff_id="handoff-demo",
        summary_json={"title": "Demo", "tldr": "TLDR", "body": ["line"]},
        summary_md="**Demo summary**",
    )

    monkeypatch.setattr(
        commands_module,
        "generate_handoff_summary",
        lambda **kwargs: summary,
    )

    monkeypatch.setattr(
        commands_module,
        "prompt_handoff_decision",
        lambda *args, **kwargs: HandoffDecision(
            status="preview",
            summary_md="**Demo summary**",
            summary_json=summary.summary_json,
        ),
    )

    apply_called = False

    def _fake_apply(**kwargs):
        nonlocal apply_called
        apply_called = True
        return "child-000"

    monkeypatch.setattr(commands_module, "apply_handoff_acceptance", _fake_apply)

    result = await handle_handoff_command("--preview", agent, session_state)

    assert result is True
    assert apply_called is False
    assert session_state.thread_manager.switch_calls == []
