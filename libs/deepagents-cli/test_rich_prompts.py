#!/usr/bin/env python3
"""Test script for Rich async prompts.

This script tests the new Rich-based async prompts that replaced Questionary.
"""

import asyncio

from rich.console import Console
from rich.panel import Panel

from deepagents_cli.rich_ui import RichPrompt


async def test_select_async():
    """Test async selection menu."""
    console = Console()
    rich_prompt = RichPrompt(console)

    console.print("\n[bold cyan]Testing async select menu:[/bold cyan]\n")

    # Test with context panel
    context_panel = Panel(
        "[bold yellow]WARNING: Test approval prompt[/bold yellow]\n\n"
        "Testing the new Rich-based selection menu that replaced Questionary.",
        border_style="yellow",
        padding=(0, 1),
    )

    decision = await rich_prompt.select_async(
        question="Choose an action:",
        choices=[
            ("approve", "✓  Approve"),
            ("reject", "✕  Reject"),
        ],
        default="approve",
        context_panel=context_panel,
    )

    console.print(f"\n[green]You selected: {decision}[/green]\n")
    return decision


async def test_text_input_async():
    """Test async text input with multiline support."""
    console = Console()
    rich_prompt = RichPrompt(console)

    console.print("\n[bold cyan]Testing async multiline text input:[/bold cyan]\n")

    feedback = await rich_prompt.text_input_async(
        prompt_text="Enter your feedback:",
        multiline=True,
        validate=lambda text: True if len(text.strip()) > 0 else "Feedback cannot be empty",
    )

    if feedback:
        console.print(f"\n[green]Feedback received:[/green] {feedback[:100]}\n")
    else:
        console.print("\n[yellow]No feedback provided (cancelled)[/yellow]\n")

    return feedback


async def main():
    """Run all tests."""
    console = Console()

    console.print("[bold cyan]╔═══════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  Rich Async Prompts Test Suite       ║[/bold cyan]")
    console.print("[bold cyan]╚═══════════════════════════════════════╝[/bold cyan]")
    console.print()

    # Test 1: Select menu
    try:
        result1 = await test_select_async()
        console.print(f"✓ Select test completed: {result1}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Select test cancelled by user[/yellow]")

    # Test 2: Multiline text input
    try:
        result2 = await test_text_input_async()
        console.print(f"✓ Text input test completed: {result2 is not None}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Text input test cancelled by user[/yellow]")

    console.print("\n[bold green]All tests completed![/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
