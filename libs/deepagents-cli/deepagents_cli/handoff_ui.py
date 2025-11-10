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


def prompt_handoff_decision(
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

    console.print()
    console.print(
        "  [green]☐ (A)pprove[/green] - Accept and proceed with handoff",
        style=COLORS["dim"],
    )
    console.print(
        "  [yellow]☐ (R)efine[/yellow] - Regenerate summary with feedback",
        style=COLORS["dim"],
    )
    console.print(
        "  [red]☐ (D)ecline[/red] - Cancel handoff",
        style=COLORS["dim"],
    )
    console.print()

    while True:
        choice = input("Decision [A/r/d, default=Approve]: ").strip().lower()

        if choice in {"", "a", "approve"}:
            console.print("[green]✓ Handoff summary approved[/green]")
            console.print()
            return HandoffDecision(
                type="approve",
                summary_md=proposal.summary_md,
                summary_json=proposal.summary_json,
            )

        elif choice in {"r", "refine"}:
            console.print()
            console.print("[yellow]Refining summary with LLM assistance...[/yellow]")
            console.print()
            console.print(
                "Enter your feedback for how to improve the summary.",
                style=COLORS["dim"],
            )
            console.print(
                "Examples: 'Add more technical details', 'Make it shorter', 'Focus on implementation changes'",
                style=COLORS["dim"],
            )
            console.print()

            # Collect multi-line feedback
            feedback_lines = []
            console.print("Enter feedback (press Enter twice to finish):")
            while True:
                line = input("> ").strip()
                if not line:
                    if not feedback_lines:
                        # Empty feedback - prompt again
                        console.print(
                            "[yellow]Please provide feedback for refinement.[/yellow]"
                        )
                        continue
                    # Empty line submitted after some feedback - done
                    break
                feedback_lines.append(line)

            feedback = " ".join(feedback_lines)
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

        elif choice in {"d", "decline", "reject"}:
            console.print("[yellow]Handoff declined by user.[/yellow]")
            console.print()
            return HandoffDecision(
                type="reject",
                summary_md=proposal.summary_md,
                summary_json=proposal.summary_json,
            )

        else:
            console.print(
                "[red]Invalid selection. Please enter A, R, or D.[/red]"
            )


__all__ = ["HandoffProposal", "HandoffDecision", "prompt_handoff_decision"]
