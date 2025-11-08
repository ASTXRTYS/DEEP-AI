"""Utilities for persisting handoff summaries to agent memory."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from deepagents.middleware.handoff_summarization import (
    HandoffSummary,
    render_summary_markdown,
)

SUMMARY_START_TAG = "<current_thread_summary>"
SUMMARY_END_TAG = "</current_thread_summary>"
SUMMARY_PLACEHOLDER = "None recorded yet."


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
) -> str:
    """Persist the accepted summary and create the handoff child thread."""

    thread_manager = session_state.thread_manager
    agent_md_path = thread_manager.agent_dir / "agent.md"
    write_summary_block(agent_md_path, summary_md)

    child_flags = {"pending": True, "cleanup_required": True}
    parent_flags = {"pending": False, "cleanup_required": False}

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
    summary_json["child_thread_id"] = child_thread_id

    base_metadata = {
        "handoff_id": summary.handoff_id,
        "source_thread_id": parent_thread_id,
        "child_thread_id": child_thread_id,
        "title": summary_json.get("title"),
        "tldr": summary_json.get("tldr"),
        "created_at": summary_json.get("created_at"),
        "last_cleanup_at": None,
    }

    thread_manager.update_thread_metadata(parent_thread_id, {"handoff": base_metadata | parent_flags})
    thread_manager.update_thread_metadata(child_thread_id, {"handoff": base_metadata | child_flags})

    return child_thread_id


__all__ = [
    "apply_handoff_acceptance",
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
