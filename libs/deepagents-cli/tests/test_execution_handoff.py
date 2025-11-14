"""Unit coverage for the CLI HITL handoff helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.types import Interrupt

import deepagents_cli.execution as execution_module
from deepagents_cli.execution import (
    HANDOFF_ACTION_NAME,
    _normalize_hitl_request_payload,
    _resolve_handoff_action,
    execute_task,
    is_handoff_request,
)
from deepagents_cli.handoff_ui import HandoffProposal, prompt_handoff_decision
from deepagents_cli.config import SessionState
from deepagents_cli.handoff_persistence import build_handoff_metadata, write_summary_block
from deepagents_cli.thread_manager import ThreadManager
from deepagents_cli.ui import TokenTracker


def test_is_handoff_request_detects_action_request() -> None:
    hitl_request = {
        "action_requests": [
            {"name": HANDOFF_ACTION_NAME, "args": {"handoff_id": "handoff-123"}},
        ],
    }

    assert is_handoff_request(hitl_request) is True


def test_is_handoff_request_detects_review_config() -> None:
    hitl_request = {
        "review_configs": [{"action_name": HANDOFF_ACTION_NAME}],
    }

    assert is_handoff_request(hitl_request) is True


def test_resolve_handoff_action_prefers_action_args() -> None:
    handoff_args = {
        "handoff_id": "handoff-abc",
        "summary_json": {"title": "Upstream summary"},
        "parent_thread_id": "parent-1",
    }
    hitl_request = {
        "summary_json": {"title": "Legacy summary"},
        "action_requests": [
            {
                "name": HANDOFF_ACTION_NAME,
                "args": handoff_args,
            }
        ],
    }

    normalized, request_entry = _resolve_handoff_action(hitl_request)

    assert normalized["summary_json"]["title"] == "Upstream summary"
    assert normalized["handoff_id"] == "handoff-abc"
    assert request_entry is hitl_request["action_requests"][0]


def test_resolve_handoff_action_falls_back_to_legacy_shape() -> None:
    legacy_request = {
        "handoff_id": "legacy-handoff",
        "summary_md": "Legacy",
        "summary_json": {"title": "Legacy summary"},
        "parent_thread_id": "parent-legacy",
    }

    normalized, request_entry = _resolve_handoff_action(legacy_request)

    assert request_entry is None
    assert normalized["handoff_id"] == "legacy-handoff"
    assert normalized["summary_json"]["title"] == "Legacy summary"


def test_resolve_handoff_action_preserves_preview_flag() -> None:
    hitl_request = {
        "action_requests": [
            {
                "name": HANDOFF_ACTION_NAME,
                "args": {
                    "handoff_id": "handoff-preview",
                    "preview_only": True,
                },
            }
        ]
    }

    normalized, _ = _resolve_handoff_action(hitl_request)

    assert normalized["preview_only"] is True


def test_prompt_handoff_decision_preview_mode_short_circuits() -> None:
    proposal = HandoffProposal(
        handoff_id="handoff-preview",
        summary_json={"title": "Preview", "tldr": "TLDR", "body": []},
        summary_md="**Preview summary**",
        parent_thread_id="thread-1",
        assistant_id="assistant-1",
    )

    decision = prompt_handoff_decision(proposal, preview_only=True)

    assert decision.status == "preview"
    assert decision.summary_md == proposal.summary_md


def test_normalize_hitl_request_prefers_model_dump() -> None:
    class DummyModel:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def model_dump(self) -> dict[str, Any]:
            return self._payload

    payload = {
        "action_requests": [
            {
                "name": HANDOFF_ACTION_NAME,
                "args": {"handoff_id": "123"},
            }
        ],
        "review_configs": [
            {
                "action_name": HANDOFF_ACTION_NAME,
                "allowed_decisions": ["approve"],
            }
        ],
    }

    normalized = _normalize_hitl_request_payload(DummyModel(payload))

    assert normalized == payload


class _StubAgent:
    def __init__(
        self,
        invocations: list[list[tuple]],
        *,
        final_state: SimpleNamespace | None = None,
    ) -> None:
        self.invocations = invocations
        self.call_count = 0
        self.stream_inputs: list[Any] = []
        self._final_state = final_state

    async def astream(self, stream_input, **kwargs):  # type: ignore[override]
        idx = self.call_count
        self.call_count += 1
        self.stream_inputs.append(stream_input)
        for chunk in self.invocations[idx]:
            yield chunk

    async def aupdate_state(self, *args, **kwargs):  # pragma: no cover - not used here
        return None

    async def aget_state(self, *args, **kwargs):  # pragma: no cover - not used here
        return self._final_state


@pytest.mark.asyncio
async def test_execute_task_handles_typed_dict_hitl_interrupt(monkeypatch) -> None:
    hitl_payload = {
        "action_requests": [
            {
                "name": "demo_tool",
                "args": {"path": "demo.txt"},
                "description": "Demo request",
            }
        ],
        "review_configs": [
            {"action_name": "demo_tool", "allowed_decisions": ["approve", "reject"]},
        ],
    }

    interrupts = [Interrupt(value=hitl_payload, id="interrupt-1")]
    first_cycle = [("root", "updates", {"__interrupt__": interrupts})]
    second_cycle: list[tuple] = []
    agent = _StubAgent(invocations=[first_cycle, second_cycle])

    captured_requests: list[dict[str, Any]] = []

    def fake_is_handoff_request(request: Any) -> bool:
        captured_requests.append(request)
        return False

    monkeypatch.setattr(execution_module, "is_handoff_request", fake_is_handoff_request)

    session_state = SimpleNamespace(auto_approve=True, thread_manager=None)

    await execute_task(
        user_input="summarize",
        agent=agent,
        assistant_id="assistant-1",
        session_state=session_state,
    )

    assert captured_requests, "interrupt was not routed through handoff detection"
    assert captured_requests[0] == hitl_payload


@pytest.mark.asyncio
async def test_execute_task_accepts_middleware_handoff(monkeypatch) -> None:
    hitl_args = {
        "handoff_id": "handoff-123",
        "summary_json": {"title": "Escalation", "tldr": "TLDR"},
        "summary_md": "**Escalation**",
        "parent_thread_id": "thread-parent",
        "assistant_id": "assistant-cli",
    }
    hitl_payload = {
        "action_requests": [{"name": HANDOFF_ACTION_NAME, "args": hitl_args}],
        "review_configs": [{"action_name": HANDOFF_ACTION_NAME, "allowed_decisions": ["approve"]}],
    }
    interrupts = [Interrupt(value=hitl_payload, id="interrupt-1")]
    agent = _StubAgent(invocations=[[ ("root", "updates", {"__interrupt__": interrupts}) ], []], final_state=SimpleNamespace(values={}))

    async def _fake_prompt(*args, **kwargs):  # type: ignore[override]
        return SimpleNamespace(status="accepted", summary_json=hitl_args["summary_json"], summary_md=hitl_args["summary_md"])

    captured_apply: dict[str, Any] = {}

    def _fake_apply(**kwargs):
        captured_apply.update(kwargs)
        return "child-xyz"

    monkeypatch.setattr("deepagents_cli.handoff_ui.prompt_handoff_decision", _fake_prompt)
    monkeypatch.setattr("deepagents_cli.handoff_persistence.apply_handoff_acceptance", _fake_apply)

    session_state = SimpleNamespace(auto_approve=False, thread_manager=None, pending_handoff_child_id=None)

    await execute_task(
        user_input="continue",
        agent=agent,
        assistant_id="assistant-cli",
        session_state=session_state,
    )

    assert session_state.pending_handoff_child_id == "child-xyz"
    assert captured_apply["summary_json"]["title"] == "Escalation"


@pytest.mark.asyncio
async def test_execute_task_triggers_summary_cleanup(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "deepagents_cli.server_client.create_thread_on_server",
        lambda *args, **kwargs: "thread-root",
    )

    manager = ThreadManager(tmp_path / "agent", "assistant-cli")
    thread_id = manager.get_current_thread_id()

    summary_json: dict[str, Any] = {
        "title": "Escalation",
        "tldr": "TLDR",
        "created_at": "2024-01-01T00:00:00Z",
    }
    handoff_meta = build_handoff_metadata(
        handoff_id="handoff-xyz",
        source_thread_id=thread_id,
        child_thread_id=thread_id,
        summary_json=summary_json,
        pending=True,
        cleanup_required=True,
    )
    manager.update_thread_metadata(thread_id, {"handoff": handoff_meta})

    agent_md_path = manager.agent_dir / "agent.md"
    write_summary_block(agent_md_path, "### Demo summary\n- point")

    session_state = SessionState(thread_manager=manager)
    token_tracker = TokenTracker()
    token_tracker.set_baseline(100)

    final_state = SimpleNamespace(values={"_handoff_cleanup_pending": True})
    agent = _StubAgent(invocations=[[ ]], final_state=final_state)

    cleared_paths: list[Path] = []

    import deepagents_cli.handoff_persistence as hp

    original_clear = hp.clear_summary_block_file

    def _tracking_clear(path: Path) -> None:
        cleared_paths.append(path)
        original_clear(path)

    monkeypatch.setattr(hp, "clear_summary_block_file", _tracking_clear)

    await execute_task(
        user_input="please proceed",
        agent=agent,
        assistant_id="assistant-cli",
        session_state=session_state,
        token_tracker=token_tracker,
    )

    assert cleared_paths and cleared_paths[0] == agent_md_path

    thread_meta = manager.get_thread_metadata(thread_id)
    assert thread_meta is not None
    handoff_state = (thread_meta.get("metadata") or {}).get("handoff")
    assert handoff_state
    assert handoff_state["pending"] is False
    assert handoff_state["cleanup_required"] is False
    assert handoff_state["last_cleanup_at"] is not None
