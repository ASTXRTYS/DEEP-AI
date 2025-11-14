from types import SimpleNamespace

import pytest

from deepagents.middleware.handoff_summarization import (
    HANDOFF_ACTION_NAME,
    HandoffSummarizationMiddleware,
    HandoffSummary,
)


def _runtime(metadata=None, configurable=None):
    metadata = metadata or {}
    configurable = configurable or {}
    return SimpleNamespace(config={"metadata": metadata, "configurable": configurable})


def _state(messages=None):
    return {"handoff_requested": True, "messages": messages or []}


@pytest.fixture
def stub_summary() -> HandoffSummary:
    return HandoffSummary(
        handoff_id="handoff-123",
        summary_json={
            "schema_version": 1,
            "handoff_id": "handoff-123",
            "assistant_id": "assistant-1",
            "parent_thread_id": "thread-1",
            "child_thread_id": None,
            "title": "Escalation",
            "body": ["Investigate log spike"],
            "tldr": "Pending investigation",
            "model": "stub",
            "tokens_used": 12,
            "created_at": "2024-01-01T00:00:00Z",
        },
        summary_md="""### Recent Thread Snapshot\n**Title:** Escalation\n**TL;DR:** Pending investigation\n\n#### Key Points\n- Investigate log spike\n""",
    )


@pytest.mark.parametrize("decision_payload", [
    {"decisions": [{"type": "approve"}]},
    {"decisions": [{"type": "approve", "message": "looks good"}]},
])
def test_handoff_middleware_emits_canonical_payload(monkeypatch, stub_summary, decision_payload):
    middleware = HandoffSummarizationMiddleware(model=SimpleNamespace())

    captured = {}

    monkeypatch.setattr(
        "deepagents.middleware.handoff_summarization.generate_handoff_summary",
        lambda **kwargs: stub_summary,
    )

    def _fake_interrupt(payload):
        captured.update(payload)
        return decision_payload

    monkeypatch.setattr("langgraph.types.interrupt", _fake_interrupt)

    runtime = _runtime(metadata={"assistant_id": "assistant-1"}, configurable={"thread_id": "thread-1"})

    update = middleware.after_model(_state(), runtime)

    assert captured["action_requests"][0]["name"] == HANDOFF_ACTION_NAME
    args = captured["action_requests"][0]["args"]
    assert args["handoff_id"] == stub_summary.handoff_id
    assert args["summary_json"]["title"] == "Escalation"
    assert captured["metadata"]["handoff"]["pending"] is True

    assert update["handoff_requested"] is False
    assert update["handoff_decision"]["type"] == "approve"
    assert update["handoff_approved"] is True


def test_handoff_middleware_normalizes_edit_decision(monkeypatch, stub_summary):
    middleware = HandoffSummarizationMiddleware(model=SimpleNamespace())

    monkeypatch.setattr(
        "deepagents.middleware.handoff_summarization.generate_handoff_summary",
        lambda **kwargs: stub_summary,
    )

    def _fake_interrupt(payload):
        overrides = dict(payload["action_requests"][0]["args"])
        overrides["summary_json"] = {"title": "Human", "tldr": "Edited", "body": ["Updated"]}
        overrides["summary_md"] = "### Human Summary"
        return {
            "decisions": [
                {
                    "type": "edit",
                    "edited_action": {
                        "name": HANDOFF_ACTION_NAME,
                        "args": overrides,
                    },
                }
            ]
        }

    monkeypatch.setattr("langgraph.types.interrupt", _fake_interrupt)

    runtime = _runtime(metadata={"assistant_id": "assistant-1"}, configurable={"thread_id": "thread-1"})

    update = middleware.after_model(_state(), runtime)

    decision = update["handoff_decision"]
    assert decision["type"] == "edit"
    assert decision["summary_json"]["title"] == "Human"
    assert decision["summary_md"] == "### Human Summary"
    assert update["handoff_approved"] is False
