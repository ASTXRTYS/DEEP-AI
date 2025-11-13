"""Safety wrappers around legacy synchronous prompts so they never hang."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, InvalidResponse, Prompt

from .ui_constants import Colors


def _read_int_env(var_name: str, default: int) -> int:
    """Read integer environment variables with sane fallbacks."""
    value = os.getenv(var_name)
    if value is None:
        return default

    try:
        parsed = int(value)
    except ValueError:
        return default

    return parsed if parsed > 0 else default


def _read_float_env(var_name: str, default: float) -> float:
    """Read float environment variables with sane fallbacks."""
    value = os.getenv(var_name)
    if value is None:
        return default

    try:
        parsed = float(value)
    except ValueError:
        return default

    return parsed if parsed > 0 else default


PROMPT_MAX_ATTEMPTS = _read_int_env("DEEPAGENTS_PROMPT_MAX_ATTEMPTS", default=3)
PROMPT_TIMEOUT_SECONDS = _read_float_env("DEEPAGENTS_PROMPT_TIMEOUT_SECONDS", default=30.0)


class PromptStatus(Enum):
    """Internal status for prompt attempts."""

    OK = "ok"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PromptOutcome:
    """Represents the outcome of a single prompt attempt."""

    status: PromptStatus
    value: str | None = None


@dataclass(frozen=True)
class PromptSafetyConfig:
    """Configuration for SafePrompt guards."""

    max_attempts: int = PROMPT_MAX_ATTEMPTS
    timeout_seconds: float = PROMPT_TIMEOUT_SECONDS


class SafePrompt:
    """Wrap prompt_toolkit prompts with retry limits and timeout protection."""

    def __init__(
        self,
        console: Console,
        config: PromptSafetyConfig | None = None,
    ) -> None:
        self.console = console
        self.config = config or PromptSafetyConfig()

    # ------------------------------------------------------------------
    # Public APIs used by RichPrompt
    # ------------------------------------------------------------------
    def ask_text(
        self,
        prompt_text: str,
        *,
        default: str | None = None,
        allow_blank: bool = False,
        password: bool = False,
        max_attempts: int | None = None,
        timeout_seconds: float | None = None,
    ) -> str | None:
        """Collect free-form text input with safety guards."""

        def parser(raw: str) -> str:
            if not allow_blank and not raw.strip():
                raise InvalidResponse("Input cannot be empty or whitespace-only")
            return raw

        return self._prompt_loop(
            prompt_text=prompt_text,
            parser=parser,
            default_text=default,
            password=password,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
        )

    def ask_confirm(
        self,
        prompt_text: str,
        *,
        default: bool = False,
        max_attempts: int | None = None,
        timeout_seconds: float | None = None,
    ) -> bool | None:
        """Confirmation prompt returning bool or None on cancel."""

        def parser(raw: str) -> bool:
            text = raw.strip().lower()
            if not text:
                return default
            if text in {"y", "yes"}:
                return True
            if text in {"n", "no"}:
                return False
            raise InvalidResponse("Please enter 'y' or 'n'")

        return self._prompt_loop(
            prompt_text=prompt_text,
            parser=parser,
            allow_blank=True,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
        )

    def ask_int(
        self,
        prompt_text: str,
        *,
        valid_choices: Sequence[str] | None = None,
        max_attempts: int | None = None,
        timeout_seconds: float | None = None,
    ) -> int | None:
        """Numeric prompt that optionally enforces allowed choices."""
        choice_set = set(valid_choices or [])

        def parser(raw: str) -> int:
            text = raw.strip()
            if not text:
                raise InvalidResponse("Please enter a number")
            try:
                value = int(text)
            except ValueError as exc:
                raise InvalidResponse("Please enter a valid number") from exc
            if choice_set and text not in choice_set:
                raise InvalidResponse("Please enter one of the listed choices")
            return value

        return self._prompt_loop(
            prompt_text=prompt_text,
            parser=parser,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
        )

    # ------------------------------------------------------------------
    # Backward-compatible API (used by legacy tests/extensions)
    # ------------------------------------------------------------------
    def ask(
        self,
        prompt_fn: Callable[..., Any],
        prompt_text: str,
        *,
        allow_whitespace_only: bool = False,
        max_attempts: int | None = None,
        timeout_seconds: float | None = None,
        **prompt_kwargs: Any,
    ) -> Any:
        """Maintain compatibility with the old SafePrompt signature."""
        prompt_owner = getattr(prompt_fn, "__self__", None)

        if prompt_owner is Prompt:
            return self.ask_text(
                prompt_text,
                default=prompt_kwargs.get("default"),
                allow_blank=allow_whitespace_only,
                password=prompt_kwargs.get("password", False),
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
            )

        if prompt_owner is Confirm:
            return self.ask_confirm(
                prompt_text,
                default=prompt_kwargs.get("default", False),
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
            )

        if prompt_owner is IntPrompt:
            return self.ask_int(
                prompt_text,
                valid_choices=prompt_kwargs.get("choices"),
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
            )

        raise ValueError("Unsupported prompt type for SafePrompt.ask()")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _prompt_loop(
        self,
        *,
        prompt_text: str,
        parser: Callable[[str], Any],
        default_text: str | None = None,
        password: bool = False,
        allow_blank: bool = False,
        max_attempts: int | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        attempts_allowed = max(1, max_attempts or self.config.max_attempts)
        timeout_limit = (
            timeout_seconds if timeout_seconds is not None else self.config.timeout_seconds
        )
        start_time = time.monotonic()

        for attempt in range(1, attempts_allowed + 1):
            elapsed = time.monotonic() - start_time
            if timeout_limit and elapsed >= timeout_limit:
                self.console.print(f"[red]Prompt timed out after {timeout_limit:g}s[/red]")
                return None

            remaining = None if not timeout_limit else max(timeout_limit - elapsed, 0.01)
            outcome = self._prompt_once(
                prompt_text if attempt == 1 else None,
                default_text=default_text,
                password=password,
                timeout=remaining,
            )

            if outcome.status is PromptStatus.TIMEOUT:
                self.console.print(f"[red]Prompt timed out after {timeout_limit:g}s[/red]")
                return None
            if outcome.status is PromptStatus.CANCELLED:
                return None

            raw = outcome.value or ""
            if not allow_blank and not raw.strip():
                remaining_attempts = attempts_allowed - attempt
                if remaining_attempts > 0:
                    self.console.print(
                        "[yellow]Input cannot be empty or whitespace-only[/yellow] "
                        f"[dim]({remaining_attempts} attempts left)[/dim]"
                    )
                    continue
                self.console.print("[red]Input cannot be empty or whitespace-only[/red]")
                self.console.print("[red]Maximum attempts exceeded[/red]")
                return None

            try:
                return parser(raw)
            except InvalidResponse as error:
                remaining_attempts = attempts_allowed - attempt
                if remaining_attempts > 0:
                    self.console.print(
                        f"[yellow]{error}[/yellow] [dim]({remaining_attempts} attempts left)[/dim]"
                    )
                else:
                    self.console.print(f"[red]{error}[/red]")
                    self.console.print("[red]Maximum attempts exceeded[/red]")
                continue

        return None

    def _prompt_once(
        self,
        prompt_text: str | None,
        *,
        default_text: str | None,
        password: bool,
        timeout: float | None,
    ) -> PromptOutcome:
        if prompt_text:
            self.console.print(prompt_text)

        if timeout is not None and timeout <= 0:
            return PromptOutcome(PromptStatus.TIMEOUT)

        try:
            value = self._run_prompt_with_timeout(
                default_text=default_text,
                password=password,
                timeout=timeout,
            )
            return PromptOutcome(PromptStatus.OK, value)

        except TimeoutError:
            return PromptOutcome(PromptStatus.TIMEOUT)

        except KeyboardInterrupt:
            self.console.print()
            self.console.print("[dim]✓ Cancelled.[/dim]")
            self.console.print()
            return PromptOutcome(PromptStatus.CANCELLED)

    def _run_prompt_with_timeout(
        self,
        *,
        default_text: str | None,
        password: bool,
        timeout: float | None,
    ) -> str:
        async def _prompt_async() -> str:
            session = PromptSession(
                message=HTML(f'<style fg="{Colors.PRIMARY_HEX}">▶</style> '),
            )
            with patch_stdout():
                return await session.prompt_async(
                    default=default_text or "",
                    is_password=password,
                )

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            coro = _prompt_async()
            if timeout is None:
                return loop.run_until_complete(coro)
            return loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
        finally:
            asyncio.set_event_loop(None)
            loop.close()


__all__ = [
    "PROMPT_MAX_ATTEMPTS",
    "PROMPT_TIMEOUT_SECONDS",
    "PromptSafetyConfig",
    "SafePrompt",
]
