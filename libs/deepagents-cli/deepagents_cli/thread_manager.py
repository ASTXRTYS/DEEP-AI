"""Thread management for DeepAgents CLI.

This module provides ThreadManager for creating, switching, and managing
conversation threads. Each thread maintains its own conversation history
in the LangGraph checkpointer while sharing access to /memories/ files.

Thread ID Format: {assistant_id}:{uuid_short}
Example: agent:a1b2c3d4

Metadata Storage: ~/.deepagents/{agent}/threads.json
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TypedDict


class ThreadMetadata(TypedDict):
    """Metadata for a conversation thread."""

    id: str
    """Thread ID in format {assistant_id}:{uuid_short}"""

    created: str
    """ISO 8601 timestamp when thread was created"""

    last_used: str
    """ISO 8601 timestamp when thread was last accessed"""

    parent_id: str | None
    """Parent thread ID if this was forked, None otherwise"""

    name: str | None
    """Optional human-readable name for the thread"""


class ThreadManager:
    """Manages conversation threads for a DeepAgents CLI agent.

    Each agent (identified by assistant_id) has its own set of threads stored
    in ~/.deepagents/{assistant_id}/threads.json. The manager handles:
    - Creating new threads with unique IDs
    - Switching between existing threads
    - Listing all available threads
    - Forking threads to branch conversations

    Thread IDs follow the format: {assistant_id}:{uuid_short}
    Example: agent:a1b2c3d4

    The current thread ID is tracked in-memory and determines which conversation
    history the LangGraph checkpointer loads.

    Args:
        agent_dir: Path to the agent's directory (e.g., ~/.deepagents/agent)
        assistant_id: Agent identifier (e.g., "agent")

    Example:
        ```python
        from pathlib import Path
        agent_dir = Path.home() / ".deepagents" / "agent"
        manager = ThreadManager(agent_dir, "agent")

        # Create new thread
        thread_id = manager.create_thread()

        # List threads
        threads = manager.list_threads()

        # Switch thread
        manager.switch_thread("agent:a1b2c3d4")

        # Get current thread
        current = manager.current_thread_id
        ```
    """

    def __init__(self, agent_dir: Path, assistant_id: str):
        """Initialize ThreadManager.

        Args:
            agent_dir: Path to agent directory (e.g., ~/.deepagents/agent)
            assistant_id: Agent identifier (e.g., "agent")
        """
        self.agent_dir = Path(agent_dir)
        self.assistant_id = assistant_id
        self.threads_file = self.agent_dir / "threads.json"
        self.current_thread_id: str | None = None

        # Ensure agent directory exists
        self.agent_dir.mkdir(parents=True, exist_ok=True)

        # Load or initialize threads metadata
        self._load_or_initialize()

    def _load_or_initialize(self) -> None:
        """Load threads metadata from file or initialize with default thread."""
        if self.threads_file.exists():
            # Load existing threads
            try:
                with open(self.threads_file) as f:
                    data = json.load(f)
                    threads = data.get("threads", [])
                    current_id = data.get("current_thread_id")

                    # Set current thread (use last thread if current_id not found)
                    if current_id and any(t["id"] == current_id for t in threads):
                        self.current_thread_id = current_id
                    elif threads:
                        # Use most recently used thread
                        threads_sorted = sorted(
                            threads, key=lambda t: t.get("last_used", ""), reverse=True
                        )
                        self.current_thread_id = threads_sorted[0]["id"]
            except (json.JSONDecodeError, KeyError, ValueError):
                # Corrupted file, reinitialize
                self._initialize_default_thread()
        else:
            # No threads file, create default thread
            self._initialize_default_thread()

    def _initialize_default_thread(self) -> None:
        """Initialize with a default thread."""
        default_id = f"{self.assistant_id}:main"
        now = datetime.utcnow().isoformat() + "Z"

        threads = [
            ThreadMetadata(
                id=default_id,
                created=now,
                last_used=now,
                parent_id=None,
                name="Main thread",
            )
        ]

        self.current_thread_id = default_id
        self._save_threads(threads)

    def _save_threads(self, threads: list[ThreadMetadata]) -> None:
        """Save threads metadata to file.

        Args:
            threads: List of thread metadata to save
        """
        data = {"threads": threads, "current_thread_id": self.current_thread_id}

        with open(self.threads_file, "w") as f:
            json.dump(data, f, indent=2)

    def _load_threads(self) -> list[ThreadMetadata]:
        """Load threads metadata from file.

        Returns:
            List of thread metadata
        """
        if not self.threads_file.exists():
            return []

        try:
            with open(self.threads_file) as f:
                data = json.load(f)
                return data.get("threads", [])
        except (json.JSONDecodeError, KeyError):
            return []

    def create_thread(self, name: str | None = None, parent_id: str | None = None) -> str:
        """Create a new thread.

        Args:
            name: Optional human-readable name for the thread
            parent_id: Optional parent thread ID (for forking)

        Returns:
            The new thread ID in format {assistant_id}:{uuid_short}

        Example:
            >>> manager.create_thread()
            'agent:a1b2c3d4'
            >>> manager.create_thread(name="Web scraper project")
            'agent:xyz789ab'
        """
        # Generate unique ID
        uuid_short = uuid.uuid4().hex[:8]
        thread_id = f"{self.assistant_id}:{uuid_short}"

        # Create metadata
        now = datetime.utcnow().isoformat() + "Z"
        metadata = ThreadMetadata(
            id=thread_id,
            created=now,
            last_used=now,
            parent_id=parent_id,
            name=name,
        )

        # Add to threads list
        threads = self._load_threads()
        threads.append(metadata)
        self._save_threads(threads)

        # Switch to new thread
        self.current_thread_id = thread_id

        return thread_id

    def switch_thread(self, thread_id: str) -> None:
        """Switch to an existing thread.

        Args:
            thread_id: Thread ID to switch to

        Raises:
            ValueError: If thread_id doesn't exist

        Example:
            >>> manager.switch_thread("agent:a1b2c3d4")
        """
        threads = self._load_threads()

        # Find thread
        thread = next((t for t in threads if t["id"] == thread_id), None)
        if not thread:
            available_ids = [t["id"] for t in threads]
            raise ValueError(
                f"Thread '{thread_id}' not found. Available threads: {', '.join(available_ids)}"
            )

        # Update last_used timestamp
        thread["last_used"] = datetime.utcnow().isoformat() + "Z"

        # Update current thread
        self.current_thread_id = thread_id
        self._save_threads(threads)

    def list_threads(self) -> list[ThreadMetadata]:
        """List all available threads, sorted by last_used (most recent first).

        Returns:
            List of thread metadata dictionaries

        Example:
            >>> threads = manager.list_threads()
            >>> for thread in threads:
            ...     print(f"{thread['id']}: {thread['name']}")
            agent:a1b2c3d4: Main thread
            agent:xyz789ab: Web scraper project
        """
        threads = self._load_threads()
        # Sort by last_used, most recent first
        return sorted(threads, key=lambda t: t.get("last_used", ""), reverse=True)

    def get_current_thread_id(self) -> str:
        """Get the current thread ID.

        Returns:
            Current thread ID

        Example:
            >>> manager.get_current_thread_id()
            'agent:a1b2c3d4'
        """
        if self.current_thread_id is None:
            # Should never happen due to initialization, but handle gracefully
            self._initialize_default_thread()

        return self.current_thread_id

    def fork_thread(self, source_thread_id: str | None = None, name: str | None = None) -> str:
        """Fork a thread, creating a new thread with the same conversation history.

        The new thread will inherit all messages from the source thread up to the
        current point. Future messages will diverge between the two threads.

        Note: The actual conversation copying happens at the LangGraph checkpointer
        level when we pass the new thread_id with update_state. This method just
        creates the metadata entry with parent tracking.

        Args:
            source_thread_id: Thread to fork from (defaults to current thread)
            name: Optional name for the forked thread

        Returns:
            The new thread ID

        Raises:
            ValueError: If source_thread_id doesn't exist

        Example:
            >>> new_id = manager.fork_thread()  # Fork current thread
            >>> new_id = manager.fork_thread("agent:a1b2c3d4", "Experiment branch")
        """
        # Default to current thread
        if source_thread_id is None:
            source_thread_id = self.current_thread_id

        # Verify source thread exists
        threads = self._load_threads()
        source_thread = next((t for t in threads if t["id"] == source_thread_id), None)
        if not source_thread:
            available_ids = [t["id"] for t in threads]
            raise ValueError(
                f"Source thread '{source_thread_id}' not found. Available: {', '.join(available_ids)}"
            )

        # Create new thread with parent tracking
        if name is None:
            name = f"Fork of {source_thread.get('name', source_thread_id)}"

        return self.create_thread(name=name, parent_id=source_thread_id)

    def get_thread_metadata(self, thread_id: str) -> ThreadMetadata | None:
        """Get metadata for a specific thread.

        Args:
            thread_id: Thread ID to get metadata for

        Returns:
            Thread metadata dict, or None if not found

        Example:
            >>> metadata = manager.get_thread_metadata("agent:a1b2c3d4")
            >>> print(metadata['created'])
            2025-01-11T20:30:00Z
        """
        threads = self._load_threads()
        return next((t for t in threads if t["id"] == thread_id), None)

    def rename_thread(self, thread_id: str, new_name: str) -> None:
        """Rename a thread.

        Args:
            thread_id: Thread ID to rename
            new_name: New name for the thread

        Raises:
            ValueError: If thread_id doesn't exist

        Example:
            >>> manager.rename_thread("agent:a1b2c3d4", "Production bugfix")
        """
        threads = self._load_threads()

        # Find and update thread
        thread = next((t for t in threads if t["id"] == thread_id), None)
        if not thread:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread["name"] = new_name
        self._save_threads(threads)
