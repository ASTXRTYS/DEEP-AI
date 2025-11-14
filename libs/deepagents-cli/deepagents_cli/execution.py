"""Task execution and streaming logic for the CLI."""

import asyncio
import json
import logging
import sys
import termios
import tty
from datetime import UTC, datetime
from typing import Any, TYPE_CHECKING

from langchain.agents.middleware.human_in_the_loop import (
    ActionRequest,
    ApproveDecision,
    Decision,
    HITLResponse,
    RejectDecision,
)
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command, Interrupt
from pydantic import TypeAdapter, ValidationError
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from typing_extensions import NotRequired, TypedDict

from deepagents.middleware.handoff_summarization import HANDOFF_ACTION_NAME
from deepagents_cli.config import COLORS, console
from deepagents_cli.file_ops import FileOpTracker, build_approval_preview
from deepagents_cli.input import parse_file_mentions
from deepagents_cli.thread_store import ThreadStoreError
from deepagents_cli.ui import (
    TokenTracker,
    format_tool_display,
    format_tool_message_content,
    render_diff_block,
    render_file_operation,
    render_todo_list,
)

class _FlexibleActionRequest(TypedDict):
    name: str
    args: dict[str, Any]
    description: NotRequired[str]


class _FlexibleReviewConfig(TypedDict):
    action_name: str
    allowed_decisions: list[str]
    args_schema: NotRequired[dict[str, Any]]


class _FlexibleHITLRequest(TypedDict):
    action_requests: list[_FlexibleActionRequest]
    review_configs: list[_FlexibleReviewConfig]
    metadata: NotRequired[dict[str, Any]]


if TYPE_CHECKING:  # pragma: no cover - typing aid only
    from deepagents.middleware.handoff_summarization import HandoffActionArgs


_HITL_REQUEST_ADAPTER = TypeAdapter(_FlexibleHITLRequest)


def _normalize_hitl_request_payload(payload: Any) -> dict[str, Any]:
    """Return a plain dict for any validated HITL payload."""
    if payload is None:
        return {}
    if hasattr(payload, "model_dump"):
        try:
            normalized = payload.model_dump()
        except Exception:  # pragma: no cover - defensive guard
            normalized = None
    else:
        normalized = payload

    if isinstance(normalized, dict):
        return dict(normalized)

    try:
        return dict(normalized)
    except Exception:  # pragma: no cover - final fallback
        return {}
logger = logging.getLogger(__name__)


def _coerce_action_args(raw_args: Any) -> dict[str, Any]:
    """Convert ActionRequest args into a mutable dict."""
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict):
        return dict(raw_args)
    if hasattr(raw_args, "model_dump"):
        try:
            dumped = raw_args.model_dump()
        except Exception:  # pragma: no cover - defensive guard
            return {}
        if isinstance(dumped, dict):
            return dict(dumped)
    return {}


def _resolve_handoff_action(
    hitl_request: dict[str, Any] | None,
) -> tuple["HandoffActionArgs", dict[str, Any] | None]:
    """Return canonical :class:`HandoffActionArgs` plus the raw request entry."""
    if not isinstance(hitl_request, dict):
        return {}, None

    action_requests = hitl_request.get("action_requests") or []
    for request in action_requests:
        if not isinstance(request, dict):
            continue
        if request.get("name") != HANDOFF_ACTION_NAME:
            continue
        return _coerce_action_args(request.get("args")), request

    # Backwards compatibility: fall back to legacy top-level shape
    fallback: dict[str, Any] = {}
    for key in (
        "handoff_id",
        "summary_md",
        "summary_json",
        "parent_thread_id",
        "assistant_id",
        "preview_only",
    ):
        value = hitl_request.get(key)
        if value is not None:
            fallback[key] = value
    return fallback, None


def is_handoff_request(hitl_request: Any) -> bool:
    if not isinstance(hitl_request, dict):
        return False
    if hitl_request.get("action") == HANDOFF_ACTION_NAME:
        return True
    action_requests = hitl_request.get("action_requests") or []
    if any(
        isinstance(req, dict) and req.get("name") == HANDOFF_ACTION_NAME
        for req in action_requests
    ):
        return True
    review_configs = hitl_request.get("review_configs") or []
    return any(
        isinstance(cfg, dict) and cfg.get("action_name") == HANDOFF_ACTION_NAME
        for cfg in review_configs
    )


def prompt_for_tool_approval(
    action_request: ActionRequest,
    assistant_id: str | None,
) -> Decision:
    """Prompt user to approve/reject a tool action with arrow key navigation."""
    description = action_request.get("description", "No description available")
    name = action_request["name"]
    args = action_request["args"]
    preview = build_approval_preview(name, args, assistant_id) if name else None

    body_lines = []
    if preview:
        body_lines.append(f"[bold]{preview.title}[/bold]")
        body_lines.extend(preview.details)
        if preview.error:
            body_lines.append(f"[red]{preview.error}[/red]")
    else:
        body_lines.append(description)

    # Display action info first
    console.print(
        Panel(
            "[bold yellow]⚠️  Tool Action Requires Approval[/bold yellow]\n\n"
            + "\n".join(body_lines),
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
    if preview and preview.diff and not preview.error:
        console.print()
        render_diff_block(preview.diff, preview.diff_title or preview.title)

    options = ["approve", "reject"]
    selected = 0  # Start with approve selected

    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            # Hide cursor during menu interaction
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()

            # Initial render flag
            first_render = True

            while True:
                if not first_render:
                    # Move cursor back to start of menu (up 2 lines, then to start of line)
                    sys.stdout.write("\033[2A\r")

                first_render = False

                # Display options vertically with ANSI color codes
                for i, option in enumerate(options):
                    sys.stdout.write("\r\033[K")  # Clear line from cursor to end

                    if i == selected:
                        if option == "approve":
                            # Green bold with filled checkbox
                            sys.stdout.write("\033[1;32m☑ Approve\033[0m\n")
                        else:
                            # Red bold with filled checkbox
                            sys.stdout.write("\033[1;31m☑ Reject\033[0m\n")
                    elif option == "approve":
                        # Dim with empty checkbox
                        sys.stdout.write("\033[2m☐ Approve\033[0m\n")
                    else:
                        # Dim with empty checkbox
                        sys.stdout.write("\033[2m☐ Reject\033[0m\n")

                sys.stdout.flush()

                # Read key
                char = sys.stdin.read(1)

                if char == "\x1b":  # ESC sequence (arrow keys)
                    next1 = sys.stdin.read(1)
                    next2 = sys.stdin.read(1)
                    if next1 == "[":
                        if next2 == "B":  # Down arrow
                            selected = (selected + 1) % len(options)
                        elif next2 == "A":  # Up arrow
                            selected = (selected - 1) % len(options)
                elif char in {"\r", "\n"}:  # Enter
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break
                elif char == "\x03":  # Ctrl+C
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    raise KeyboardInterrupt
                elif char.lower() == "a":
                    selected = 0
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break
                elif char.lower() == "r":
                    selected = 1
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break

        finally:
            # Show cursor again
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    except (termios.error, AttributeError):
        # Fallback for non-Unix systems
        console.print("  ☐ (A)pprove  (default)")
        console.print("  ☐ (R)eject")
        choice = input("\nChoice (A/R, default=Approve): ").strip().lower()
        selected = 1 if choice in {"r", "reject"} else 0

    # Return decision based on selection
    if selected == 0:
        return ApproveDecision(type="approve")
    return RejectDecision(type="reject", message="User rejected the command")


async def execute_task(
    user_input: str,
    agent,
    assistant_id: str | None,
    session_state,
    token_tracker: TokenTracker | None = None,
    backend=None,
    run_metadata: dict[str, Any] | None = None,
):
    """Execute any task by passing it directly to the AI agent."""
    # Parse file mentions and inject content if any
    prompt_text, mentioned_files = parse_file_mentions(user_input)

    if mentioned_files:
        context_parts = [prompt_text, "\n\n## Referenced Files\n"]
        for file_path in mentioned_files:
            try:
                content = file_path.read_text()
                # Limit file content to reasonable size
                if len(content) > 50000:
                    content = content[:50000] + "\n... (file truncated)"
                context_parts.append(
                    f"\n### {file_path.name}\nPath: `{file_path}`\n```\n{content}\n```"
                )
            except Exception as e:
                context_parts.append(f"\n### {file_path.name}\n[Error reading file: {e}]")

        final_input = "\n".join(context_parts)
    else:
        final_input = prompt_text

    thread_id = assistant_id or "main"
    if session_state and session_state.thread_manager:
        thread_id = session_state.thread_manager.get_current_thread_id()

    config_configurable: dict[str, Any] = {"thread_id": thread_id}
    if assistant_id:
        config_configurable["assistant_id"] = assistant_id

    handoff_trace_metadata: dict[str, Any] | None = None
    metadata_overrides = dict(run_metadata or {})
    auto_approve = bool(getattr(session_state, "auto_approve", False))

    def base_run_metadata() -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if session_state and session_state.thread_manager:
            try:
                thread_meta = session_state.thread_manager.get_thread_metadata(thread_id)
            except (ThreadStoreError, OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Failed to retrieve thread metadata for tracing context",
                    exc_info=True,
                    extra={"thread_id": thread_id, "error_type": type(exc).__name__},
                )
                thread_meta = None

            if thread_meta:
                thread_meta_block = dict(thread_meta.get("metadata") or {})
                if thread_meta_block:
                    metadata["thread_metadata"] = thread_meta_block
                    handoff_block = thread_meta_block.get("handoff")
                    if handoff_block:
                        metadata["handoff"] = handoff_block
                if name := thread_meta.get("name"):
                    metadata["thread_name"] = name
        return metadata

    def build_run_config(*, with_trace_metadata: bool = True) -> dict[str, Any]:
        metadata = base_run_metadata()
        if metadata_overrides:
            metadata.update(metadata_overrides)
        if with_trace_metadata and handoff_trace_metadata:
            metadata.update(handoff_trace_metadata)
        return {
            "configurable": config_configurable,
            "metadata": metadata,
        }

    def serialize_decision(decision: Decision | dict[str, Any]) -> dict[str, Any]:
        if isinstance(decision, dict):
            return decision
        return decision.model_dump()

    has_responded = False
    captured_input_tokens = 0
    captured_output_tokens = 0
    current_todos = None  # Track current todo list state

    status = console.status(f"[bold {COLORS['thinking']}]Agent is thinking...", spinner="dots")
    status.start()
    spinner_active = True

    tool_icons = {
        "read_file": "📖",
        "write_file": "✏️",
        "edit_file": "✂️",
        "ls": "📁",
        "glob": "🔍",
        "grep": "🔎",
        "shell": "⚡",
        "execute": "🔧",
        "web_search": "🌐",
        "http_request": "🌍",
        "task": "🤖",
        "write_todos": "📋",
    }

    file_op_tracker = FileOpTracker(assistant_id=assistant_id, backend=backend)

    # Track which tool calls we've displayed to avoid duplicates
    displayed_tool_ids = set()
    # Buffer partial tool-call chunks keyed by streaming index
    tool_call_buffers: dict[str | int, dict] = {}
    # Buffer assistant text so we can render complete markdown segments
    pending_text = ""

    def flush_text_buffer(*, final: bool = False) -> None:
        """Flush accumulated assistant text as rendered markdown when appropriate."""
        nonlocal pending_text, spinner_active, has_responded
        if not final or not pending_text.strip():
            return
        if spinner_active:
            status.stop()
            spinner_active = False
        if not has_responded:
            console.print("●", style=COLORS["agent"], markup=False, end=" ")
            has_responded = True
        markdown = Markdown(pending_text.rstrip())
        console.print(markdown, style=COLORS["agent"])
        pending_text = ""

    # Stream input - may need to loop if there are interrupts
    stream_input = {"messages": [{"role": "user", "content": final_input}]}

    try:
        while True:
            interrupt_occurred = False
            hitl_response: dict[str, HITLResponse] = {}
            suppress_resumed_output = False
            # Track all pending interrupts: {interrupt_id: request_data}
            pending_interrupts: dict[str, dict[str, Any]] = {}

            async for chunk in agent.astream(
                stream_input,
                stream_mode=["messages", "updates"],  # Dual-mode for HITL support
                subgraphs=True,
                config=build_run_config(),
                durability="exit",
            ):
                # Unpack chunk - with subgraphs=True and dual-mode, it's (namespace, stream_mode, data)
                if not isinstance(chunk, tuple) or len(chunk) != 3:
                    continue

                namespace, current_stream_mode, data = chunk

                # Handle UPDATES stream - for interrupts and todos
                if current_stream_mode == "updates":
                    if not isinstance(data, dict):
                        continue

                    # Check for interrupts - collect ALL pending interrupts
                    if "__interrupt__" in data:
                        interrupts: list[Interrupt] = data["__interrupt__"]
                        if interrupts:
                            for interrupt_obj in interrupts:
                                # Interrupt has required fields: value (HITLRequest) and id (str)
                                # Validate the HITLRequest using TypeAdapter
                                try:
                                    validated_request = _HITL_REQUEST_ADAPTER.validate_python(
                                        interrupt_obj.value
                                    )
                                    pending_interrupts[interrupt_obj.id] = (
                                        _normalize_hitl_request_payload(validated_request)
                                    )
                                    interrupt_occurred = True
                                except ValidationError as e:
                                    console.print(
                                        f"[yellow]Warning: Invalid HITL request data: {e}[/yellow]",
                                        style="dim",
                                    )
                                    raise

                    # Extract chunk_data from updates for todo checking
                    chunk_data = next(iter(data.values())) if data else None
                    if chunk_data and isinstance(chunk_data, dict):
                        # Check for todo updates
                        if "todos" in chunk_data:
                            new_todos = chunk_data["todos"]
                            if new_todos != current_todos:
                                current_todos = new_todos
                                # Stop spinner before rendering todos
                                if spinner_active:
                                    status.stop()
                                    spinner_active = False
                                console.print()
                                render_todo_list(new_todos)
                                console.print()

                # Handle MESSAGES stream - for content and tool calls
                elif current_stream_mode == "messages":
                    # Messages stream returns (message, metadata) tuples
                    if not isinstance(data, tuple) or len(data) != 2:
                        continue

                    message, metadata = data

                    if isinstance(message, HumanMessage):
                        content = message.text
                        if content:
                            flush_text_buffer(final=True)
                            if spinner_active:
                                status.stop()
                                spinner_active = False
                            if not has_responded:
                                console.print("●", style=COLORS["agent"], markup=False, end=" ")
                                has_responded = True
                            markdown = Markdown(content)
                            console.print(markdown, style=COLORS["agent"])
                            console.print()
                        continue

                    if isinstance(message, ToolMessage):
                        # Tool results are sent to the agent, not displayed to users
                        # Exception: show shell command errors to help with debugging
                        tool_name = getattr(message, "name", "")
                        tool_status = getattr(message, "status", "success")
                        tool_content = format_tool_message_content(message.content)
                        record = file_op_tracker.complete_with_message(message)

                        # Reset spinner message after tool completes
                        if spinner_active:
                            status.update(f"[bold {COLORS['thinking']}]Agent is thinking...")

                        if tool_name == "shell" and tool_status != "success":
                            flush_text_buffer(final=True)
                            if tool_content:
                                if spinner_active:
                                    status.stop()
                                    spinner_active = False
                                console.print()
                                console.print(tool_content, style="red", markup=False)
                                console.print()
                        elif tool_content and isinstance(tool_content, str):
                            stripped = tool_content.lstrip()
                            if stripped.lower().startswith("error"):
                                flush_text_buffer(final=True)
                                if spinner_active:
                                    status.stop()
                                    spinner_active = False
                                console.print()
                                console.print(tool_content, style="red", markup=False)
                                console.print()

                        if record:
                            flush_text_buffer(final=True)
                            if spinner_active:
                                status.stop()
                                spinner_active = False
                            console.print()
                            render_file_operation(record)
                            console.print()
                            if not spinner_active:
                                status.start()
                                spinner_active = True

                        # For all other tools (web_search, http_request, etc.),
                        # results are hidden from user - agent will process and respond
                        continue

                    # Check if this is an AIMessageChunk
                    if not hasattr(message, "content_blocks"):
                        # Fallback for messages without content_blocks
                        continue

                    # Extract token usage if available
                    if token_tracker and hasattr(message, "usage_metadata"):
                        usage = message.usage_metadata
                        if usage:
                            input_toks = usage.get("input_tokens", 0)
                            output_toks = usage.get("output_tokens", 0)
                            if input_toks or output_toks:
                                captured_input_tokens = max(captured_input_tokens, input_toks)
                                captured_output_tokens = max(captured_output_tokens, output_toks)

                    # Process content blocks (this is the key fix!)
                    for block in message.content_blocks:
                        block_type = block.get("type")

                        # Handle text blocks
                        if block_type == "text":
                            text = block.get("text", "")
                            if text:
                                pending_text += text

                        # Handle reasoning blocks
                        elif block_type == "reasoning":
                            flush_text_buffer(final=True)
                            reasoning = block.get("reasoning", "")
                            if reasoning and spinner_active:
                                status.stop()
                                spinner_active = False
                                # Could display reasoning differently if desired
                                # For now, skip it or handle minimally

                        # Handle tool call chunks
                        elif block_type == "tool_call_chunk":
                            chunk_name = block.get("name")
                            chunk_args = block.get("args")
                            chunk_id = block.get("id")
                            chunk_index = block.get("index")

                            # Use index as stable buffer key; fall back to id if needed
                            buffer_key: str | int
                            if chunk_index is not None:
                                buffer_key = chunk_index
                            elif chunk_id is not None:
                                buffer_key = chunk_id
                            else:
                                buffer_key = f"unknown-{len(tool_call_buffers)}"

                            buffer = tool_call_buffers.setdefault(
                                buffer_key,
                                {"name": None, "id": None, "args": None, "args_parts": []},
                            )

                            if chunk_name:
                                buffer["name"] = chunk_name
                            if chunk_id:
                                buffer["id"] = chunk_id

                            if isinstance(chunk_args, dict):
                                buffer["args"] = chunk_args
                                buffer["args_parts"] = []
                            elif isinstance(chunk_args, str):
                                if chunk_args:
                                    parts: list[str] = buffer.setdefault("args_parts", [])
                                    if not parts or chunk_args != parts[-1]:
                                        parts.append(chunk_args)
                                    buffer["args"] = "".join(parts)
                            elif chunk_args is not None:
                                buffer["args"] = chunk_args

                            buffer_name = buffer.get("name")
                            buffer_id = buffer.get("id")
                            if buffer_name is None:
                                continue
                            if buffer_id is not None and buffer_id in displayed_tool_ids:
                                continue

                            parsed_args = buffer.get("args")
                            if isinstance(parsed_args, str):
                                if not parsed_args:
                                    continue
                                try:
                                    parsed_args = json.loads(parsed_args)
                                except json.JSONDecodeError:
                                    # Wait for more chunks to form valid JSON
                                    continue
                            elif parsed_args is None:
                                continue

                            # Ensure args are in dict form for formatter
                            if not isinstance(parsed_args, dict):
                                parsed_args = {"value": parsed_args}

                            flush_text_buffer(final=True)
                            if buffer_id is not None:
                                displayed_tool_ids.add(buffer_id)
                                file_op_tracker.start_operation(buffer_name, parsed_args, buffer_id)
                            tool_call_buffers.pop(buffer_key, None)
                            icon = tool_icons.get(buffer_name, "🔧")

                            if spinner_active:
                                status.stop()

                            if has_responded:
                                console.print()

                            display_str = format_tool_display(buffer_name, parsed_args)
                            console.print(
                                f"  {icon} {display_str}",
                                style=f"dim {COLORS['tool']}",
                                markup=False,
                            )

                            # Restart spinner with context about which tool is executing
                            status.update(f"[bold {COLORS['thinking']}]Executing {display_str}...")
                            status.start()
                            spinner_active = True

                    if getattr(message, "chunk_position", None) == "last":
                        flush_text_buffer(final=True)

            # After streaming loop - handle interrupt if it occurred
            flush_text_buffer(final=True)

            # Handle human-in-the-loop after stream completes
            if interrupt_occurred:
                any_rejected = False

                for interrupt_id, hitl_request in pending_interrupts.items():
                    if is_handoff_request(hitl_request):
                        from deepagents_cli.handoff_ui import HandoffProposal, prompt_handoff_decision

                        payload_metadata = hitl_request.get("metadata")
                        if isinstance(payload_metadata, dict):
                            handoff_trace_metadata = payload_metadata.copy()

                        if spinner_active:
                            status.stop()
                            spinner_active = False

                        handoff_args, handoff_request = _resolve_handoff_action(hitl_request)
                        summary_json = handoff_args.get("summary_json") or hitl_request.get(
                            "summary_json", {}
                        )
                        if not isinstance(summary_json, dict):
                            summary_json = {}
                        else:
                            summary_json = dict(summary_json)
                        summary_md = (
                            handoff_args.get("summary_md")
                            or hitl_request.get("summary")
                            or hitl_request.get("summary_md")
                            or ""
                        )
                        summary_md = str(summary_md or "")
                        parent_thread_id = (
                            handoff_args.get("parent_thread_id")
                            or hitl_request.get("parent_thread_id")
                            or thread_id
                            or ""
                        )
                        parent_thread_id = str(parent_thread_id)
                        assistant_for_request = (
                            handoff_args.get("assistant_id")
                            or hitl_request.get("assistant_id")
                            or assistant_id
                            or ""
                        )
                        assistant_for_request = str(assistant_for_request)
                        preview_requested = bool(
                            handoff_args.get("preview_only")
                            or hitl_request.get("preview_only")
                            or (payload_metadata or {}).get("handoff", {}).get("preview_only")
                        )
                        handoff_id = (
                            handoff_args.get("handoff_id")
                            or hitl_request.get("handoff_id")
                            or ""
                        )
                        handoff_id = str(handoff_id)

                        if not summary_md and summary_json:
                            from deepagents.middleware.handoff_summarization import (
                                render_summary_markdown,
                            )

                            summary_md = render_summary_markdown(
                                summary_json.get("title", "Handoff Summary"),
                                summary_json.get("tldr", ""),
                                summary_json.get("body", []),
                            )

                        proposal = HandoffProposal(
                            handoff_id=handoff_id,
                            summary_json=summary_json,
                            summary_md=summary_md,
                            parent_thread_id=parent_thread_id,
                            assistant_id=str(assistant_for_request),
                        )

                        # Jason owns CLI handoff UX polish, including preview-mode follow-ups (issues #92/#93).
                        decision_result = await prompt_handoff_decision(
                            proposal,
                            preview_only=preview_requested,
                        )

                        decision_kind = (
                            getattr(decision_result, "status", None)
                            or getattr(decision_result, "type", None)
                            or ""
                        ).lower()
                        decision_payload: dict[str, Any] | None = None

                        if decision_kind in {"accepted", "accept", "approve", "approved"}:
                            decision_payload = {"type": "approve"}

                            try:
                                from deepagents.middleware.handoff_summarization import (
                                    HandoffSummary,
                                )

                                from deepagents_cli.handoff_persistence import (
                                    apply_handoff_acceptance,
                                )

                                parent_thread_id = parent_thread_id or hitl_request.get(
                                    "parent_thread_id", ""
                                )
                                hsum = HandoffSummary(
                                    handoff_id=proposal.handoff_id,
                                    summary_json=decision_result.summary_json
                                    or summary_json,
                                    summary_md=decision_result.summary_md or summary_md,
                                )

                                child_id = apply_handoff_acceptance(
                                    session_state=session_state,
                                    summary=hsum,
                                    summary_md=hsum.summary_md,
                                    summary_json=hsum.summary_json,
                                    parent_thread_id=parent_thread_id,
                                )

                                if session_state:
                                    session_state.pending_handoff_child_id = child_id
                                console.print()
                                console.print("[green]✓ Handoff approved. Processing...[/green]")
                                console.print()
                            except (ValueError, OSError, json.JSONDecodeError) as exc:
                                logger.warning(
                                    "Failed to persist handoff acceptance",
                                    extra={
                                        "error": str(exc),
                                        "error_type": type(exc).__name__,
                                        "parent_thread_id": parent_thread_id,
                                        "handoff_id": proposal.handoff_id,
                                    },
                                )
                        elif decision_kind in {"refine", "edit", "feedback"}:
                            action_name = (
                                (handoff_request or {}).get("name")
                                or hitl_request.get("action")
                                or HANDOFF_ACTION_NAME
                            )
                            edited_args: dict[str, Any] = dict(handoff_args)
                            edited_args.update(
                                {
                                    "handoff_id": proposal.handoff_id,
                                    "parent_thread_id": parent_thread_id,
                                    "summary_json": decision_result.summary_json or summary_json,
                                    "summary_md": decision_result.summary_md or summary_md,
                                }
                            )
                            if assistant_for_request and not edited_args.get("assistant_id"):
                                edited_args["assistant_id"] = assistant_for_request
                            feedback = getattr(decision_result, "feedback", None)
                            if feedback:
                                edited_args["feedback"] = feedback

                            decision_payload = {
                                "type": "edit",
                                "edited_action": {
                                    "name": action_name,
                                    "args": edited_args,
                                },
                            }
                            console.print()
                            console.print("[yellow]Regenerating summary with your feedback...[/yellow]")
                            console.print()
                        elif decision_kind == "preview":
                            console.print()
                            console.print(
                                "[dim]Preview-only review acknowledged. No decision sent; re-run the handoff when ready.[/dim]"
                            )
                            console.print()
                            decision_payload = {"type": "preview"}
                        else:
                            decision_payload = {
                                "type": "reject",
                                "message": "User declined handoff",
                            }

                        if decision_payload and decision_payload.get("type") == "reject":
                            any_rejected = True

                        if decision_payload:
                            hitl_response[interrupt_id] = {"decisions": [decision_payload]}

                        continue

                    action_requests = (
                        hitl_request.get("action_requests", []) if hitl_request else []
                    )
                    decisions: list[Decision | dict[str, Any]] = []

                    if auto_approve:
                        for action_request in action_requests:
                            if spinner_active:
                                status.stop()
                                spinner_active = False

                            description = action_request.get("description", "tool action")
                            console.print()
                            console.print(f"  [dim]⚡ {description}[/dim]")
                            decisions.append(ApproveDecision(type="approve"))

                        if not spinner_active:
                            status.start()
                            spinner_active = True
                    else:
                        if spinner_active:
                            status.stop()
                            spinner_active = False

                        for action_request in action_requests:
                            decision = prompt_for_tool_approval(
                                action_request,
                                assistant_id,
                            )
                            decisions.append(decision)

                    serialized_decisions = [serialize_decision(d) for d in decisions]
                    if any(decision.get("type") == "reject" for decision in serialized_decisions):
                        any_rejected = True

                    hitl_response[interrupt_id] = {"decisions": serialized_decisions}

                suppress_resumed_output = any_rejected

            if interrupt_occurred and hitl_response:
                if suppress_resumed_output:
                    if spinner_active:
                        status.stop()
                        spinner_active = False

                    console.print("[yellow]Command rejected.[/yellow]", style="bold")
                    console.print("Tell the agent what you'd like to do differently.")
                    console.print()
                    return

                # Resume the agent with the human decision
                stream_input = Command(resume=hitl_response)
                # Continue the while loop to restream
            else:
                # No interrupt, break out of while loop
                handoff_trace_metadata = None
                break

    except asyncio.CancelledError:
        # Event loop cancelled the task (e.g. Ctrl+C during streaming) - clean up and return
        if spinner_active:
            status.stop()
        console.print("\n[yellow]Interrupted by user[/yellow]")
        console.print("Updating agent state...", style="dim")

        try:
            await agent.aupdate_state(
                config=build_run_config(with_trace_metadata=False),
                values={
                    "messages": [
                        HumanMessage(content="[The previous request was cancelled by the system]")
                    ]
                },
            )
            console.print("Ready for next command.\n", style="dim")
        except Exception as e:
            console.print(f"[red]Warning: Failed to update agent state: {e}[/red]\n")

        return

    except KeyboardInterrupt:
        # User pressed Ctrl+C - clean up and exit gracefully
        if spinner_active:
            status.stop()
        console.print("\n[yellow]Interrupted by user[/yellow]")
        console.print("Updating agent state...", style="dim")

        # Inform the agent synchronously (in async context)
        try:
            await agent.aupdate_state(
                config=build_run_config(with_trace_metadata=False),
                values={
                    "messages": [
                        HumanMessage(content="[User interrupted the previous request with Ctrl+C]")
                    ]
                },
            )
            console.print("Ready for next command.\n", style="dim")
        except Exception as e:
            console.print(f"[red]Warning: Failed to update agent state: {e}[/red]\n")

        return

    if spinner_active:
        status.stop()

    if has_responded:
        console.print()
        # Track token usage (display only via /tokens command)
        if token_tracker and (captured_input_tokens or captured_output_tokens):
            token_tracker.add(captured_input_tokens, captured_output_tokens)

            if session_state and session_state.thread_manager and thread_id:
                try:
                    session_state.thread_manager.update_token_count(
                        thread_id, token_tracker.current_context
                    )
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    logger.debug(
                        "Failed to update token count",
                        extra={
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "thread_id": thread_id,
                        },
                    )
                    # Non-critical - token tracking is for display only via /tokens command

    if session_state and session_state.thread_manager and thread_id:
        try:
            final_state = await agent.aget_state(build_run_config(with_trace_metadata=False))
        except Exception as exc:
            logger.warning(
                "Failed to load final agent state",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "thread_id": thread_id,
                },
            )
            final_state = None
        else:
            if final_state and final_state.values.get("_handoff_cleanup_pending"):
                from deepagents_cli.handoff_persistence import clear_summary_block_file

                try:
                    agent_md_path = session_state.thread_manager.agent_dir / "agent.md"
                    clear_summary_block_file(agent_md_path)

                    thread_meta = session_state.thread_manager.get_thread_metadata(thread_id)
                    if thread_meta:
                        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                        existing = dict(
                            (thread_meta.get("metadata") or {}).get("handoff") or {}
                        )
                        updated = existing | {
                            "pending": False,
                            "cleanup_required": False,
                            "last_cleanup_at": timestamp,
                        }
                        # Jason is the contact for broader lifecycle follow-ups (issue #91).
                        session_state.thread_manager.update_thread_metadata(
                            thread_id,
                            {"handoff": updated},
                        )
                    else:
                        logger.debug(
                            "Skipping handoff metadata cleanup; metadata unavailable",
                            extra={"thread_id": thread_id},
                        )
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "Failed to clean up handoff state",
                        extra={
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "thread_id": thread_id,
                            "operation": "clear_summary_block_file",
                        },
                    )

        try:
            session_state.thread_manager.touch_thread(thread_id, reason="interaction")
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            logger.debug(
                "Failed to touch thread timestamp",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "thread_id": thread_id,
                    "reason": "interaction",
                },
            )
