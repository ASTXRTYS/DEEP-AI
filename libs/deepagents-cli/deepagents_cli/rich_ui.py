"""Rich-enhanced UI components for DeepAgents CLI.

This module provides beautiful terminal UI components using the Rich library,
including panels, tables, progress bars, and interactive prompts.
"""

import asyncio
import logging
import os
import subprocess
import sys
import threading
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import ValidationError, Validator
from rich.console import Console, Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .config import COLORS, DEEP_AGENTS_ASCII, SessionState, console
from .prompt_safety import SafePrompt
from .thread_display import relative_time
from .ui_constants import Colors

logger = logging.getLogger(__name__)


@dataclass
class SelectionState:
    """State manager for interactive selection menus."""

    choices: list[tuple[str, str]]
    default_value: str | None = None
    filter_text: str = ""
    filtered_indices: list[int] = field(default_factory=list)
    selected_row: int = 0
    require_explicit_choice: bool = False
    _initialized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.apply_filter(self.filter_text)

    def apply_filter(self, text: str) -> None:
        """Filter choices by substring (case-insensitive)."""
        self.filter_text = text
        if text:
            lowered = text.lower()
            self.filtered_indices = [
                idx for idx, (_, title) in enumerate(self.choices) if lowered in title.lower()
            ]
        else:
            self.filtered_indices = list(range(len(self.choices)))

        self._sync_selection()

    def append_filter_char(self, char: str) -> None:
        self.apply_filter(self.filter_text + char)

    def remove_filter_char(self) -> None:
        if self.filter_text:
            self.apply_filter(self.filter_text[:-1])

    def clear_filter(self) -> None:
        self.apply_filter("")

    def move(self, delta: int) -> None:
        if not self.filtered_indices:
            return
        self.selected_row = (self.selected_row + delta) % len(self.filtered_indices)

    def jump_to(self, index: int) -> None:
        if not self.filtered_indices:
            return
        clamped = max(0, min(index, len(self.filtered_indices) - 1))
        self.selected_row = clamped

    def current_value(self) -> str | None:
        if not self.filtered_indices or self.selected_row < 0:
            return None
        choice_idx = self.filtered_indices[self.selected_row]
        return self.choices[choice_idx][0]

    def render_choices(self) -> list[tuple[str, str]]:
        """Build formatted text for the choice list."""
        if not self.filtered_indices:
            return [("class:select-empty", "  No matches. Adjust filter.\n")]

        lines: list[tuple[str, str]] = []
        for display_idx, choice_idx in enumerate(self.filtered_indices, start=1):
            value, title = self.choices[choice_idx]
            is_selected = (display_idx - 1) == self.selected_row
            pointer_style = (
                "class:select-pointer-selected" if is_selected else "class:select-pointer"
            )
            label_style = "class:select-choice-selected" if is_selected else "class:select-choice"

            lines.append((pointer_style, "> " if is_selected else "  "))
            lines.append((label_style, title))
            if value == self.default_value:
                lines.append(("class:select-default", "  (default)"))
            lines.append(("", "\n"))

        return lines

    def render_filter_summary(self) -> list[tuple[str, str]]:
        text = self.filter_text or "(none)"
        suffix = (
            " • select option" if self.require_explicit_choice and self.selected_row < 0 else ""
        )
        return [("class:select-filter", f"Filter: {text}{suffix}")]

    def _sync_selection(self) -> None:
        if not self.filtered_indices:
            self.selected_row = -1 if self.require_explicit_choice else 0
            self._initialized = True
            return

        if not self._initialized:
            if self.require_explicit_choice:
                self.selected_row = -1
            elif self.default_value is not None:
                for i, idx in enumerate(self.filtered_indices):
                    if self.choices[idx][0] == self.default_value:
                        self.selected_row = i
                        break
                else:
                    self.selected_row = 0
            else:
                self.selected_row = 0
            self._initialized = True
            return

        if self.selected_row >= len(self.filtered_indices):
            self.selected_row = len(self.filtered_indices) - 1


class RichPrompt:
    """Enhanced prompt system using Rich.

    Provides beautiful, numbered menus with Rich panels for display
    and Rich's prompts for user input (IntPrompt, Confirm, Prompt).
    """

    def __init__(
        self,
        console: Console,
        session_state: SessionState | None = None,
        prompt_session: PromptSession | None = None,
    ):
        """Initialize the Rich prompt system.

        Args:
            console: Rich Console instance for output
            session_state: Optional session state for shortcuts
            prompt_session: Optional main PromptSession for unified lifecycle
        """
        self.console = console
        self.session_state = session_state
        self.prompt_session = prompt_session
        self.safe_prompt = SafePrompt(console)

    def _restore_terminal_state(self) -> None:
        """Restore a sane terminal state (echo + canonical mode).

        This guards against cases where an unexpected exception during an
        interactive prompt leaves the TTY in a corrupted state (no echo, raw mode).
        Implementation is best-effort and degrades gracefully on unsupported
        platforms.
        """
        try:
            # POSIX: ensure ECHO and ICANON are enabled; fallback to `stty sane`.
            if os.name == "posix" and sys.stdin.isatty():
                try:
                    import termios

                    fd = sys.stdin.fileno()
                    attrs = termios.tcgetattr(fd)
                    # lflags index = 3; set echo + canonical input processing
                    attrs[3] |= getattr(termios, "ECHO", 0) | getattr(termios, "ICANON", 0)
                    termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
                    return
                except Exception:
                    # Fallback: rely on stty sane when available
                    try:
                        subprocess.run(
                            ["stty", "sane"],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        return
                    except Exception:
                        pass

            # Windows: best-effort reset of console input mode (echo + line input)
            if os.name == "nt":
                try:
                    import ctypes  # type: ignore

                    kernel32 = ctypes.windll.kernel32
                    STD_INPUT_HANDLE = -10
                    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
                    mode = ctypes.c_uint()
                    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                        ENABLE_PROCESSED_INPUT = 0x0001
                        ENABLE_LINE_INPUT = 0x0002
                        ENABLE_ECHO_INPUT = 0x0004
                        new_mode = (
                            mode.value
                            | ENABLE_PROCESSED_INPUT
                            | ENABLE_LINE_INPUT
                            | ENABLE_ECHO_INPUT
                        )
                        kernel32.SetConsoleMode(handle, new_mode)
                except Exception:
                    # As a last resort on Windows, do nothing silently.
                    pass
        except Exception:
            # Never raise from cleanup; log at debug level only.
            logger.debug("Failed to restore terminal state", exc_info=True)

    def _supports_rich_ui(self) -> bool:
        """Detect if terminal supports Rich full-screen UI (VT/ANSI sequences).

        Checks for:
        - Terminal capabilities (is_terminal, is_dumb_terminal, legacy_windows)
        - CI environments (GITHUB_ACTIONS, CI, etc.)
        - Environment variable override (DEEPAGENTS_FALLBACK_UI)

        Returns:
            True if full Rich UI is supported, False if compact fallback selector should be used
        """
        # Environment variable override for testing/automation
        fallback_env = os.environ.get("DEEPAGENTS_FALLBACK_UI", "").lower()
        if fallback_env in ("1", "true", "yes"):
            return False  # Force fallback mode

        # CI environment detection - typically don't support interactive TUI
        ci_indicators = ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS"]
        if any(os.environ.get(var) for var in ci_indicators):
            # Exception: Allow if TTY_COMPATIBLE is explicitly set
            if os.environ.get("TTY_COMPATIBLE") != "1":
                return False

        # Rich Console capability checks
        if not self.console.is_terminal:
            return False  # Not a terminal (piped/redirected)

        if self.console.is_dumb_terminal:
            return False  # "dumb" terminal (TERM=dumb or unknown)

        # Check for Windows legacy console (no VT support)
        if hasattr(self.console, "legacy_windows") and self.console.legacy_windows:
            return False  # Old Windows cmd.exe without ANSI

        # All checks passed - terminal supports Rich UI
        return True

    def _bind_global_shortcuts(
        self,
        kb: KeyBindings,
        exit_action: Callable[[Any], None],
        on_activity: Callable[[], None] | None = None,
    ) -> None:
        """Attach Ctrl+T / Ctrl+M bindings that mirror the main prompt."""
        if not self.session_state:
            return

        def mark_activity() -> None:
            if on_activity:
                on_activity()

        @kb.add("c-t")
        def _(event):
            self.session_state.toggle_auto_approve()
            mark_activity()
            event.app.invalidate()

        @kb.add("c-m")
        def _(event):
            self.session_state.menu_requested = True
            mark_activity()
            exit_action(event)

    def menu(
        self,
        title: str,
        options: list[tuple[str, str]],
        subtitle: str | None = None,
        show_numbers: bool = True,
    ) -> str | None:
        """Display a beautiful numbered menu and get user selection.

        .. deprecated::
            This is a legacy method. Prefer select_async() for production use,
            which provides arrow-key navigation, unified Application lifecycle,
            and doesn't cause screen flicker.

        Args:
            title: Menu title
            options: List of (value, description) tuples
            subtitle: Optional subtitle
            show_numbers: Whether to show numbers (default: True)

        Returns:
            Selected value or None if cancelled
        """
        warnings.warn(
            "RichPrompt.menu() is deprecated. Use select_async() instead for "
            "arrow-key navigation and unified Application lifecycle.",
            DeprecationWarning,
            stacklevel=2,
        )

        from rich.console import Group
        from rich.text import Text

        # Create menu panel
        menu_content = self._create_menu_content(title, options, subtitle)
        panel = Panel(
            menu_content,
            border_style=COLORS["primary"],
            title=f"[bold]{title}[/bold]",
            subtitle=subtitle if subtitle else None,
            padding=(1, 2),
        )

        # Use screen context manager for flicker-free display
        # This prevents the momentary blank screen that console.clear() causes
        with self.console.screen() as screen:
            # Display menu in alternate buffer (no scrollback, no flicker)
            screen.update(Group(panel, Text("")))

            # Get user input with Rich's IntPrompt
            try:
                # Build valid choices (1-indexed for user display)
                option_values = [opt[0] for opt in options]
                valid_choices = list(range(1, len(options) + 1))

                # Prompt for selection (renders below the panel)
                choice = self.safe_prompt.ask_int(
                    "[bold yellow]Enter your choice[/bold yellow]",
                    valid_choices=[str(i) for i in valid_choices],
                )

                # Map back to value (convert from 1-indexed to 0-indexed)
                if choice is not None:
                    return option_values[choice - 1]
                return None

            except KeyboardInterrupt:
                return None

    def confirm(self, message: str, default: bool = False) -> bool | None:
        """Display a confirmation prompt.

        Args:
            message: Confirmation message
            default: Default response

        Returns:
            True if confirmed, False if explicitly denied, None if cancelled or aborted
        """
        try:
            result = self.safe_prompt.ask_confirm(
                f"[bold yellow]{message}[/bold yellow]",
                default=default,
            )
        except KeyboardInterrupt:
            return None
        return result

    def text_input(
        self,
        prompt: str,
        default: str = "",
        password: bool = False,
        allow_blank: bool = False,
    ) -> str | None:
        """Get text input from user.

        Args:
            prompt: Input prompt
            default: Default value
            password: Whether to suppress input display
            allow_blank: Whether to accept empty/whitespace-only responses

        Returns:
            User input or None if cancelled
        """
        try:
            return self.safe_prompt.ask_text(
                f"[bold yellow]{prompt}[/bold yellow]",
                default=default if default else None,
                password=password,
                allow_blank=allow_blank,
            )
        except KeyboardInterrupt:
            return None

    async def _run_modal_in_terminal(self, modal_coro_fn: Callable):
        """Run a modal dialog within the main PromptSession's terminal context.

        This pattern avoids nested Application anti-patterns by using the main
        PromptSession's Application to temporarily suspend input and run a modal
        dialog. The main Application's toolbar and keybindings remain active.

        Architecture:
            Main REPL Loop (cement_interactive.py)
              └─ PromptSession (single Application instance)
                  ├─ Persistent toolbar & key bindings
                  │
                  └─ Modal dialogs via run_in_terminal_async()
                      ├─ Selection menus (select_async)
                      ├─ Text input (text_input_async)
                      └─ Confirmations (confirm_async)

        Why this matters:
            Without this pattern, each modal dialog would create a new Application
            instance, causing:
            - Toolbar flickering and disappearing
            - Keyboard shortcuts (Ctrl+T, Ctrl+M) failing intermittently
            - Screen corruption during terminal resize
            - Nested event loop conflicts

        How it works:
            1. Temporarily suspends main PromptSession UI
            2. Restores normal terminal input/output
            3. Executes modal dialog Application
            4. Restores PromptSession UI when modal closes
            5. Single Application lifecycle maintained throughout

        See GitHub Issue #55 for context on why this pattern is necessary.

        Args:
            modal_coro_fn: Callable that returns a coroutine for the modal dialog

        Returns:
            Result from the modal dialog
        """
        result_container: dict[str, Any] = {}

        def run_modal_in_new_loop(
            restore_loop: asyncio.AbstractEventLoop | None,
        ) -> BaseException | None:
            """Run the modal coroutine on a fresh event loop."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(run_modal())
            except asyncio.CancelledError as exc:  # pragma: no cover - cancellation edge
                logger.debug("Modal cancelled during execution")
                return exc
            except BaseException as exc:  # pragma: no cover - propagated below
                return exc
            finally:
                loop.close()
                if restore_loop is not None:
                    asyncio.set_event_loop(restore_loop)
            return None

        def run_modal_on_existing_loop(loop: asyncio.AbstractEventLoop) -> BaseException | None:
            """Schedule the modal coroutine on an already running loop."""
            future = asyncio.run_coroutine_threadsafe(run_modal(), loop)
            try:
                future.result()
            except asyncio.CancelledError as exc:  # pragma: no cover - cancellation edge
                logger.debug("Modal cancelled during execution")
                return exc
            except BaseException as exc:  # pragma: no cover - propagated below
                return exc
            return None

        def run_modal_in_worker_thread() -> None:
            """Execute the modal in a dedicated worker thread when required."""
            exception_holder: list[BaseException] = []

            def thread_runner() -> None:
                exc = run_modal_in_new_loop(None)
                if exc:
                    exception_holder.append(exc)

            thread = threading.Thread(
                target=thread_runner, name="DeepAgentsModalRunner", daemon=True
            )
            thread.start()
            thread.join()

            if exception_holder:
                raise exception_holder[0]

        async def run_modal():
            """Execute the modal coroutine and store result."""
            result_container["value"] = await modal_coro_fn()

        def sync_wrapper():
            """Synchronous wrapper for run_in_terminal."""
            old_loop: asyncio.AbstractEventLoop | None = None
            loop_running = False
            loop_thread_id: int | None = None
            try:
                old_loop = asyncio.get_event_loop()
                loop_running = old_loop.is_running()
                loop_thread_id = getattr(old_loop, "_thread_id", None)
            except RuntimeError:
                # No loop on this thread - that's fine
                pass

            current_thread_id = threading.get_ident()

            if loop_running and old_loop is not None:
                if loop_thread_id is not None and loop_thread_id != current_thread_id:
                    exc = run_modal_on_existing_loop(old_loop)
                    if exc:
                        raise exc
                    return

                # Same thread (or unknown owner). Use a worker thread to avoid re-entrancy.
                run_modal_in_worker_thread()
                return

            exc = run_modal_in_new_loop(old_loop)
            if exc:
                raise exc

        # Use the main PromptSession's Application to run modal in terminal
        app = self.prompt_session.app
        run_async = getattr(app, "run_in_terminal_async", None)
        if callable(run_async):
            await run_async(sync_wrapper)
        else:
            # Compatibility: older prompt_toolkit exposes only synchronous APIs
            run_sync = getattr(app, "run_in_terminal", None)
            if callable(run_sync):
                run_sync(sync_wrapper)
            else:
                # Final fallback: use module-level run_in_terminal if available
                try:
                    from prompt_toolkit.application import run_in_terminal as module_run_in_terminal
                except Exception:
                    module_run_in_terminal = None
                if callable(module_run_in_terminal):
                    module_run_in_terminal(sync_wrapper)
                else:
                    # As a last resort, execute synchronously
                    sync_wrapper()

        return result_container.get("value")

    async def select_async(
        self,
        question: str,
        choices: list[tuple[str, str]],
        default: str | None = None,
        context_panel: RenderableType | None = None,
        require_explicit_choice: bool = False,
    ) -> str | None:
        """Display a selection menu asynchronously (for HITL approval workflows).

        **Async Implementation Note:**
        The `_async` suffix indicates this method is built on prompt_toolkit's native
        async implementation (Application.run_async()). This is NOT wrapped blocking I/O,
        but true async/await patterns that cooperate with Python's event loop.

        Use this method in async contexts (menu systems, HITL workflows) where you need
        non-blocking user interaction that can be cancelled or interrupted gracefully.

        Args:
            question: Question text displayed above choices
            choices: List of (value, description) tuples for selection
            default: Default value to pre-select (optional)
            context_panel: Optional Rich renderable shown above the menu
            require_explicit_choice: If True, user must highlight a choice before Enter

        Returns:
            Selected value string, or None if cancelled (Escape/Ctrl+C)
        """
        if not choices:
            self.console.print("[red]No options available for selection.[/red]")
            self.console.print()
            return None

        supports_rich_ui = self._supports_rich_ui()
        fallback_mode = not supports_rich_ui

        if fallback_mode:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                self.console.print()
                self.console.print(
                    "[yellow]Interactive selection requires a TTY. "
                    "Use slash commands instead (e.g., /threads).[/yellow]"
                )
                self.console.print()
                return None
            logger.info("Using compact fallback selector (arrow-only, no numeric prompts)")

        # Terminal supports rich UI - display context if provided
        if context_panel:
            self.console.print(context_panel)
            self.console.print()

        enable_search = len(choices) > 10
        state = SelectionState(
            choices=choices,
            default_value=default,
            require_explicit_choice=require_explicit_choice,
        )

        # Use run_in_terminal if main prompt session is available
        if self.prompt_session:
            return await self._run_modal_in_terminal(
                lambda: self._run_selection_dialog(
                    question, state, enable_search, fallback_mode=fallback_mode
                )
            )
        # Fallback to direct execution (creates nested Application)
        logger.warning(
            "prompt_session is None - falling back to nested Application. "
            "This may cause toolbar/keyboard issues. "
            "Ensure RichPrompt is initialized with the main PromptSession."
        )
        return await self._run_selection_dialog(
            question, state, enable_search, fallback_mode=fallback_mode
        )

    async def _run_selection_dialog(
        self,
        question: str,
        state: SelectionState,
        enable_search: bool,
        *,
        fallback_mode: bool = False,
    ) -> str | None:
        """Render the interactive selection UI and return the chosen value."""
        question_control = FormattedTextControl(lambda: [("class:select-question", question)])
        choice_control = FormattedTextControl(state.render_choices)
        escape_pending = False

        def reset_escape_pending() -> None:
            nonlocal escape_pending
            if escape_pending:
                escape_pending = False

        def instruction_fragments() -> list[str]:
            if enable_search:
                fragments = [
                    "↑/↓ move",
                    "Type to filter",
                    "Backspace edits",
                    "Enter select",
                    "Esc clears/cancel",
                ]
            else:
                fragments = ["↑/↓ move", "Enter select", "Esc cancel"]

            if escape_pending:
                fragments.append("Esc again to confirm")

            if self.session_state:
                fragments.append("Ctrl+M menu")
                fragments.append("Ctrl+T toggle")

            if state.require_explicit_choice and state.current_value() is None:
                fragments.append("Highlight choice before Enter")

            return fragments

        def instructions_renderable() -> list[tuple[str, str]]:
            text = " • ".join(instruction_fragments())
            return [("class:select-instructions", text)]

        instructions_control = FormattedTextControl(instructions_renderable)

        body_children = [
            Window(content=question_control, dont_extend_height=True, height=1),
            Window(height=1, char="─", style="class:select-divider"),
            Window(content=choice_control, always_hide_cursor=True),
        ]

        if enable_search:
            filter_control = FormattedTextControl(state.render_filter_summary)
            body_children.append(Window(content=filter_control, dont_extend_height=True, height=1))

        body_children.append(
            Window(content=instructions_control, dont_extend_height=True, height=1)
        )

        layout = Layout(container=HSplit(body_children, padding=1))

        style = Style.from_dict(
            {
                "select-question": f"bold {Colors.QUESTION_HEX}",
                "select-divider": Colors.DIVIDER_HEX,
                "select-choice": Colors.TEXT_WHITE,
                "select-choice-selected": f"bold {Colors.TEXT_WHITE} bg:{Colors.PRIMARY_HEX}",
                "select-pointer": Colors.NUMBER_HEX,
                "select-pointer-selected": f"bold {Colors.NUMBER_SELECTED_HEX} bg:{Colors.PRIMARY_HEX}",
                "select-default": f"{Colors.NUMBER_HEX} italic",
                "select-instructions": f"italic {Colors.NUMBER_HEX}",
                "select-filter": Colors.NUMBER_HEX,
                "select-empty": f"italic {Colors.NUMBER_HEX}",
            }
        )

        kb = KeyBindings()

        self._bind_global_shortcuts(
            kb,
            exit_action=lambda event: event.app.exit(result=None),
            on_activity=reset_escape_pending,
        )

        @kb.add("up")
        def _(event):
            reset_escape_pending()
            state.move(-1)
            event.app.invalidate()

        @kb.add("down")
        def _(event):
            reset_escape_pending()
            state.move(1)
            event.app.invalidate()

        @kb.add("pageup")
        def _(event):
            reset_escape_pending()
            state.move(-5)
            event.app.invalidate()

        @kb.add("pagedown")
        def _(event):
            reset_escape_pending()
            state.move(5)
            event.app.invalidate()

        @kb.add("home")
        def _(event):
            reset_escape_pending()
            state.jump_to(0)
            event.app.invalidate()

        @kb.add("end")
        def _(event):
            reset_escape_pending()
            state.jump_to(len(state.filtered_indices) - 1)
            event.app.invalidate()

        @kb.add("enter")
        def _(event):
            reset_escape_pending()
            value = state.current_value()
            if value is not None:
                event.app.exit(result=value)

        @kb.add("escape")
        def _(event):
            nonlocal escape_pending
            if enable_search and state.filter_text:
                state.clear_filter()
                reset_escape_pending()
                event.app.invalidate()
                return

            if not escape_pending:
                escape_pending = True
                event.app.invalidate()
                return

            event.app.exit(result=None)

        @kb.add("c-c")
        def _(event):
            event.app.exit(result=None)

        if enable_search:

            @kb.add("backspace")
            def _(event):
                reset_escape_pending()
                if state.filter_text:
                    state.remove_filter_char()
                    event.app.invalidate()

            @kb.add(Keys.Any)
            def _(event):
                reset_escape_pending()
                data = event.data or ""
                if len(data) == 1 and data.isprintable() and data not in {"\n", "\r"}:
                    state.append_filter_char(data)
                    event.app.invalidate()

        app = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            mouse_support=False,
            full_screen=False,
        )

        try:
            with patch_stdout():
                return await app.run_async()
        except (KeyboardInterrupt, EOFError):
            return None
        finally:
            self._restore_terminal_state()

    async def text_input_async(
        self,
        prompt_text: str,
        default: str = "",
        multiline: bool = False,
        validate: Callable[[str], bool | str] | None = None,
    ) -> str | None:
        """Get text input from user asynchronously.

        **Async Implementation Note:**
        The `_async` suffix indicates this method is built on prompt_toolkit's native
        async implementation (PromptSession.prompt_async()). This is NOT wrapped
        blocking I/O, but true async/await patterns that cooperate with Python's
        event loop.

        Use this method in async contexts (menu systems, HITL workflows) where you need
        non-blocking text input that can be cancelled or interrupted gracefully.

        Args:
            prompt_text: Input prompt displayed to user
            default: Default value pre-filled in the input field
            multiline: Whether to enable multiline mode (Alt+Enter to submit)
            validate: Optional validation function (returns True or error message string)

        Returns:
            User input string, or None if cancelled (Escape/Ctrl+C)
        """

        async def _text_input_dialog():
            """Inner function that creates and runs the text input dialog."""
            # Display prompt
            self.console.print()
            self.console.print(f"[bold yellow]{prompt_text}[/bold yellow]")
            self.console.print()

            # Create validator once if validation function provided
            validator = None
            if validate:

                class ContentValidator(Validator):
                    def validate(self, document):
                        result = validate(document.text)
                        if result is not True:
                            raise ValidationError(
                                message=str(result), cursor_position=len(document.text)
                            )

                validator = ContentValidator()

            if multiline:
                self.console.print(
                    "[dim]Type feedback • Alt+Enter or Esc+Enter finish • Ctrl+C cancel[/dim]"
                )
                self.console.print()

                # For multiline, use prompt_toolkit to get proper multiline input
                kb = KeyBindings()

                @kb.add("escape", "enter")
                def _(event):
                    """Alt+Enter or Esc then Enter submits the input."""
                    event.current_buffer.validate_and_handle()

                self._bind_global_shortcuts(
                    kb,
                    exit_action=lambda event: event.app.exit(result=None),
                )

                session = PromptSession(
                    message=HTML(f'<style fg="{Colors.PRIMARY_HEX}">✎</style> '),
                    multiline=True,
                    key_bindings=kb,
                    validator=validator,
                    reserve_space_for_menu=0,
                )

                try:
                    with patch_stdout():
                        return await session.prompt_async(default=default)

                except (KeyboardInterrupt, EOFError):
                    return None
                finally:
                    self._restore_terminal_state()

            else:
                # Single-line input using prompt_toolkit for consistency
                kb = KeyBindings()
                self._bind_global_shortcuts(
                    kb,
                    exit_action=lambda event: event.app.exit(result=None),
                )

                session = PromptSession(
                    message=HTML(f'<style fg="{Colors.PRIMARY_HEX}">▶</style> '),
                    validator=validator,
                    key_bindings=kb,
                    reserve_space_for_menu=0,
                )

                try:
                    with patch_stdout():
                        return await session.prompt_async(default=default)

                except (KeyboardInterrupt, EOFError):
                    return None
                finally:
                    self._restore_terminal_state()

        # Use run_in_terminal if main prompt session is available
        if self.prompt_session:
            return await self._run_modal_in_terminal(_text_input_dialog)
        # Fallback to direct execution (creates nested Application)
        logger.warning(
            "prompt_session is None - falling back to nested Application for text input. "
            "This may cause toolbar/keyboard issues."
        )
        return await _text_input_dialog()

    async def confirm_async(
        self,
        message: str,
        default: bool = False,
        warning_panel: Panel | None = None,
    ) -> bool:
        """Async confirmation prompt.

        **Async Implementation Note:**
        The `_async` suffix indicates this method is built on prompt_toolkit's native
        async implementation (PromptSession.prompt_async()). This is NOT wrapped
        blocking I/O, but true async/await patterns that cooperate with Python's
        event loop.

        Use this method in async contexts (menu systems, HITL workflows) where you need
        non-blocking yes/no confirmation that can be cancelled or interrupted gracefully.

        Args:
            message: Confirmation question to display
            default: Default response (True=Yes, False=No)
            warning_panel: Optional Rich Panel displayed before the question (for dangerous actions)

        Returns:
            True if user confirmed (y/yes), False if declined or cancelled
        """

        async def _confirm_dialog():
            """Inner function that creates and runs the confirmation dialog."""
            # Display warning panel if provided
            if warning_panel:
                self.console.print()
                self.console.print(warning_panel)
                self.console.print()

            # Display the question
            default_str = " (Y/n)" if default else " (y/N)"
            self.console.print(f"[bold yellow]{message}{default_str}[/bold yellow]")
            self.console.print()

            kb = KeyBindings()
            self._bind_global_shortcuts(
                kb,
                exit_action=lambda event: event.app.exit(result=None),
            )

            session = PromptSession(
                message=HTML(f'<style fg="{Colors.PRIMARY_HEX}">▶</style> '),
                key_bindings=kb,
                reserve_space_for_menu=0,
            )

            try:
                with patch_stdout():
                    response = await session.prompt_async()

                if response is None:
                    return default

                # Parse response
                response = response.strip().lower()
                if not response:
                    return default
                return response in ("y", "yes")

            except (KeyboardInterrupt, EOFError):
                self.console.print()
                self.console.print("[dim]✓ Cancelled.[/dim]")
                self.console.print()
                return False
            finally:
                self._restore_terminal_state()

        # Use run_in_terminal if main prompt session is available
        if self.prompt_session:
            return await self._run_modal_in_terminal(_confirm_dialog)
        # Fallback to direct execution (creates nested Application)
        logger.warning(
            "prompt_session is None - falling back to nested Application for confirmation. "
            "This may cause toolbar/keyboard issues."
        )
        return await _confirm_dialog()

    async def dangerous_confirmation_async(
        self,
        action: str,
        target: str,
        details: dict[str, Any],
        confirmation_text: str = "DELETE",
    ) -> bool:
        """Dangerous action confirmation requiring typed confirmation.

        **Async Implementation Note:**
        The `_async` suffix indicates this method is built on prompt_toolkit's native
        async implementation (via text_input_async()). This is NOT wrapped blocking I/O,
        but true async/await patterns that cooperate with Python's event loop.

        Use this method in async contexts (menu systems, HITL workflows) where you need
        non-blocking dangerous action confirmation that can be cancelled or interrupted
        gracefully.

        Displays red warning panel with action details and requires user to type exact
        confirmation text (case-sensitive) to proceed.

        Args:
            action: Action name displayed in warning (e.g., "Delete Thread")
            target: Target name/ID being acted upon
            details: Dict of details to display (e.g., {"message_count": 42, "tokens": 1500})
            confirmation_text: Exact text user must type to confirm (default: "DELETE")

        Returns:
            True if user typed confirmation text exactly (case-sensitive), False otherwise
        """
        # Build warning panel
        safe_target = escape(target)
        detail_lines = [f"[bold]Target:[/bold] {safe_target}\n"]

        for key, value in details.items():
            detail_lines.append(f"[bold]{key}:[/bold] {value}")

        detail_lines.append(
            f"\n[yellow]WARNING: This action cannot be undone.[/yellow]\n"
            f"[yellow]Type '{confirmation_text}' to confirm.[/yellow]"
        )

        panel = Panel(
            "\n".join(detail_lines),
            title=f"[bold {Colors.ERROR}]WARNING: {action}[/bold {Colors.ERROR}]",
            border_style=Colors.ERROR,
            padding=(1, 2),
        )

        self.console.print()
        self.console.print(panel)
        self.console.print()

        # Create validator for exact match
        def validate_confirmation(text: str) -> bool | str:
            """Validate that user typed exact confirmation text."""
            if not text or text.isspace():
                return "Confirmation cannot be empty or whitespace-only"
            if text != confirmation_text:
                return f"Must type {confirmation_text} exactly (case-sensitive)"
            return True

        try:
            # Use text_input_async with validation
            result = await self.text_input_async(
                prompt_text=f'Type "{confirmation_text}" to confirm:',
                default="",
                multiline=False,
                validate=validate_confirmation,
            )

            if result == confirmation_text:
                self.console.print()
                self.console.print(f"[red]Confirmed: {action}[/red]")
                self.console.print()
                return True
            self.console.print()
            self.console.print("[dim]✓ Cancelled.[/dim]")
            self.console.print()
            return False

        except (KeyboardInterrupt, EOFError):
            self.console.print()
            self.console.print("[dim]✓ Cancelled.[/dim]")
            self.console.print()
            return False
        finally:
            # Idempotent; inner prompts also perform restoration.
            self._restore_terminal_state()

    def _create_menu_content(
        self, title: str, options: list[tuple[str, str]], subtitle: str | None
    ) -> Group:
        """Create beautiful menu content with Rich formatting.

        Args:
            title: Menu title
            options: List of (value, description) tuples
            subtitle: Optional subtitle

        Returns:
            Rich Group with formatted menu items
        """
        items = []

        # Add subtitle if provided
        if subtitle:
            items.append(Text(subtitle, style="dim"))
            items.append(Text(""))

        # Add numbered options
        for i, (_value, description) in enumerate(options, 1):
            text = Text()
            text.append(f"{i:2}. ", style=f"bold {COLORS['primary']}")
            text.append(description, style="bold white")
            items.append(text)

        # Add hint
        items.append(Text(""))
        items.append(
            Text(
                "Type number • Enter select • Ctrl+C cancel",
                style=f"dim {COLORS['dim']}",
            )
        )

        return Group(*items)


class ProgressDisplay:
    """Rich progress display for long-running operations."""

    def __init__(self, console: Console):
        """Initialize progress display.

        Args:
            console: Rich Console instance
        """
        self.console = console
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,  # Clean up completed progress bars
        )

    def __enter__(self):
        """Enter context manager."""
        self.progress.start()
        return self.progress

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        self.progress.stop()


def create_status_table(title: str, items: list[tuple[str, str, str | None]]) -> Table:
    """Create a beautiful status table.

    Args:
        title: Table title
        items: List of (label, value, style) tuples

    Returns:
        Formatted Rich Table
    """
    table = Table(
        title=title,
        show_header=False,
        border_style=COLORS["primary"],
        padding=(0, 1),
    )

    table.add_column("Label", style="dim", width=20)
    table.add_column("Value", style="bold")

    for label, value, style in items:
        val_style = style if style else Colors.TEXT_WHITE
        table.add_row(label, value, style=val_style)

    return table


def create_thread_table(threads: list[dict], current_id: str) -> Table:
    """Create a summary table for threads with usage metrics."""
    table = Table(
        title="Thread Overview",
        border_style=COLORS["primary"],
        header_style=f"bold {COLORS['primary']}",
        show_lines=True,
    )

    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("ID", style=COLORS["primary"], width=12)
    table.add_column("Name", style="bold white")
    table.add_column("Messages", justify="right", style=Colors.WARNING)
    table.add_column("Tokens", justify="right", style=Colors.PRIMARY)
    table.add_column("Last Used", style="dim", width=12)
    table.add_column("Status", justify="center", width=12)

    for i, thread in enumerate(threads, 1):
        thread_id = thread["id"]
        thread_id_short = thread_id[:8] if len(thread_id) > 8 else thread_id
        name = escape(thread.get("display_name") or thread.get("name", "Untitled"))
        message_count = thread.get("message_count", 0) or 0
        tokens = thread.get("langsmith_tokens")
        if tokens is None:
            tokens = thread.get("total_tokens") or thread.get("token_count") or 0
        tokens_str = f"{tokens / 1000:.1f}K" if tokens >= 1000 else str(tokens)
        last_used = relative_time(thread.get("last_used", ""))

        status_style = Colors.SUCCESS if thread_id == current_id else "dim"
        status_text = "ACTIVE" if thread_id == current_id else "AVAILABLE"

        table.add_row(
            str(i),
            thread_id_short,
            name,
            str(message_count),
            tokens_str,
            last_used,
            f"[{status_style}]{status_text}[/{status_style}]",
        )

    return table


def create_syntax_panel(code: str, language: str, title: str = "Code") -> Panel:
    """Create a beautiful syntax-highlighted code panel.

    Args:
        code: Code to display
        language: Programming language
        title: Panel title

    Returns:
        Formatted Panel with syntax highlighting
    """
    syntax = Syntax(code, language, theme="monokai", line_numbers=True)
    return Panel(
        syntax,
        title=f"[bold]{title}[/bold]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )


def create_tree_view(title: str, data: dict) -> Tree:
    """Create a beautiful tree view of nested data.

    Args:
        title: Tree title
        data: Nested dictionary to display

    Returns:
        Rich Tree
    """
    tree = Tree(f"[bold cyan]{title}[/bold cyan]")

    def add_items(parent, items):
        if isinstance(items, dict):
            for key, value in items.items():
                if isinstance(value, dict):
                    branch = parent.add(f"[yellow]{key}[/yellow]")
                    add_items(branch, value)
                else:
                    parent.add(f"[yellow]{key}[/yellow]: [green]{value}[/green]")
        elif isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    add_items(parent, item)
                else:
                    parent.add(f"[green]{item}[/green]")

    add_items(tree, data)
    return tree


# Display functions for main CLI


def display_ascii_banner() -> None:
    """Display the DeepAgents ASCII banner."""
    console.clear()
    console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
    console.print()


def display_connection_status(connected: bool) -> None:
    """Display server connection status.

    Args:
        connected: Whether server is connected
    """
    if connected:
        console.print("[green]● Connected to LangGraph server[/green]")
    else:
        console.print("[red]● Not connected to LangGraph server[/red]")
    console.print()


def display_tavily_warning() -> None:
    """Display Tavily API warning."""
    console.print(
        "[yellow]⚠ Web search disabled:[/yellow] TAVILY_API_KEY not found.",
        style=COLORS["dim"],
    )
    console.print("  To enable web search, set your Tavily API key:", style=COLORS["dim"])
    console.print("    export TAVILY_API_KEY=your_api_key_here", style=COLORS["dim"])
    console.print(
        "  Or add it to your .env file. Get your key at: https://tavily.com",
        style=COLORS["dim"],
    )
    console.print()


def display_welcome(auto_approve: bool = False) -> None:
    """Display welcome message.

    Args:
        auto_approve: Whether auto-approve is enabled
    """
    from pathlib import Path

    console.print("... Ready to code! What would you like to build?", style=COLORS["agent"])
    console.print(f"  [dim]Working directory: {Path.cwd()}[/dim]")
    console.print()

    if auto_approve:
        console.print(
            "  [yellow]⚡ Auto-approve: ON[/yellow] [dim](tools run without confirmation)[/dim]"
        )
        console.print()

    console.print(
        "  Tips: Ctrl+M for menu • /help for commands • !cmd for bash • Ctrl+C to exit",
        style=f"dim {COLORS['dim']}",
    )
    console.print()


def display_server_error(error_message: str | None = None) -> None:
    """Display server connection error.

    Args:
        error_message: Optional error details
    """
    console.print("[red]✗ Failed to start server automatically[/red]")
    console.print()

    if error_message:
        panel = Panel(
            error_message,
            title=f"[bold {Colors.ERROR}]Error Details[/bold {Colors.ERROR}]",
            border_style=Colors.ERROR,
        )
        console.print(panel)
        console.print()

    console.print("Please start the server manually in another terminal:")
    console.print("  [cyan]langgraph dev[/cyan]")
    console.print()
    console.print("Then restart the CLI.")
