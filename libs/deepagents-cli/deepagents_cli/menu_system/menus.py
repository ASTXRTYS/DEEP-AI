"""Menu definitions and choice generation.

Provides functions to generate questionary choices for all menus
in the system, with dynamic, context-aware behavior.
"""

from questionary import Choice

from ..config import SessionState
from ..ui_constants import Icons


def get_main_menu_choices(session_state: SessionState) -> list[Choice]:
    """Generate main menu choices dynamically based on current state.

    Args:
        session_state: Current session state

    Returns:
        List of Choice objects for the main menu
    """
    return [
        Choice(
            title=f"{Icons.THREAD}  Threads        Manage conversation threads        (T)",
            value="threads",
            shortcut_key="t",
        ),
        Choice(
            title=f"{Icons.NEW}  New Thread     Start fresh conversation           (N)",
            value="new_thread",
            shortcut_key="n",
        ),
        Choice(
            title=f"{Icons.TOKENS}  Tokens         View usage statistics              (K)",
            value="tokens",
            shortcut_key="k",
        ),
        Choice(
            title=f"{Icons.HANDOFF}  Handoff        Create child thread                (H)",
            value="handoff",
            shortcut_key="h",
        ),
        Choice(
            title=f"{Icons.SETTINGS}   Settings       Configure CLI options              (S)",
            value="settings",
            shortcut_key="s",
        ),
        Choice(
            title=f"{Icons.HELP}  Help           Show commands and shortcuts        (I)",
            value="help",
            shortcut_key="i",
        ),
        Choice(
            title=f"{Icons.EXIT}  Exit           Quit application                   (Q)",
            value="exit",
            shortcut_key="q",
        ),
    ]


def get_thread_list_choices(threads: list[dict], current_id: str) -> list[Choice]:
    """Generate thread list choices with rich formatting.

    Args:
        threads: List of thread metadata dictionaries
        current_id: ID of the currently active thread

    Returns:
        List of Choice objects for the thread list
    """
    if not threads:
        return [
            Choice(
                title="[dim](No threads available)[/dim]",
                value=None,
                disabled=True,
            )
        ]

    choices = []
    for thread in threads:
        # Format thread summary
        thread_id_short = thread["id"][:8] if len(thread["id"]) > 8 else thread["id"]
        name = thread.get("name", "Untitled")
        message_count = thread.get("message_count", 0)
        tokens = thread.get("total_tokens", 0)

        # Format tokens with K suffix if > 1000
        tokens_str = f"{tokens / 1000:.1f}K" if tokens >= 1000 else str(tokens)

        # Build title with stats
        title_parts = [
            thread_id_short,
            name,
            f"· {message_count} msgs",
            f"· {tokens_str} tokens",
        ]

        # Add "current" indicator
        if thread["id"] == current_id:
            title_parts.append("· [bold]current[/bold]")

        title = "  ".join(title_parts)

        choices.append(
            Choice(
                title=title,
                value=thread["id"],
                description=thread.get("preview", ""),
            )
        )

    return choices


def get_thread_action_choices(thread_id: str, current_id: str) -> list[Choice]:
    """Generate action choices for a selected thread.

    Args:
        thread_id: ID of the selected thread
        current_id: ID of the currently active thread

    Returns:
        List of Choice objects for thread actions
    """
    choices = []

    # Only show "Switch" if not the current thread
    if thread_id != current_id:
        choices.append(
            Choice(
                title=f"{Icons.SWITCH}  Switch to this thread                                (S)",
                value="switch",
                shortcut_key="s",
            )
        )

    # Always show rename and delete
    choices.extend(
        [
            Choice(
                title=f"{Icons.RENAME}  Rename this thread                                   (R)",
                value="rename",
                shortcut_key="r",
            ),
            Choice(
                title=f"{Icons.DELETE}  Delete this thread                                  (D)",
                value="delete",
                shortcut_key="d",
            ),
            Choice(
                title=f"{Icons.BACK}  Back to thread list                                  (B)",
                value="back",
                shortcut_key="b",
            ),
        ]
    )

    return choices


def get_settings_menu_choices(session_state: SessionState) -> list[Choice]:
    """Generate settings menu choices based on current configuration.

    Args:
        session_state: Current session state

    Returns:
        List of Choice objects for settings menu
    """
    # Get current auto-approve status
    auto_approve_status = "ON" if session_state.auto_approve else "OFF"

    return [
        Choice(
            title=f"⚡  Auto-approve: {auto_approve_status}         Toggle tool auto-approval   (A)",
            value="toggle_auto_approve",
            shortcut_key="a",
        ),
        Choice(
            title="🎨  Theme: Green            Change color scheme          (T)",
            value="theme",
            shortcut_key="t",
            disabled=True,  # Future enhancement
        ),
        Choice(
            title="📝  Editor: nano            Set external editor          (E)",
            value="editor",
            shortcut_key="e",
            disabled=True,  # Future enhancement
        ),
        Choice(
            title="🔧  Advanced                Advanced settings            (V)",
            value="advanced",
            shortcut_key="v",
            disabled=True,  # Future enhancement
        ),
        Choice(
            title=f"{Icons.BACK}  Back to main menu                                     (B)",
            value="back",
            shortcut_key="b",
        ),
    ]
