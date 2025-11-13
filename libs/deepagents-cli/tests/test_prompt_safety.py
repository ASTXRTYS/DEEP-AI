"""Tests for the SafePrompt wrapper."""

from __future__ import annotations

from collections import deque
from typing import Any

from rich.console import Console

from deepagents_cli.prompt_safety import (
    PromptOutcome,
    PromptSafetyConfig,
    PromptStatus,
    SafePrompt,
)
from deepagents_cli.rich_ui import RichPrompt


def test_safe_prompt_limits_attempts_and_reports_remaining(monkeypatch):
    console = Console(record=True)
    safe_prompt = SafePrompt(console, PromptSafetyConfig(max_attempts=2, timeout_seconds=30.0))

    call_count = {"count": 0}

    def fake_prompt(self, *_, **__):
        call_count["count"] += 1
        return PromptOutcome(PromptStatus.OK, "   ")

    monkeypatch.setattr(SafePrompt, "_prompt_once", fake_prompt)

    result = safe_prompt.ask_text("Choose option:", allow_blank=False)

    assert result is None
    assert call_count["count"] == 2  # exhausted attempts
    output = console.export_text()
    assert "1 attempts left" in output
    assert "Maximum attempts exceeded" in output


def test_safe_prompt_times_out(monkeypatch):
    console = Console(record=True)
    safe_prompt = SafePrompt(console, PromptSafetyConfig(max_attempts=5, timeout_seconds=1))

    def fake_prompt(self, *_, **__):
        return PromptOutcome(PromptStatus.TIMEOUT, None)

    monkeypatch.setattr(SafePrompt, "_prompt_once", fake_prompt)

    result = safe_prompt.ask_text("Choose option:")

    assert result is None
    assert "timed out" in console.export_text().lower()


def test_safe_prompt_rejects_whitespace_only_input(monkeypatch):
    console = Console(record=True)
    safe_prompt = SafePrompt(console, PromptSafetyConfig(max_attempts=3, timeout_seconds=30.0))
    responses = deque(
        [
            PromptOutcome(PromptStatus.OK, "   "),
            PromptOutcome(PromptStatus.OK, "valid input"),
        ]
    )

    def fake_prompt(self, *_, **__):
        return responses.popleft()

    monkeypatch.setattr(SafePrompt, "_prompt_once", fake_prompt)

    result = safe_prompt.ask_text("Enter value:", allow_blank=False)

    assert result == "valid input"
    output = console.export_text()
    assert "cannot be empty" in output.lower()


class _RecordingSafePrompt:
    """Helper to capture kwargs passed into RichPrompt safe prompt helpers."""

    def __init__(self, *, text_result: str | None = "", confirm_result: bool | None = False):
        self.text_result = text_result
        self.confirm_result = confirm_result
        self.last_text_kwargs: dict[str, Any] | None = None
        self.last_confirm_kwargs: dict[str, Any] | None = None

    def ask_confirm(self, _prompt_text: str, **kwargs):
        self.last_confirm_kwargs = kwargs
        return self.confirm_result

    def ask_text(self, _prompt_text: str, **kwargs):
        self.last_text_kwargs = kwargs
        return self.text_result


def test_rich_prompt_confirm_propagates_none():
    prompt = RichPrompt(Console(record=True))
    recorder = _RecordingSafePrompt(confirm_result=None)
    prompt.safe_prompt = recorder  # type: ignore[assignment]

    assert prompt.confirm("Proceed?") is None


def test_rich_prompt_text_input_respects_allow_blank_flag():
    prompt = RichPrompt(Console(record=True))
    accepting_prompt = _RecordingSafePrompt(text_result="")
    prompt.safe_prompt = accepting_prompt  # type: ignore[assignment]

    assert prompt.text_input("Enter optional", allow_blank=True) == ""
    assert accepting_prompt.last_text_kwargs is not None
    assert accepting_prompt.last_text_kwargs.get("allow_blank") is True

    rejecting_prompt = _RecordingSafePrompt(text_result="value")
    prompt.safe_prompt = rejecting_prompt  # type: ignore[assignment]
    prompt.text_input("Enter required")
    assert rejecting_prompt.last_text_kwargs is not None
    assert rejecting_prompt.last_text_kwargs.get("allow_blank") is False
