"""Thread management for DeepAgents CLI.

This module owns the lifecycle for conversation threads. Metadata lives in
`~/.deepagents/{agent}/threads.json`, persisted through :class:`ThreadStore`
for atomic, cross-process-safe updates. Conversation state remains in the
LangGraph checkpointer (SQLite by default).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from .thread_store import ThreadStore, ThreadStoreCorruptError, ThreadStoreData

if TYPE_CHECKING:
    from langgraph.graph.graph import CompiledGraph


def _now_iso() -> str:
    """Return a UTC timestamp suitable for thread metadata."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ThreadMetadata(TypedDict):
    """Metadata for a conversation thread."""

    id: str
    assistant_id: str
    created: str
    last_used: str
    parent_id: str | None
    name: str | None
    token_count: int | None  # Current context token count


@dataclass
class ThreadSyncReport:
    """Summary of a metadata/checkpointer reconciliation run."""

    metadata_only: list[ThreadMetadata]
    checkpoint_only: list[str]
    removed: list[ThreadMetadata]
    added: list[ThreadMetadata]
    current_thread_changed: bool
    new_current_thread_id: str | None

    @property
    def pending_changes(self) -> bool:
        """True if metadata and checkpoint states disagree."""
        return bool(self.metadata_only or self.checkpoint_only)


class ThreadManager:
    """Manages conversation threads for a DeepAgents CLI agent."""

    def __init__(self, agent_dir: Path, assistant_id: str):
        self.agent_dir = Path(agent_dir)
        self.assistant_id = assistant_id
        self.threads_file = self.agent_dir / "threads.json"
        self.agent_dir.mkdir(parents=True, exist_ok=True)

        self.store = ThreadStore(self.threads_file)
        self.current_thread_id: str | None = None

        self._load_or_initialize()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _safe_load(self) -> ThreadStoreData:
        """Load metadata, repairing corrupt files if necessary."""
        try:
            return self.store.load()
        except ThreadStoreCorruptError:
            self.store.archive_corrupt_file()
            self._initialize_default_thread()
            return self.store.load()

    def _initialize_default_thread(self) -> None:
        """Create a default thread when none exist."""
        from .server_client import create_thread_on_server

        # Create thread on server
        default_id = create_thread_on_server(name="Default conversation")
        now = _now_iso()
        default_thread: ThreadMetadata = {
            "id": default_id,
            "assistant_id": self.assistant_id,
            "created": now,
            "last_used": now,
            "parent_id": None,
            "name": "Default conversation",
            "token_count": 0,
        }

        with self.store.edit() as data:
            data.threads = [default_thread]
            data.current_thread_id = default_id
            data.version = ThreadStore.VERSION

        self.current_thread_id = default_id

    def _load_or_initialize(self) -> None:
        """Ensure metadata exists and the current thread is set."""
        data = self._safe_load()

        if not data.threads:
            self._initialize_default_thread()
            return

        if data.current_thread_id and any(t["id"] == data.current_thread_id for t in data.threads):
            self.current_thread_id = data.current_thread_id
            return

        fallback_id = self._select_most_recent_thread(data.threads)
        with self.store.edit() as editable:
            editable.current_thread_id = fallback_id
        self.current_thread_id = fallback_id

    @staticmethod
    def _select_most_recent_thread(threads: list[ThreadMetadata]) -> str:
        """Pick the thread most recently used, falling back to creation time."""
        if not threads:
            raise ValueError("No threads available to select from.")

        def sort_key(thread: ThreadMetadata) -> tuple[str, str]:
            return (
                thread.get("last_used") or thread.get("created") or "",
                thread.get("created") or "",
            )

        return sorted(threads, key=sort_key, reverse=True)[0]["id"]

    @staticmethod
    def _is_recent_timestamp(value: str | None, *, minutes: int = 5) -> bool:
        """Return True if the timestamp is within the grace window."""
        if not value:
            return False
        trimmed = value[:-1] if value.endswith("Z") else value
        try:
            timestamp = datetime.fromisoformat(trimmed)
        except ValueError:
            return False
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
        return timestamp >= datetime.now(timezone.utc) - timedelta(minutes=minutes)

    def _should_remove_metadata(
        self,
        thread: ThreadMetadata,
        *,
        current_thread_id: str | None,
        grace_minutes: int = 5,
    ) -> bool:
        """Determine whether a metadata-only thread should be dropped."""
        if thread["id"] == current_thread_id:
            return False
        return not self._is_recent_timestamp(thread.get("last_used"), minutes=grace_minutes)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------
    def create_thread(self, name: str | None = None, parent_id: str | None = None) -> str:
        """Create a new thread via the server API."""
        from .server_client import create_thread_on_server

        # Create thread on server
        thread_id = create_thread_on_server(name=name)
        now = _now_iso()

        metadata: ThreadMetadata = {
            "id": thread_id,
            "assistant_id": self.assistant_id,
            "created": now,
            "last_used": now,
            "parent_id": parent_id,
            "name": name,
            "token_count": 0,
        }

        with self.store.edit() as data:
            data.threads.append(metadata)
            data.current_thread_id = thread_id

        self.current_thread_id = thread_id
        return thread_id

    def switch_thread(self, thread_id: str) -> None:
        """Switch to an existing thread."""
        now = _now_iso()

        with self.store.edit() as data:
            thread = next((thread for thread in data.threads if thread["id"] == thread_id), None)
            if not thread:
                available = [t["id"] for t in data.threads]
                raise ValueError(
                    f"Thread '{thread_id}' not found. Available threads: {', '.join(available)}"
                )

            thread["last_used"] = now
            data.current_thread_id = thread_id

        self.current_thread_id = thread_id

    def list_threads(self) -> list[ThreadMetadata]:
        """List all threads sorted by last activity."""
        data = self._safe_load()
        return sorted(
            data.threads,
            key=lambda t: (t.get("last_used") or t.get("created") or ""),
            reverse=True,
        )

    def get_current_thread_id(self) -> str:
        """Return the current thread ID, creating a default thread if needed."""
        if self.current_thread_id is None:
            self._load_or_initialize()
        if self.current_thread_id is None:
            raise RuntimeError("Thread manager has no current thread.")
        return self.current_thread_id

    def fork_thread(
        self,
        agent: "CompiledGraph",
        source_thread_id: str | None = None,
        name: str | None = None,
    ) -> str:
        """Fork a thread via the server API."""
        from .server_client import fork_thread_on_server

        if source_thread_id is None:
            source_thread_id = self.get_current_thread_id()

        source_data = self._safe_load()
        source_thread = next((t for t in source_data.threads if t["id"] == source_thread_id), None)
        if not source_thread:
            available = [t["id"] for t in source_data.threads]
            raise ValueError(
                f"Source thread '{source_thread_id}' not found. Available: {', '.join(available)}"
            )

        # Fork thread on server
        new_thread_id = fork_thread_on_server(source_thread_id)

        # Also copy state in local checkpointer for compatibility
        source_config = {"configurable": {"thread_id": source_thread_id}}
        state = agent.get_state(source_config)
        new_config = {"configurable": {"thread_id": new_thread_id}}
        agent.update_state(new_config, state.values)

        now = _now_iso()
        fork_name = name or f"Fork of {source_thread.get('name', 'conversation')}"
        # Get token count for the forked thread
        source_token_count = source_thread.get("token_count", 0)
        new_thread: ThreadMetadata = {
            "id": new_thread_id,
            "assistant_id": self.assistant_id,
            "created": now,
            "last_used": now,
            "parent_id": source_thread_id,
            "name": fork_name,
            "token_count": source_token_count,  # Inherit from parent
        }

        with self.store.edit() as data:
            parent = next((t for t in data.threads if t["id"] == source_thread_id), None)
            if parent is None:
                raise ValueError(f"Source thread '{source_thread_id}' not found.")

            parent["last_used"] = now
            data.threads.append(new_thread)
            data.current_thread_id = new_thread_id

        self.current_thread_id = new_thread_id
        return new_thread_id

    def get_thread_metadata(self, thread_id: str) -> ThreadMetadata | None:
        """Return metadata for a specific thread."""
        data = self._safe_load()
        return next((t for t in data.threads if t["id"] == thread_id), None)

    def rename_thread(self, thread_id: str, new_name: str) -> None:
        """Rename a thread."""
        with self.store.edit() as data:
            thread = next((t for t in data.threads if t["id"] == thread_id), None)
            if not thread:
                raise ValueError(f"Thread '{thread_id}' not found.")
            thread["name"] = new_name

    def delete_thread(self, thread_id: str, agent: "CompiledGraph") -> None:
        """Delete a thread and its checkpoints."""
        current_id = self.get_current_thread_id()
        if thread_id == current_id:
            raise ValueError(
                "Cannot delete the current thread. Switch to another thread first with "
                "'/threads continue <id>' or create a new thread with '/new'."
            )

        data = self._safe_load()
        target = next((t for t in data.threads if t["id"] == thread_id), None)
        if not target:
            available = [t["id"] for t in data.threads]
            raise ValueError(
                f"Thread '{thread_id}' not found. Available threads: {', '.join(available)}"
            )

        try:
            agent.checkpointer.delete_thread(thread_id)  # type: ignore[attr-defined]
        except AttributeError:
            # Checkpointer may not expose delete_thread (e.g., remote deployments)
            pass

        with self.store.edit() as editable:
            editable.threads = [t for t in editable.threads if t["id"] != thread_id]
            if editable.current_thread_id == thread_id:
                editable.current_thread_id = (
                    editable.threads[0]["id"] if editable.threads else None
                )
            new_current = editable.current_thread_id

        self.current_thread_id = new_current

    # ------------------------------------------------------------------
    # Maintenance operations
    # ------------------------------------------------------------------
    def cleanup_old_threads(
        self, days_old: int, agent: "CompiledGraph", dry_run: bool = False
    ) -> tuple[int, list[str]]:
        """Delete threads whose last activity predates the cutoff."""
        data = self._safe_load()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)
        stale_threads: list[ThreadMetadata] = []

        for thread in data.threads:
            if thread["id"] == self.get_current_thread_id():
                continue
            last_used_str = thread.get("last_used", "")
            if last_used_str.endswith("Z"):
                last_used_str = last_used_str[:-1]
            try:
                last_used = datetime.fromisoformat(last_used_str).replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                continue
            if last_used < cutoff:
                stale_threads.append(thread)

        if dry_run:
            preview = [thread.get("name") or thread["id"] for thread in stale_threads]
            return len(preview), preview

        deleted_ids: list[str] = []
        deleted_names: list[str] = []
        for thread in stale_threads:
            thread_id = thread["id"]
            try:
                agent.checkpointer.delete_thread(thread_id)  # type: ignore[attr-defined]
            except AttributeError:
                pass
            except Exception:
                continue
            else:
                deleted_ids.append(thread_id)
                deleted_names.append(thread.get("name") or thread_id)

        if not deleted_ids:
            return 0, []

        with self.store.edit() as editable:
            editable.threads = [t for t in editable.threads if t["id"] not in set(deleted_ids)]
            if editable.current_thread_id and all(
                t["id"] != editable.current_thread_id for t in editable.threads
            ):
                editable.current_thread_id = (
                    editable.threads[0]["id"] if editable.threads else None
                )
            new_current = editable.current_thread_id

        self.current_thread_id = new_current
        return len(deleted_names), deleted_names

    def vacuum_database(self) -> dict[str, int]:
        """Run VACUUM on the SQLite checkpoint database."""
        import sqlite3

        checkpoint_db = self.agent_dir / "checkpoints.db"
        size_before = checkpoint_db.stat().st_size if checkpoint_db.exists() else 0

        try:
            conn = sqlite3.connect(str(checkpoint_db))
            conn.execute("VACUUM")
            conn.close()
        except Exception:
            return {"size_before": size_before, "size_after": size_before}

        size_after = checkpoint_db.stat().st_size if checkpoint_db.exists() else 0
        return {"size_before": size_before, "size_after": size_after}

    def get_database_stats(self) -> dict:
        """Gather simple statistics about the checkpoint database."""
        import sqlite3

        data = self._safe_load()
        checkpoint_db = self.agent_dir / "checkpoints.db"

        checkpoint_count = 0
        if checkpoint_db.exists():
            try:
                conn = sqlite3.connect(str(checkpoint_db))
                cursor = conn.execute("SELECT COUNT(*) FROM checkpoints")
                checkpoint_count = cursor.fetchone()[0]
                conn.close()
            except Exception:
                checkpoint_count = 0

        db_size_bytes = checkpoint_db.stat().st_size if checkpoint_db.exists() else 0

        oldest_thread = None
        newest_thread = None
        if data.threads:
            sorted_by_created = sorted(
                data.threads, key=lambda t: t.get("created") or ""
            )
            oldest = sorted_by_created[0]
            newest = sorted_by_created[-1]
            oldest_thread = {
                "id": oldest["id"],
                "name": oldest.get("name"),
                "created": oldest.get("created"),
            }
            newest_thread = {
                "id": newest["id"],
                "name": newest.get("name"),
                "created": newest.get("created"),
            }

        return {
            "thread_count": len(data.threads),
            "checkpoint_count": checkpoint_count,
            "db_size_bytes": db_size_bytes,
            "oldest_thread": oldest_thread,
            "newest_thread": newest_thread,
        }

    def touch_thread(self, thread_id: str, *, reason: str | None = None) -> bool:
        """Update the last-used timestamp for the given thread."""
        timestamp = _now_iso()
        try:
            with self.store.edit() as data:
                for thread in data.threads:
                    if thread["id"] == thread_id:
                        thread["last_used"] = timestamp
                        return True
        except ThreadStoreCorruptError:
            self._load_or_initialize()
        return False

    # ------------------------------------------------------------------
    # Reconciliation utilities
    # ------------------------------------------------------------------
    def reconcile_with_checkpointer(self, apply: bool = False) -> ThreadSyncReport:
        """Align threads.json metadata with checkpoint contents."""
        data = self._safe_load()
        metadata_map = {thread["id"]: thread for thread in data.threads}
        metadata_ids = set(metadata_map.keys())
        checkpoint_ids = self._list_checkpoint_thread_ids()

        metadata_only_candidates = [
            metadata_map[mid]
            for mid in (metadata_ids - checkpoint_ids)
            if self._should_remove_metadata(
                metadata_map[mid], current_thread_id=data.current_thread_id
            )
        ]
        checkpoint_only_ids = sorted(checkpoint_ids - metadata_ids)

        if not apply:
            return ThreadSyncReport(
                metadata_only=metadata_only_candidates,
                checkpoint_only=checkpoint_only_ids,
                removed=[],
                added=[],
                current_thread_changed=False,
                new_current_thread_id=data.current_thread_id,
            )

        removed_threads: list[ThreadMetadata] = []
        added_threads: list[ThreadMetadata] = []
        current_changed = False

        with self.store.edit() as editable:
            live_ids = {thread["id"] for thread in editable.threads}
            stale_threads = [
                cast(ThreadMetadata, thread)
                for thread in editable.threads
                if thread["id"] not in checkpoint_ids
                and self._should_remove_metadata(
                    cast(ThreadMetadata, thread),
                    current_thread_id=editable.current_thread_id,
                )
            ]
            stale_ids = {thread["id"] for thread in stale_threads}
            missing_ids = sorted(checkpoint_ids - live_ids)

            if stale_ids:
                editable.threads = [
                    thread for thread in editable.threads if thread["id"] not in stale_ids
                ]
                removed_threads = stale_threads

            if missing_ids:
                now = _now_iso()
                for thread_id in missing_ids:
                    recovered: ThreadMetadata = {
                        "id": thread_id,
                        "assistant_id": self.assistant_id,
                        "created": now,
                        "last_used": now,
                        "parent_id": None,
                        "name": None,
                        "token_count": 0,  # Will be updated on next interaction
                    }
                    editable.threads.append(recovered)
                    added_threads.append(recovered)

            if editable.current_thread_id and all(
                thread["id"] != editable.current_thread_id for thread in editable.threads
            ):
                editable.current_thread_id = (
                    editable.threads[0]["id"] if editable.threads else None
                )
                current_changed = True

            new_current = editable.current_thread_id

        self.current_thread_id = new_current

        return ThreadSyncReport(
            metadata_only=metadata_only_candidates,
            checkpoint_only=checkpoint_only_ids,
            removed=removed_threads,
            added=added_threads,
            current_thread_changed=current_changed,
            new_current_thread_id=new_current,
        )

    def _list_checkpoint_thread_ids(self) -> set[str]:
        """Return thread IDs present in the SQLite checkpointer."""
        import sqlite3

        checkpoint_db = self.agent_dir / "checkpoints.db"
        if not checkpoint_db.exists():
            return set()

        try:
            conn = sqlite3.connect(str(checkpoint_db))
            cursor = conn.execute("SELECT DISTINCT thread_id FROM checkpoints")
            thread_ids = {row[0] for row in cursor.fetchall() if row[0]}
            conn.close()
        except Exception:
            return set()

        return thread_ids

    def update_token_count(self, thread_id: str, token_count: int) -> None:
        """Update the token count for a thread.

        Args:
            thread_id: The thread ID to update.
            token_count: The new token count (current context size).
        """
        with self.store.edit() as data:
            for thread in data.threads:
                if thread["id"] == thread_id:
                    thread["token_count"] = token_count
                    break
