from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from deepagents.middleware.handoff_summarization import (
    HANDOFF_ACTION_NAME,
    HandoffSummarizationMiddleware,
    HandoffSummary,
    generate_handoff_summary,
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


@pytest.mark.parametrize(
    "decision_payload",
    [
        {"decisions": [{"type": "approve"}]},
        {"decisions": [{"type": "approve", "message": "looks good"}]},
    ],
)
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
    assert args["iteration"] == 0
    assert "feedback" not in args
    assert "feedback_history" not in args
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


def test_handoff_middleware_runs_refinement_iteration(monkeypatch, stub_summary):
    middleware = HandoffSummarizationMiddleware(model=SimpleNamespace())

    generated_calls: list[dict[str, Any]] = []
    summaries: list[HandoffSummary] = []

    def _make_summary(idx: int, handoff_id: str | None = None) -> HandoffSummary:
        identifier = handoff_id or f"handoff-{idx}"
        summary_json = dict(stub_summary.summary_json)
        summary_json["handoff_id"] = identifier
        summary_json["title"] = f"Iteration {idx}"
        summary_md = f"### Iteration {idx}\n**TL;DR:** Pass {idx}\n\n#### Key Points\n- Body {idx}\n"
        return HandoffSummary(
            handoff_id=identifier,
            summary_json=summary_json,
            summary_md=summary_md,
        )

    def _fake_generate(**kwargs):
        generated_calls.append(kwargs)
        idx = len(generated_calls) - 1
        summary = _make_summary(idx, kwargs.get("handoff_id"))
        summaries.append(summary)
        return summary

    decision_queue = [
        {
            "decisions": [
                {
                    "type": "edit",
                    "edited_action": {
                        "name": HANDOFF_ACTION_NAME,
                        "args": {"feedback": "make this shorter"},
                    },
                }
            ]
        },
        {"decisions": [{"type": "approve"}]},
    ]
    captured_payloads: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "deepagents.middleware.handoff_summarization.generate_handoff_summary",
        _fake_generate,
    )

    def _fake_interrupt(payload):
        captured_payloads.append(payload)
        return decision_queue.pop(0)

    monkeypatch.setattr("langgraph.types.interrupt", _fake_interrupt)

    runtime = _runtime(metadata={"assistant_id": "assistant-1"}, configurable={"thread_id": "thread-1"})
    state = _state()

    first_update = middleware.after_model(state, runtime)
    assert first_update["handoff_requested"] is True
    assert first_update["_handoff_iteration"] == 1
    assert first_update["_handoff_feedback"] == "make this shorter"
    assert first_update["handoff_decision"]["type"] == "edit"
    assert first_update["_handoff_id"] == summaries[0].handoff_id
    assert first_update["_handoff_created_at"] == summaries[0].summary_json.get("created_at")
    state.update(first_update)

    second_update = middleware.after_model(state, runtime)
    assert second_update["handoff_requested"] is False
    assert second_update["handoff_approved"] is True
    assert second_update["_handoff_iteration"] == 0
    assert second_update["_handoff_id"] is None
    assert second_update["_handoff_created_at"] is None

    assert generated_calls[0]["iteration"] == 0
    assert generated_calls[0]["feedback"] is None
    assert generated_calls[1]["iteration"] == 1
    assert generated_calls[1]["feedback"] == "make this shorter"
    assert generated_calls[1]["previous_summary_md"] == summaries[0].summary_md
    assert generated_calls[1]["handoff_id"] == summaries[0].handoff_id

    assert captured_payloads[0]["action_requests"][0]["args"]["iteration"] == 0
    second_args = captured_payloads[1]["action_requests"][0]["args"]
    assert second_args["iteration"] == 1
    assert len(second_args["feedback_history"]) == 1
    assert second_args["feedback_history"][0]["feedback"] == "make this shorter"
    assert second_args["handoff_id"] == summaries[0].handoff_id


def test_handoff_middleware_enforces_iteration_cap(monkeypatch, stub_summary):
    middleware = HandoffSummarizationMiddleware(model=SimpleNamespace())

    monkeypatch.setattr(
        "deepagents.middleware.handoff_summarization.MAX_REFINEMENT_ITERATIONS",
        1,
    )
    monkeypatch.setattr(
        "deepagents.middleware.handoff_summarization.generate_handoff_summary",
        lambda **kwargs: stub_summary,
    )

    def _fake_interrupt(payload):
        return {
            "decisions": [
                {
                    "type": "edit",
                    "edited_action": {
                        "name": HANDOFF_ACTION_NAME,
                        "args": {"feedback": "too long"},
                    },
                }
            ]
        }

    monkeypatch.setattr("langgraph.types.interrupt", _fake_interrupt)

    runtime = _runtime(metadata={"assistant_id": "assistant-1"}, configurable={"thread_id": "thread-1"})
    update = middleware.after_model(_state(), runtime)

    assert update["handoff_requested"] is False
    assert update["handoff_approved"] is False
    assert update["_handoff_iteration"] == 0
    history = update["handoff_decision"]["feedback_history"]
    assert history[0]["feedback"] == "too long"
    assert "Reached maximum refinement iterations" in update["handoff_decision"]["message"]


def test_generate_handoff_summary_traces_iteration_metadata_and_tags():
    calls: list[dict[str, Any]] = []

    class RecordingLLM:
        def invoke(self, prompt, config=None, max_tokens=None):
            calls.append({"prompt": prompt, "config": config, "max_tokens": max_tokens})
            return SimpleNamespace(
                content="First sentence. Second sentence.",
                usage_metadata={"output_tokens": 42},
            )

    llm = RecordingLLM()
    messages = [HumanMessage(content="Hello world")]

    summary_initial = generate_handoff_summary(
        model=llm,
        messages=messages,
        assistant_id="assistant-1",
        parent_thread_id="thread-1",
        iteration=0,
    )

    summary_refined = generate_handoff_summary(
        model=llm,
        messages=messages,
        assistant_id="assistant-1",
        parent_thread_id="thread-1",
        feedback="make this shorter",
        previous_summary_md=summary_initial.summary_md,
        iteration=2,
        handoff_id=summary_initial.handoff_id,
        created_at=summary_initial.summary_json["created_at"],
    )

    assert len(calls) == 2

    initial_call = calls[0]
    refined_call = calls[1]

    for call in (initial_call, refined_call):
        assert isinstance(call["config"], dict)
        assert "run_name" in call["config"]
        assert "metadata" in call["config"]
        assert "tags" in call["config"]

    initial_config = initial_call["config"]
    refined_config = refined_call["config"]

    assert initial_config["run_name"] == "generate_handoff_summary_iter_0"
    assert refined_config["run_name"] == "generate_handoff_summary_iter_2"

    initial_meta = initial_config["metadata"]
    refined_meta = refined_config["metadata"]

    assert initial_meta["handoff_iteration"] == 0
    assert initial_meta["has_feedback"] is False
    assert initial_meta["summary_type"] == "initial"
    assert initial_meta["parent_thread_id"] == "thread-1"
    assert initial_meta["assistant_id"] == "assistant-1"
    assert initial_meta["handoff_id"] == summary_initial.handoff_id
    assert initial_meta["feedback_preview"] is None

    assert refined_meta["handoff_iteration"] == 2
    assert refined_meta["has_feedback"] is True
    assert refined_meta["summary_type"] == "refinement"
    assert refined_meta["parent_thread_id"] == "thread-1"
    assert refined_meta["assistant_id"] == "assistant-1"
    assert refined_meta["handoff_id"] == summary_refined.handoff_id
    assert refined_meta["feedback_preview"] == "make this shorter"

    initial_tags = initial_config["tags"]
    refined_tags = refined_config["tags"]

    assert initial_tags == ["handoff-summary", "iteration-0", "initial"]
    assert refined_tags == ["handoff-summary", "iteration-2", "refinement"]

    assert summary_refined.handoff_id == summary_initial.handoff_id
    assert summary_refined.summary_json["created_at"] == summary_initial.summary_json["created_at"]
