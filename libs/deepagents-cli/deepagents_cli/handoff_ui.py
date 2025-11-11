"""CLI utilities for reviewing and approving handoff summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich import box
from rich.markdown import Markdown
from rich.panel import Panel

from .config import COLORS, console


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

    type: str  # "approve", "refine", or "reject"
    feedback: str | None = None  # Refinement feedback if type == "refine"
    summary_md: str = ""
    summary_json: dict[str, Any] = field(default_factory=dict)


async def prompt_handoff_decision(
    proposal: HandoffProposal,
    *,
    preview_only: bool = False,
) -> HandoffDecision:
    """Render the proposal and capture the user's decision.

    Displays the handoff summary in a yellow panel (matching other interrupt styles)
    and prompts for: Approve / Refine / Reject.

    Args:
        proposal: The handoff summary to review
        preview_only: If True, skip decision prompt (for testing)

    Returns:
        HandoffDecision with type="approve", "refine", or "reject"
    """
    console.print()
    console.print(
        Panel(
            "[bold yellow]⚠️  Thread Handoff Requires Approval[/bold yellow]\n\n"
            + Markdown(proposal.summary_md).markup,
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )

    if preview_only:
        console.print("[dim]Preview-only mode — no changes were applied.[/dim]")
        console.print()
        return HandoffDecision(
            type="preview",
            summary_md=proposal.summary_md,
            summary_json=proposal.summary_json,
        )

    import questionary
    from questionary import Choice, Style

    # Handoff approval style
    handoff_style = Style(
        [
            ("qmark", f"{COLORS['primary']} bold"),
            ("question", "bold"),
            ("answer", f"{COLORS['primary']} bold"),
            ("pointer", f"{COLORS['primary']} bold"),
            ("highlighted", f"#ffffff bg:{COLORS['primary']} bold"),
            ("selected", f"{COLORS['primary']}"),
            ("instruction", "#888888 italic"),
            ("text", ""),
            ("search_success", f"{COLORS['primary']}"),  # Successful search results
            ("search_none", "#888888"),  # No search results message
            ("separator", "#888888"),  # Separators in lists
        ]
    )

    console.print()
    try:
        decision = await questionary.select(
            "Review the handoff summary and choose an action:",
            choices=[
                Choice(title="✓  Approve (proceed with handoff)", value="approve"),
                Choice(title="⟲  Refine (regenerate with feedback)", value="refine"),
                Choice(title="✕  Decline (cancel handoff)", value="decline"),
            ],
            default="approve",
            use_arrow_keys=True,
            use_indicator=True,
            use_shortcuts=True,  # Allow a/r/d shortcuts
            style=handoff_style,
            qmark="▶",
            pointer="●",
            instruction="(↑↓ navigate, Enter select, or press a/r/d)",
        ).ask_async()
    except (KeyboardInterrupt, EOFError):
        console.print()
        console.print("[dim]✓ Handoff cancelled.[/dim]")
        console.print()
        return HandoffDecision(type="reject")

    console.print()

    if decision == "approve":
        console.print("[green]✓ Handoff summary approved[/green]")
        console.print()
        return HandoffDecision(
            type="approve",
            summary_md=proposal.summary_md,
            summary_json=proposal.summary_json,
        )

    if decision == "refine":
        console.print()
        console.print("[yellow]Provide feedback to improve the summary:[/yellow]")
        console.print()
        console.print(
            "[dim]Examples: 'Add more technical details', 'Make it shorter', 'Focus on implementation changes'[/dim]"
        )
        console.print()

        try:
            feedback = await questionary.text(
                "Enter your feedback:",
                multiline=True,
                style=handoff_style,
                qmark="✎",
                instruction="(Type feedback, press Alt+Enter or Esc then Enter to finish)",
                validate=lambda text: len(text.strip()) > 0
                or "Feedback cannot be empty for refinement",
            ).ask_async()
        except (KeyboardInterrupt, EOFError):
            console.print()
            console.print("[dim]✓ Refinement cancelled.[/dim]")
            console.print()
            return HandoffDecision(type="reject")

        console.print()
        console.print(
            f"[dim]Feedback: {feedback[:100]}{'...' if len(feedback) > 100 else ''}[/dim]"
        )
        console.print()
        return HandoffDecision(
            type="refine",
            feedback=feedback,
            summary_md=proposal.summary_md,
            summary_json=proposal.summary_json,
        )

    # decline
    console.print("[yellow]✕ Handoff declined by user.[/yellow]")
    console.print()
    return HandoffDecision(
        type="reject",
        summary_md=proposal.summary_md,
        summary_json=proposal.summary_json,
    )


__all__ = ["HandoffDecision", "HandoffProposal", "prompt_handoff_decision"]
