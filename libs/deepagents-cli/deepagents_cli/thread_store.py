"""Persistence helpers for thread metadata files."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

try:  # pragma: no cover - optional dependency for portability
    from filelock import FileLock, Timeout
except ImportError:  # pragma: no cover - fallback for environments without filelock
    import errno
    import fcntl
    import time

    class Timeout(Exception):
        """Raised when the fallback file lock cannot be acquired."""

    class FileLock:
        """Minimal advisory lock fallback using fcntl (POSIX only)."""

        def __init__(self, path: str) -> None:
            self.path = path
            self._fd: int | None = None

        def acquire(self, timeout: float | None = None) -> bool:
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                if self._fd is None:
                    self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR)
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except OSError as exc:
                    if exc.errno != errno.EWOULDBLOCK:
                        raise
                    if deadline is not None and time.monotonic() > deadline:
                        msg = f"Timed out acquiring lock {self.path}"
                        raise Timeout(msg) from None
                    time.sleep(0.1)

        def release(self) -> None:
            if self._fd is not None:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
                self._fd = None


if TYPE_CHECKING:
    from collections.abc import Iterator

    from .thread_manager import ThreadMetadata


class ThreadStoreError(Exception):
    """Base exception for thread store operations."""


class ThreadStoreCorruptError(ThreadStoreError):
    """Raised when the thread metadata file is unreadable."""


class ThreadStoreLockTimeout(ThreadStoreError):
    """Raised when the thread metadata lock cannot be acquired in time."""


@dataclass
class ThreadStoreData:
    """In-memory representation of thread metadata."""

    threads: list[ThreadMetadata]
    current_thread_id: str | None
    version: int

    def clone(self) -> ThreadStoreData:
        """Create a deep copy of the current data structure."""
        thread_copies = [cast("ThreadMetadata", dict(thread)) for thread in self.threads]
        return ThreadStoreData(
            threads=thread_copies,
            current_thread_id=self.current_thread_id,
            version=self.version,
        )


class ThreadStore:
    """Provides safe, atomic access to the threads.json metadata file."""

    VERSION = 1

    def __init__(self, threads_file: Path, *, timeout: float = 5.0) -> None:
        self.threads_file = Path(threads_file)
        self.threads_file.parent.mkdir(parents=True, exist_ok=True)

        lock_name = f"{self.threads_file.name}.lock"
        self._lock = FileLock(str(self.threads_file.parent / lock_name))
        self._timeout = timeout

    def load(self) -> ThreadStoreData:
        """Load metadata with the lock held, returning a copy for read-only usage."""
        self._acquire_lock()
        try:
            data = self._load_unlocked()
        finally:
            self._lock.release()
        return data.clone()

    @contextmanager
    def edit(self) -> Iterator[ThreadStoreData]:
        """Yield mutable metadata under an exclusive lock and persist on success."""
        self._acquire_lock()
        data = self._load_unlocked()
        try:
            yield data
        except Exception:  # pragma: no cover - re-raise for caller handling
            raise
        else:
            self._write_unlocked(data)
        finally:
            self._lock.release()

    def archive_corrupt_file(self) -> Path | None:
        """Rename a corrupt threads.json file for later inspection."""
        self._acquire_lock()
        try:
            if not self.threads_file.exists():
                return None
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            backup_name = f"{self.threads_file.name}.corrupt.{timestamp}"
            backup_path = self.threads_file.parent / backup_name
            os.replace(self.threads_file, backup_path)
            return backup_path
        finally:
            self._lock.release()

    def _acquire_lock(self) -> None:
        try:
            self._lock.acquire(timeout=self._timeout)
        except Timeout as exc:  # pragma: no cover - rare contention case
            msg = f"Timed out waiting for thread metadata lock: {self.threads_file}"
            raise ThreadStoreLockTimeout(msg) from exc

    def _load_unlocked(self) -> ThreadStoreData:
        if not self.threads_file.exists():
            return ThreadStoreData(threads=[], current_thread_id=None, version=self.VERSION)

        try:
            with self.threads_file.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except json.JSONDecodeError as exc:
            msg = f"Corrupt thread metadata: {self.threads_file}"
            raise ThreadStoreCorruptError(msg) from exc
        except OSError as exc:
            msg = f"Unable to read thread metadata: {self.threads_file}"
            raise ThreadStoreError(msg) from exc

        if not isinstance(raw, dict):
            msg = f"Unexpected data format in thread metadata: {self.threads_file}"
            raise ThreadStoreCorruptError(msg)

        threads_raw = raw.get("threads", [])
        if not isinstance(threads_raw, list):
            msg = f"Thread metadata is malformed: {self.threads_file}"
            raise ThreadStoreCorruptError(msg)

        threads = [
            cast("ThreadMetadata", dict(thread))
            for thread in threads_raw
            if isinstance(thread, dict)
        ]

        current_thread_id = raw.get("current_thread_id")
        version = int(raw.get("version", self.VERSION))

        return ThreadStoreData(
            threads=threads,
            current_thread_id=current_thread_id,
            version=version,
        )

    def _write_unlocked(self, data: ThreadStoreData) -> None:
        payload = {
            "version": data.version or self.VERSION,
            "threads": data.threads,
            "current_thread_id": data.current_thread_id,
        }

        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=self.threads_file.name,
            dir=self.threads_file.parent,
            text=True,
        )

        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(tmp_path, self.threads_file)
        finally:
            if os.path.exists(tmp_path):
                with suppress(OSError):
                    os.unlink(tmp_path)
