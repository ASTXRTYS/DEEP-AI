"""Tests for the interactive thread picker fallbacks."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime

from deepagents_cli import commands


def _sample_thread(idx: int) -> dict:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "id": f"thread-{idx:02d}-abcdef0123456789",
        "assistant_id": "unit-test",
        "created": now,
        "last_used": now,
        "parent_id": None,
        "name": f"Thread {idx}",
    }


def test_select_thread_fallback_defaults_to_current(monkeypatch):
    threads = [_sample_thread(1), _sample_thread(2), _sample_thread(3)]

    current_id = threads[1]["id"]

    def fake_input(prompt: str) -> str:
        return ""  # Accept default

    monkeypatch.setattr(builtins, "input", fake_input)

    selected = commands._select_thread_interactively(threads, current_id)

    assert selected == current_id


def test_select_thread_fallback_accepts_numeric_choice(monkeypatch):
    threads = [_sample_thread(1), _sample_thread(2), _sample_thread(3)]

    def fake_input(prompt: str) -> str:
        return "3"  # Select third entry

    monkeypatch.setattr(builtins, "input", fake_input)

    selected = commands._select_thread_interactively(threads, threads[0]["id"])

    assert selected == threads[2]["id"]
