"""Utilities for persisting handoff summaries to agent memory.

This module is the canonical source for writing/clearing the
``<current_thread_summary>`` block *and* for maintaining the shared
``HandoffMetadata`` contract that threads store in ``metadata["handoff"]``.
Both manual ``/handoff`` commands and middleware-triggered flows must route
through :func:`apply_handoff_acceptance` to keep behavior aligned.

For any future work that generalizes this lifecycle beyond the CLI, Jason is the
point of contact (see issue #91).
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from deepagents.middleware.handoff_summarization import HandoffSummary, render_summary_markdown

SUMMARY_START_TAG = "<current_thread_summary>"
SUMMARY_END_TAG = "</current_thread_summary>"
SUMMARY_PLACEHOLDER = "None recorded yet."


def _now_iso() -> str:
    """Return a UTC ISO-8601 timestamp suitable for metadata tags."""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class HandoffMetadata(TypedDict, total=False):
    """Canonical schema shared across CLI + middleware for handoff state."""

    handoff_id: str
    source_thread_id: str
    child_thread_id: str
    title: NotRequired[str | None]
    tldr: NotRequired[str | None]
    pending: bool
    cleanup_required: bool
    created_at: str
    last_cleanup_at: NotRequired[str | None]


def build_handoff_metadata(
    *,
    handoff_id: str,
    source_thread_id: str,
    child_thread_id: str,
    summary_json: dict[str, Any],
    pending: bool,
    cleanup_required: bool,
) -> HandoffMetadata:
    """Return a normalized metadata block for parent/child threads.

    Mutates ``summary_json`` so downstream consumers (like middleware traces)
    have access to the canonical identifiers produced during acceptance.
    """

    created_at = summary_json.get("created_at")
    if not created_at:
        created_at = _now_iso()
        summary_json["created_at"] = created_at

    summary_json.setdefault("handoff_id", handoff_id)
    summary_json.setdefault("source_thread_id", source_thread_id)
    summary_json["child_thread_id"] = child_thread_id

    metadata: HandoffMetadata = {
        "handoff_id": handoff_id,
        "source_thread_id": source_thread_id,
        "child_thread_id": child_thread_id,
        "title": summary_json.get("title"),
        "tldr": summary_json.get("tldr"),
        "pending": pending,
        "cleanup_required": cleanup_required,
        "created_at": created_at,
        "last_cleanup_at": None,
    }
    return metadata


def ensure_summary_section(text: str) -> str:
    """Ensure the agent.md content contains a summary section block."""

    if SUMMARY_START_TAG in text and SUMMARY_END_TAG in text:
        return text

    block = (
        f"\n\n{SUMMARY_START_TAG}\n{SUMMARY_PLACEHOLDER}\n{SUMMARY_END_TAG}\n"
    )
    return text.rstrip() + block + "\n"


def replace_summary_block(text: str, summary_md: str) -> str:
    """Replace the current summary block contents with the provided Markdown."""

    prepared = ensure_summary_section(text)
    start_index = prepared.index(SUMMARY_START_TAG) + len(SUMMARY_START_TAG)
    end_index = prepared.index(SUMMARY_END_TAG)

    before = prepared[:start_index]
    after = prepared[end_index:]
    new_content = "\n" + summary_md.strip() + "\n"
    return before + new_content + after


def clear_summary_block(text: str) -> str:
    """Reset the summary block to its placeholder content."""

    prepared = ensure_summary_section(text)
    start_index = prepared.index(SUMMARY_START_TAG) + len(SUMMARY_START_TAG)
    end_index = prepared.index(SUMMARY_END_TAG)
    before = prepared[:start_index]
    after = prepared[end_index:]
    return before + "\n" + SUMMARY_PLACEHOLDER + "\n" + after


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, path)


def write_summary_block(path: Path, summary_md: str) -> None:
    """Update the summary block inside agent.md with the provided content."""

    if path.exists():
        raw = path.read_text(encoding="utf-8")
    else:
        raw = SUMMARY_START_TAG + f"\n{SUMMARY_PLACEHOLDER}\n" + SUMMARY_END_TAG
    updated = replace_summary_block(raw, summary_md)
    _atomic_write(path, updated)


def clear_summary_block_file(path: Path) -> None:
    """Replace the summary block with the placeholder string."""

    if path.exists():
        raw = path.read_text(encoding="utf-8")
    else:
        raw = SUMMARY_START_TAG + f"\n{SUMMARY_PLACEHOLDER}\n" + SUMMARY_END_TAG
    updated = clear_summary_block(raw)
    _atomic_write(path, updated)


def apply_handoff_acceptance(
    *,
    session_state,
    summary: HandoffSummary,
    summary_md: str,
    summary_json: dict[str, Any],
    parent_thread_id: str,
    agent=None,
) -> str:
    """Persist the accepted summary and create the handoff child thread.

    This function is the single source of truth for the parent/child metadata
    contract used by both middleware and the CLI cleanup pass. Parent threads
    receive ``pending=False`` / ``cleanup_required=False`` while the child is
    marked ``pending=True`` / ``cleanup_required=True`` until its first
    response triggers :class:`HandoffCleanupMiddleware`.

    Implements transaction-like rollback semantics to prevent inconsistent state
    on partial failures. If any step fails, all prior changes are rolled back.

    Args:
        session_state: Session state with thread_manager
        summary: Generated handoff summary
        summary_md: Markdown-formatted summary
        summary_json: JSON representation of summary
        parent_thread_id: Source thread ID
        agent: Optional compiled graph for thread deletion during rollback

    Returns:
        Created child thread ID

    Raises:
        Exception: If handoff acceptance fails (after rollback attempt)
    """
    import logging

    logger = logging.getLogger(__name__)

    thread_manager = session_state.thread_manager
    agent_md_path = thread_manager.agent_dir / "agent.md"
    child_thread_id: str | None = None

    try:
        # Step 1: Write summary block
        write_summary_block(agent_md_path, summary_md)
        logger.debug(f"Handoff: Wrote summary block to {agent_md_path}")

        # Step 2: Create child thread
        child_name = summary_json.get("title") or "Handoff continuation"
        child_thread_id = thread_manager.create_thread(
            name=child_name,
            parent_id=parent_thread_id,
            metadata={
                "handoff": {
                    "handoff_id": summary.handoff_id,
                    "source_thread_id": parent_thread_id,
                    "pending": True,
                    "cleanup_required": True,
                }
            },
        )
        logger.debug(f"Handoff: Created child thread {child_thread_id}")

        # Step 3: Build metadata for parent and child
        parent_metadata = build_handoff_metadata(
            handoff_id=summary.handoff_id,
            source_thread_id=parent_thread_id,
            child_thread_id=child_thread_id,
            summary_json=summary_json,
            pending=False,
            cleanup_required=False,
        )
        child_metadata = build_handoff_metadata(
            handoff_id=summary.handoff_id,
            source_thread_id=parent_thread_id,
            child_thread_id=child_thread_id,
            summary_json=summary_json,
            pending=True,
            cleanup_required=True,
        )

        # Step 4: Update parent metadata
        thread_manager.update_thread_metadata(parent_thread_id, {"handoff": parent_metadata})
        logger.debug(f"Handoff: Updated parent metadata for {parent_thread_id}")

        # Step 5: Update child metadata
        thread_manager.update_thread_metadata(child_thread_id, {"handoff": child_metadata})
        logger.debug(f"Handoff: Updated child metadata for {child_thread_id}")

        return child_thread_id

    except Exception as exc:
        # Rollback all changes on any failure
        logger.error(
            f"Handoff acceptance failed at handoff_id={summary.handoff_id}, "
            f"parent={parent_thread_id}, child={child_thread_id}: {exc}",
            exc_info=True,
        )

        # Rollback step 1: Clear summary block
        try:
            clear_summary_block_file(agent_md_path)
            logger.info(f"Handoff rollback: Cleared summary block from {agent_md_path}")
        except Exception as rollback_exc:  # pragma: no cover
            logger.warning(f"Handoff rollback: Failed to clear summary block: {rollback_exc}")

        # Rollback step 2: Delete child thread if it was created
        if child_thread_id and agent:
            try:
                thread_manager.delete_thread(child_thread_id, agent)
                logger.info(f"Handoff rollback: Deleted child thread {child_thread_id}")
            except Exception as rollback_exc:  # pragma: no cover
                logger.warning(
                    f"Handoff rollback: Failed to delete child thread {child_thread_id}: {rollback_exc}"
                )
        elif child_thread_id:
            logger.warning(
                f"Handoff rollback: Cannot delete child thread {child_thread_id} "
                "(agent not provided to apply_handoff_acceptance)"
            )

        # Re-raise original exception for caller to handle
        raise


__all__ = [
    "HandoffMetadata",
    "apply_handoff_acceptance",
    "build_handoff_metadata",
    "ensure_summary_section",
    "replace_summary_block",
    "write_summary_block",
    "clear_summary_block",
    "clear_summary_block_file",
    "render_summary_markdown",
    "SUMMARY_START_TAG",
    "SUMMARY_END_TAG",
    "SUMMARY_PLACEHOLDER",
]
