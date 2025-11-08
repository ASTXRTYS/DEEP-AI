"""CLI utilities for reviewing and approving handoff summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.markdown import Markdown
from rich.panel import Panel

from .config import COLORS, console
from .handoff_summarization import render_summary_markdown


@dataclass
class HandoffProposal:
    """Payload presented to the user for approval."""

    handoff_id: str
    summary_json: dict[str, Any]
    summary_md: str
    parent_thread_id: str
    assistant_id: str


@dataclass
class HandoffDecision:
    """User decision captured via the CLI."""

    status: str
    summary_md: str
    summary_json: dict[str, Any] = field(default_factory=dict)


def _prompt_multiline(default: list[str]) -> list[str]:
    console.print(
        "Enter revised key points (one per line). Submit an empty line to finish."
    )
    lines: list[str] = []
    while True:
        line = input("> ").strip()
        if not line and not lines:
            return default
        if not line:
            break
        lines.append(line)
    return lines or default


def _apply_inline_edits(summary_json: dict[str, Any]) -> tuple[dict[str, Any], str]:
    updated = dict(summary_json)
    title = input(f"Title [{updated.get('title', 'Untitled')}]: ").strip()
    if title:
        updated["title"] = title

    tldr = input(f"TL;DR [{updated.get('tldr', 'Summary pending.')}]: ").strip()
    if tldr:
        updated["tldr"] = tldr

    body_default = [line.strip() for line in updated.get("body", []) if line.strip()]
    console.print()
    console.print("Current key points:")
    for idx, line in enumerate(body_default or ["(none)"]):
        console.print(f"  {idx + 1}. {line}")
    console.print()
    body = _prompt_multiline(body_default)
    updated["body"] = body

    summary_md = render_summary_markdown(updated["title"], updated["tldr"], body)
    return updated, summary_md


def prompt_handoff_decision(
    proposal: HandoffProposal,
    *,
    preview_only: bool = False,
) -> HandoffDecision:
    """Render the proposal and capture the user's decision."""

    console.print()
    console.print(
        Panel(
            Markdown(proposal.summary_md),
            border_style=COLORS["primary"],
            title="Handoff Summary Preview",
        )
    )

    if preview_only:
        console.print("[dim]Preview-only mode — no changes were applied.[/dim]")
        console.print()
        return HandoffDecision(status="preview", summary_md=proposal.summary_md, summary_json=proposal.summary_json)

    console.print(
        "Choose an action: (A)ccept, (E)dit, (D)ecline. Press Enter to accept.",
        style=COLORS["dim"],
    )

    while True:
        choice = input("Decision [A/e/d]: ").strip().lower()
        if choice in {"", "a", "accept"}:
            console.print("[green]✓ Handoff summary accepted[/green]")
            console.print()
            return HandoffDecision(
                status="accepted",
                summary_md=proposal.summary_md,
                summary_json=proposal.summary_json,
            )
        if choice in {"d", "decline"}:
            console.print("[yellow]Handoff summary declined by user.[/yellow]")
            console.print()
            return HandoffDecision(status="declined", summary_md=proposal.summary_md)
        if choice in {"e", "edit"}:
            console.print()
            console.print("[bold]Editing summary...[/bold]")
            updated_json, updated_md = _apply_inline_edits(proposal.summary_json)
            console.print()
            console.print("[green]✓ Updated summary captured[/green]")
            console.print()
            return HandoffDecision(status="accepted", summary_md=updated_md, summary_json=updated_json)

        console.print("[red]Invalid selection. Please enter A, E, or D.[/red]")


__all__ = ["HandoffProposal", "HandoffDecision", "prompt_handoff_decision"]
