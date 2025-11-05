import sqlite3
import uuid
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver

from deepagents_cli.thread_manager import ThreadManager


def _insert_checkpoint(db_path, thread_id: str) -> None:
    conn = sqlite3.connect(str(db_path))
    saver = SqliteSaver(conn)
    saver.setup()
    checkpoint_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO checkpoints (
            thread_id,
            checkpoint_ns,
            checkpoint_id,
            parent_checkpoint_id,
            type,
            checkpoint,
            metadata
        ) VALUES (?, '', ?, NULL, ?, ?, ?)
        """,
        (thread_id, checkpoint_id, "json", b"{}", b"{}"),
    )
    conn.commit()
    conn.close()


@patch("deepagents_cli.server_client.create_thread_on_server")
@patch("deepagents_cli.server_client.fork_thread_on_server")
def test_touch_thread_updates_last_used(mock_fork, mock_create, tmp_path):
    # Mock server calls to return unique UUIDs
    mock_create.side_effect = lambda name=None, **kwargs: str(uuid.uuid4())
    mock_fork.side_effect = lambda thread_id=None, **kwargs: str(uuid.uuid4())

    agent_dir = tmp_path / "agent"
    manager = ThreadManager(agent_dir, "tester")

    thread_id = manager.get_current_thread_id()
    before = manager.get_thread_metadata(thread_id)
    assert before is not None

    assert manager.touch_thread(thread_id) is True

    after = manager.get_thread_metadata(thread_id)
    assert after is not None
    assert after["last_used"] >= before["last_used"]


@patch("deepagents_cli.server_client.create_thread_on_server")
@patch("deepagents_cli.server_client.fork_thread_on_server")
def test_reconcile_adds_missing_metadata(mock_fork, mock_create, tmp_path):
    # Mock server calls to return unique UUIDs
    mock_create.side_effect = lambda name=None, **kwargs: str(uuid.uuid4())
    mock_fork.side_effect = lambda thread_id=None, **kwargs: str(uuid.uuid4())

    agent_dir = tmp_path / "agent"
    manager = ThreadManager(agent_dir, "tester")

    missing_id = str(uuid.uuid4())
    db_path = agent_dir / "checkpoints.db"
    _insert_checkpoint(db_path, missing_id)

    preview = manager.reconcile_with_checkpointer(apply=False)
    assert missing_id in preview.checkpoint_only

    applied = manager.reconcile_with_checkpointer(apply=True)
    assert any(thread["id"] == missing_id for thread in applied.added)
    assert manager.get_thread_metadata(missing_id) is not None


@patch("deepagents_cli.server_client.create_thread_on_server")
@patch("deepagents_cli.server_client.fork_thread_on_server")
def test_reconcile_removes_stale_metadata(mock_fork, mock_create, tmp_path):
    # Mock server calls to return unique UUIDs
    mock_create.side_effect = lambda name=None, **kwargs: str(uuid.uuid4())
    mock_fork.side_effect = lambda thread_id, **kwargs: str(uuid.uuid4())
    agent_dir = tmp_path / "agent"
    manager = ThreadManager(agent_dir, "tester")

    default_id = manager.get_current_thread_id()
    stale_id = manager.create_thread(name="old thread")
    manager.switch_thread(default_id)

    with manager.store.edit() as data:  # type: ignore[attr-defined]
        for thread in data.threads:
            if thread["id"] == stale_id:
                thread["last_used"] = "2023-01-01T00:00:00Z"

    preview = manager.reconcile_with_checkpointer(apply=False)
    assert any(thread["id"] == stale_id for thread in preview.metadata_only)

    applied = manager.reconcile_with_checkpointer(apply=True)
    assert any(thread["id"] == stale_id for thread in applied.removed)
    assert manager.get_thread_metadata(stale_id) is None


@patch("deepagents_cli.server_client.create_thread_on_server")
@patch("deepagents_cli.server_client.fork_thread_on_server")
def test_reconcile_preserves_recent_metadata(mock_fork, mock_create, tmp_path):
    # Mock server calls to return unique UUIDs
    mock_create.side_effect = lambda name=None, **kwargs: str(uuid.uuid4())
    mock_fork.side_effect = lambda thread_id=None, **kwargs: str(uuid.uuid4())
    agent_dir = tmp_path / "agent"
    manager = ThreadManager(agent_dir, "tester")

    default_id = manager.get_current_thread_id()
    recent_id = manager.create_thread(name="recent thread")
    manager.switch_thread(default_id)

    preview = manager.reconcile_with_checkpointer(apply=False)
    assert all(thread["id"] != recent_id for thread in preview.metadata_only)
