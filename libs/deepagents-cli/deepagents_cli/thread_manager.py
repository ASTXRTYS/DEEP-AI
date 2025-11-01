"""Thread management for DeepAgents CLI.

This module provides ThreadManager for creating, switching, and managing
conversation threads. Each thread maintains its own conversation history
in the LangGraph checkpointer while sharing access to /memories/ files.

Thread ID Format: Pure UUID (LangGraph standard)
Example: 550e8400-e29b-41d4-a716-446655440000

Metadata Storage: ~/.deepagents/{agent}/threads.json

Note: We follow LangGraph's convention of using pure UUIDs for thread IDs.
This ensures compatibility with RemoteGraph and future LangGraph features.
The assistant_id is stored in metadata, not embedded in the thread ID.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from langgraph.graph.graph import CompiledGraph


class ThreadMetadata(TypedDict):
    """Metadata for a conversation thread."""

    id: str
    """Thread ID (pure UUID following LangGraph standard)"""

    assistant_id: str
    """Agent/assistant this thread belongs to"""

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
    - Creating new threads with unique UUIDs (LangGraph standard)
    - Switching between existing threads
    - Listing all available threads
    - Forking threads to branch conversations (with checkpoint state copying)

    Thread IDs are pure UUIDs following LangGraph's conventions for maximum
    compatibility (e.g., with RemoteGraph). The assistant_id is stored in
    metadata, not embedded in the thread ID.

    Example thread ID: 550e8400-e29b-41d4-a716-446655440000

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
        # Returns: "550e8400-e29b-41d4-a716-446655440000"

        # List threads
        threads = manager.list_threads()

        # Switch thread
        manager.switch_thread("550e8400-e29b-41d4-a716-446655440000")

        # Get current thread
        current = manager.current_thread_id

        # Fork thread (requires agent for checkpoint copying)
        new_id = manager.fork_thread(current, agent)
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
        """Initialize with a default thread using a pure UUID."""
        default_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"

        threads = [
            ThreadMetadata(
                id=default_id,
                assistant_id=self.assistant_id,
                created=now,
                last_used=now,
                parent_id=None,
                name="Default conversation",
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
        """Create a new thread with a pure UUID (LangGraph standard).

        Args:
            name: Optional human-readable name for the thread
            parent_id: Optional parent thread ID (for forking)

        Returns:
            The new thread ID (pure UUID)

        Example:
            >>> manager.create_thread()
            '550e8400-e29b-41d4-a716-446655440000'
            >>> manager.create_thread(name="Web scraper project")
            '9b2d5f7e-3c1a-4b8d-9e2f-1a3b4c5d6e7f'
        """
        # Generate pure UUID (LangGraph standard)
        thread_id = str(uuid.uuid4())

        # Create metadata
        now = datetime.utcnow().isoformat() + "Z"
        metadata = ThreadMetadata(
            id=thread_id,
            assistant_id=self.assistant_id,
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
            thread_id: Thread ID to switch to (pure UUID)

        Raises:
            ValueError: If thread_id doesn't exist

        Example:
            >>> manager.switch_thread("550e8400-e29b-41d4-a716-446655440000")
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
            550e8400-e29b-41d4-a716-446655440000: Default conversation
            9b2d5f7e-3c1a-4b8d-9e2f-1a3b4c5d6e7f: Web scraper project
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

    def fork_thread(
        self,
        agent: "CompiledGraph",
        source_thread_id: str | None = None,
        name: str | None = None,
    ) -> str:
        """Fork a thread, creating a new thread with the same conversation history.

        The new thread will inherit all messages from the source thread up to the
        current point. Future messages will diverge between the two threads.

        This method performs a true fork by:
        1. Creating a new thread with a unique UUID
        2. Copying the checkpoint state from the source thread to the new thread
        3. Storing metadata linking the new thread to its parent

        Args:
            agent: The compiled LangGraph agent (needed to copy checkpoint state)
            source_thread_id: Thread to fork from (defaults to current thread)
            name: Optional name for the forked thread

        Returns:
            The new thread ID (pure UUID)

        Raises:
            ValueError: If source_thread_id doesn't exist

        Example:
            >>> new_id = manager.fork_thread(agent)  # Fork current thread
            >>> new_id = manager.fork_thread(agent, "550e8400-...", "Experiment branch")
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

        # Generate new thread ID
        new_thread_id = str(uuid.uuid4())

        # Copy checkpoint state from source thread to new thread
        source_config = {"configurable": {"thread_id": source_thread_id}}
        state = agent.get_state(source_config)

        # Update state to new thread (this creates a fork in the checkpointer)
        new_config = {"configurable": {"thread_id": new_thread_id}}
        agent.update_state(new_config, state.values)

        # Create metadata with parent tracking
        if name is None:
            name = f"Fork of {source_thread.get('name', 'conversation')}"

        now = datetime.utcnow().isoformat() + "Z"
        metadata = ThreadMetadata(
            id=new_thread_id,
            assistant_id=self.assistant_id,
            created=now,
            last_used=now,
            parent_id=source_thread_id,
            name=name,
        )

        # Add to threads list
        threads.append(metadata)
        self._save_threads(threads)

        # Switch to new forked thread
        self.current_thread_id = new_thread_id

        return new_thread_id

    def get_thread_metadata(self, thread_id: str) -> ThreadMetadata | None:
        """Get metadata for a specific thread.

        Args:
            thread_id: Thread ID to get metadata for (pure UUID)

        Returns:
            Thread metadata dict, or None if not found

        Example:
            >>> metadata = manager.get_thread_metadata("550e8400-e29b-41d4-a716-446655440000")
            >>> print(metadata['created'])
            2025-01-11T20:30:00Z
        """
        threads = self._load_threads()
        return next((t for t in threads if t["id"] == thread_id), None)

    def rename_thread(self, thread_id: str, new_name: str) -> None:
        """Rename a thread.

        Args:
            thread_id: Thread ID to rename (pure UUID)
            new_name: New name for the thread

        Raises:
            ValueError: If thread_id doesn't exist

        Example:
            >>> manager.rename_thread("550e8400-e29b-41d4-a716-446655440000", "Production bugfix")
        """
        threads = self._load_threads()

        # Find and update thread
        thread = next((t for t in threads if t["id"] == thread_id), None)
        if not thread:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread["name"] = new_name
        self._save_threads(threads)
