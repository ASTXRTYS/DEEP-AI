from types import SimpleNamespace
from unittest.mock import patch

from deepagents.middleware.handoff_summarization import HandoffSummary

from deepagents_cli.handoff_persistence import (
    SUMMARY_END_TAG,
    SUMMARY_START_TAG,
    apply_handoff_acceptance,
    build_handoff_metadata,
)
from deepagents_cli.thread_manager import ThreadManager


@patch("deepagents_cli.server_client.create_thread_on_server")
def test_apply_handoff_acceptance_persists_metadata_and_summary(mock_create, tmp_path):
    mock_create.side_effect = ["parent-thread", "child-thread"]

    manager = ThreadManager(tmp_path / "agent", "assistant-1")
    parent_thread_id = manager.get_current_thread_id()
    session_state = SimpleNamespace(thread_manager=manager)

    summary = HandoffSummary(
        handoff_id="handoff-001",
        summary_json={
            "schema_version": 1,
            "handoff_id": "handoff-001",
            "assistant_id": "assistant-1",
            "parent_thread_id": parent_thread_id,
            "child_thread_id": None,
            "title": "Escalation",
            "body": ["Pending investigation"],
            "tldr": "Pending investigation",
            "model": "claude-sonnet-4",
            "tokens_used": 12,
            "created_at": "2024-01-01T00:00:00Z",
        },
        summary_md="""### Recent Thread Snapshot\n**Title:** Escalation\n**TL;DR:** Pending investigation\n\n#### Key Points\n- Pending investigation\n""",
    )

    child_thread_id = apply_handoff_acceptance(
        session_state=session_state,
        summary=summary,
        summary_md=summary.summary_md,
        summary_json=summary.summary_json,
        parent_thread_id=parent_thread_id,
    )

    assert child_thread_id == "child-thread"
    assert summary.summary_json["child_thread_id"] == child_thread_id
    assert summary.summary_json["handoff_id"] == "handoff-001"

    agent_md = (manager.agent_dir / "agent.md").read_text(encoding="utf-8")
    assert SUMMARY_START_TAG in agent_md and SUMMARY_END_TAG in agent_md
    assert "Escalation" in agent_md

    parent_meta = manager.get_thread_metadata(parent_thread_id)
    child_meta = manager.get_thread_metadata(child_thread_id)
    assert parent_meta is not None
    assert child_meta is not None

    parent_handoff = parent_meta["metadata"]["handoff"]
    child_handoff = child_meta["metadata"]["handoff"]

    assert parent_handoff["pending"] is False
    assert parent_handoff["cleanup_required"] is False
    assert parent_handoff["child_thread_id"] == child_thread_id
    assert parent_handoff["title"] == "Escalation"
    assert parent_handoff["tldr"] == "Pending investigation"
    assert parent_handoff["created_at"] == "2024-01-01T00:00:00Z"
    assert child_handoff["pending"] is True
    assert child_handoff["cleanup_required"] is True
    assert child_handoff["source_thread_id"] == parent_thread_id
    assert child_handoff["child_thread_id"] == child_thread_id
    assert child_handoff["last_cleanup_at"] is None


def test_build_handoff_metadata_populates_defaults():
    summary_json = {"title": "Demo", "tldr": "Summary"}

    metadata = build_handoff_metadata(
        handoff_id="handoff-xyz",
        source_thread_id="parent-1",
        child_thread_id="child-2",
        summary_json=summary_json,
        pending=True,
        cleanup_required=True,
    )

    assert metadata["handoff_id"] == "handoff-xyz"
    assert metadata["child_thread_id"] == "child-2"
    assert metadata["pending"] is True
    assert metadata["cleanup_required"] is True
    assert metadata["created_at"]
    assert summary_json["child_thread_id"] == "child-2"
    assert summary_json["source_thread_id"] == "parent-1"
    assert summary_json["created_at"] == metadata["created_at"]
