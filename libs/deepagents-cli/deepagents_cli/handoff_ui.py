"""CLI utilities for reviewing and approving handoff summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich import box
from rich.markdown import Markdown
from rich.panel import Panel

from .config import console
from .rich_ui import RichPrompt


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

    # Use Rich prompts for selection
    rich_prompt = RichPrompt(console)

    console.print()
    try:
        decision = await rich_prompt.select_async(
            question="Review the handoff summary and choose an action:",
            choices=[
                ("approve", "✓  Approve (proceed with handoff)"),
                ("refine", "⟲  Refine (regenerate with feedback)"),
                ("decline", "✕  Decline (cancel handoff)"),
            ],
            default="approve",
        )
    except (KeyboardInterrupt, EOFError):
        console.print()
        console.print("[dim]✓ Handoff cancelled.[/dim]")
        console.print()
        return HandoffDecision(type="reject")

    # Handle cancellation (None return)
    if decision is None:
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

        try:
            feedback = await rich_prompt.text_input_async(
                prompt_text="Enter your feedback:",
                multiline=True,
                validate=lambda text: True
                if len(text.strip()) > 0
                else "Feedback cannot be empty for refinement",
            )
        except (KeyboardInterrupt, EOFError):
            feedback = None

        # Handle cancellation
        if feedback is None:
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
