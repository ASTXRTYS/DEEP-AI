"""Tests for RichPrompt async methods."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from rich.panel import Panel

from deepagents_cli.rich_ui import RichPrompt


@pytest.fixture
def console():
    """Create a mock console."""
    return MagicMock(spec=Console)


@pytest.fixture
def rich_prompt(console):
    """Create a RichPrompt instance with mock console."""
    return RichPrompt(console)


class TestSelectAsync:
    """Test select_async method."""

    @pytest.mark.asyncio
    async def test_basic_selection(self, rich_prompt, console):
        """Test basic selection with numbered choices."""
        choices = [
            ("value1", "Choice 1"),
            ("value2", "Choice 2"),
            ("value3", "Choice 3"),
        ]

        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            mock_session.prompt.return_value = "1"

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value="1")

                result = await rich_prompt.select_async(
                    question="Select an option:",
                    choices=choices,
                )

                assert result == "value1"

    @pytest.mark.asyncio
    async def test_selection_cancelled(self, rich_prompt, console):
        """Test selection cancelled with Ctrl+C."""
        choices = [("value1", "Choice 1")]

        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(side_effect=KeyboardInterrupt())

                result = await rich_prompt.select_async(
                    question="Select:",
                    choices=choices,
                )

                assert result is None

    @pytest.mark.asyncio
    async def test_selection_with_context_panel(self, rich_prompt, console):
        """Test selection with context panel displayed."""
        choices = [("yes", "Yes"), ("no", "No")]
        panel = Panel("Context information", border_style="yellow")

        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value="1")

                result = await rich_prompt.select_async(
                    question="Select:",
                    choices=choices,
                    context_panel=panel,
                )

                # Verify context panel was printed
                console.print.assert_any_call(panel)
                assert result == "yes"


class TestTextInputAsync:
    """Test text_input_async method."""

    @pytest.mark.asyncio
    async def test_basic_input(self, rich_prompt, console):
        """Test basic text input."""
        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value="test input")

                result = await rich_prompt.text_input_async(
                    prompt_text="Enter text:",
                )

                assert result == "test input"

    @pytest.mark.asyncio
    async def test_multiline_input(self, rich_prompt, console):
        """Test multiline text input."""
        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(
                    return_value="line1\nline2\nline3"
                )

                result = await rich_prompt.text_input_async(
                    prompt_text="Enter feedback:",
                    multiline=True,
                )

                assert "line1" in result
                assert "line2" in result

    @pytest.mark.asyncio
    async def test_input_cancelled(self, rich_prompt, console):
        """Test text input cancelled with Ctrl+C."""
        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(side_effect=KeyboardInterrupt())

                result = await rich_prompt.text_input_async(
                    prompt_text="Enter text:",
                )

                assert result is None


class TestConfirmAsync:
    """Test confirm_async method."""

    @pytest.mark.asyncio
    async def test_confirm_yes(self, rich_prompt, console):
        """Test confirmation with 'yes' response."""
        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value="y")

                result = await rich_prompt.confirm_async(
                    message="Are you sure?",
                )

                assert result is True

    @pytest.mark.asyncio
    async def test_confirm_no(self, rich_prompt, console):
        """Test confirmation with 'no' response."""
        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value="n")

                result = await rich_prompt.confirm_async(
                    message="Are you sure?",
                )

                assert result is False

    @pytest.mark.asyncio
    async def test_confirm_default_true(self, rich_prompt, console):
        """Test confirmation with empty response and default=True."""
        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value="")

                result = await rich_prompt.confirm_async(
                    message="Continue?",
                    default=True,
                )

                assert result is True

    @pytest.mark.asyncio
    async def test_confirm_with_warning_panel(self, rich_prompt, console):
        """Test confirmation with warning panel."""
        warning = Panel("Warning: This is dangerous!", border_style="red")

        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value="y")

                result = await rich_prompt.confirm_async(
                    message="Proceed?",
                    warning_panel=warning,
                )

                # Verify warning panel was printed
                console.print.assert_any_call(warning)
                assert result is True

    @pytest.mark.asyncio
    async def test_confirm_cancelled(self, rich_prompt, console):
        """Test confirmation cancelled with Ctrl+C."""
        with patch("deepagents_cli.rich_ui.PromptSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(side_effect=KeyboardInterrupt())

                result = await rich_prompt.confirm_async(
                    message="Continue?",
                )

                assert result is False


class TestDangerousConfirmationAsync:
    """Test dangerous_confirmation_async method."""

    @pytest.mark.asyncio
    async def test_correct_confirmation(self, rich_prompt, console):
        """Test dangerous confirmation with correct text."""
        # Mock text_input_async to return correct confirmation
        with patch.object(rich_prompt, "text_input_async", new=AsyncMock(return_value="DELETE")):
            result = await rich_prompt.dangerous_confirmation_async(
                action="Delete Thread",
                target="my-thread",
                details={"Messages": "42", "Tokens": "1000"},
                confirmation_text="DELETE",
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_incorrect_confirmation(self, rich_prompt, console):
        """Test dangerous confirmation with incorrect text."""
        # Mock text_input_async to return incorrect confirmation
        with patch.object(rich_prompt, "text_input_async", new=AsyncMock(return_value="delete")):
            result = await rich_prompt.dangerous_confirmation_async(
                action="Delete Thread",
                target="my-thread",
                details={"Messages": "42"},
                confirmation_text="DELETE",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_empty_confirmation(self, rich_prompt, console):
        """Test dangerous confirmation with empty input."""
        # Mock text_input_async to return empty string
        with patch.object(rich_prompt, "text_input_async", new=AsyncMock(return_value="")):
            result = await rich_prompt.dangerous_confirmation_async(
                action="Delete Thread",
                target="my-thread",
                details={"Messages": "42"},
                confirmation_text="DELETE",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_confirmation_cancelled(self, rich_prompt, console):
        """Test dangerous confirmation cancelled."""
        # Mock text_input_async to return None (cancelled)
        with patch.object(rich_prompt, "text_input_async", new=AsyncMock(return_value=None)):
            result = await rich_prompt.dangerous_confirmation_async(
                action="Delete Thread",
                target="my-thread",
                details={"Messages": "42"},
                confirmation_text="DELETE",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_custom_confirmation_text(self, rich_prompt, console):
        """Test dangerous confirmation with custom confirmation text."""
        # Mock text_input_async to return correct custom confirmation
        with patch.object(rich_prompt, "text_input_async", new=AsyncMock(return_value="DESTROY")):
            result = await rich_prompt.dangerous_confirmation_async(
                action="Destroy Database",
                target="production-db",
                details={"Records": "1000000"},
                confirmation_text="DESTROY",
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_details_displayed(self, rich_prompt, console):
        """Test that details are displayed in warning panel."""
        with patch.object(rich_prompt, "text_input_async", new=AsyncMock(return_value="DELETE")):
            await rich_prompt.dangerous_confirmation_async(
                action="Delete Thread",
                target="my-thread",
                details={
                    "Messages": "42",
                    "Tokens": "1000",
                    "Created": "2025-01-01",
                },
                confirmation_text="DELETE",
            )

            # Verify that a panel was printed (details should be in the panel)
            assert console.print.called
            # Check that some print call included a Panel
            panel_printed = any(
                isinstance(call[0][0], Panel) if call[0] else False
                for call in console.print.call_args_list
            )
            assert panel_printed
