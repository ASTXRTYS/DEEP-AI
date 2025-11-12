"""Task execution and streaming logic for the CLI."""

import asyncio
import json
import logging
from datetime import UTC
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel

from .config import COLORS, console
from .file_ops import FileOpTracker, build_approval_preview
from .input import parse_file_mentions
from .rich_ui import RichPrompt
from .thread_store import ThreadStoreError
from .ui import (
    TokenTracker,
    format_tool_display,
    format_tool_message_content,
    render_diff_block,
    render_file_operation,
    render_todo_list,
)

logger = logging.getLogger(__name__)


def _unwrap_interrupt(data: Any) -> dict | None:
    """Unwrap interrupt payload to extract dict payload.

    LangGraph interrupts can be nested in multiple ways:
    - As a list: [InterruptObj]
    - As an object with .value attribute
    - As a bare dict

    This function safely unwraps to the innermost dict payload.

    Args:
        data: Raw interrupt data from __interrupt__ field

    Returns:
        Dict payload if found, None otherwise
    """
    # Step 1: Unwrap list/tuple
    if isinstance(data, (list, tuple)):
        if not data:
            return None
        data = data[0]

    # Step 2: Unwrap .value attribute (may be nested)
    while hasattr(data, "value") and not isinstance(data, dict):
        data = data.value

    # Step 3: Validate final payload
    return data if isinstance(data, dict) else None


def _extract_tool_args(action_request: dict) -> dict | None:
    """Best-effort extraction of tool call arguments from an action request."""
    if "tool_call" in action_request and isinstance(action_request["tool_call"], dict):
        args = action_request["tool_call"].get("args")
        if isinstance(args, dict):
            return args
    args = action_request.get("args")
    if isinstance(args, dict):
        return args
    return None


async def prompt_for_tool_approval(action_request: dict, assistant_id: str | None) -> dict:
    """Prompt user to approve/reject a tool action with Rich prompts.

    NOTE: This function is async to support async prompt workflows.
    Callers must await this function.
    """
    description = action_request.get("description", "No description available")
    tool_name = action_request.get("name") or action_request.get("tool")
    tool_args = _extract_tool_args(action_request)
    preview = build_approval_preview(tool_name, tool_args, assistant_id) if tool_name else None

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

    # Use Rich prompts for approval
    rich_prompt = RichPrompt(console)

    console.print()
    try:
        decision = await rich_prompt.select_async(
            question="Choose an action:",
            choices=[
                ("approve", "✓  Approve (allow this tool to run)"),
                ("reject", "✕  Reject (block this tool)"),
            ],
            default="approve",
        )
    except (KeyboardInterrupt, EOFError):
        decision = None

    # Handle cancellation (None return)
    if decision is None:
        console.print()
        console.print("[dim]✓ Approval cancelled - tool rejected.[/dim]")
        console.print()
        return {"type": "reject", "message": "User cancelled approval"}

    console.print()
    if decision == "approve":
        return {"type": "approve"}
    return {"type": "reject", "message": "User rejected the command"}


async def execute_task(
    user_input: str,
    agent,
    assistant_id: str | None,
    session_state,
    token_tracker: TokenTracker | None = None,
) -> None:
    """Execute task with generic interrupt handling (no handoff-specific params)."""
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

    # Use thread manager's current thread ID for dynamic thread switching
    thread_id = assistant_id or "main"
    if session_state and session_state.thread_manager:
        thread_id = session_state.thread_manager.get_current_thread_id()

    # Build configurable section (execution parameters only)
    config_configurable = {"thread_id": thread_id}
    if assistant_id:
        config_configurable["assistant_id"] = assistant_id

    handoff_trace_metadata: dict[str, Any] | None = None

    def base_run_metadata() -> dict[str, Any]:
        """Capture workflow-specific metadata for LangSmith tracing.

        NOTE: thread_id and assistant_id are in configurable, not here.
        This follows LangGraph best practices - configurable for execution
        parameters, metadata for observability/tracing context only.
        """
        metadata: dict[str, Any] = {}

        if session_state and session_state.thread_manager:
            try:
                thread_meta = session_state.thread_manager.get_thread_metadata(thread_id)
            except (ThreadStoreError, OSError, json.JSONDecodeError) as e:
                # Non-fatal: metadata enrichment is optional for tracing
                logger.warning(
                    "Failed to retrieve thread metadata for tracing context",
                    exc_info=True,
                    extra={"thread_id": thread_id, "error_type": type(e).__name__},
                )
                thread_meta = None

            if thread_meta:
                # Surface thread-level metadata for middleware (e.g., handoff flags)
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
        """Compose per-run config for graph execution.

        Returns RunnableConfig with:
        - configurable: Execution parameters (thread_id, assistant_id)
        - metadata: Workflow-specific tracing context (handoff state, etc.)
        """
        metadata = base_run_metadata()
        if with_trace_metadata and handoff_trace_metadata:
            metadata.update(handoff_trace_metadata)
        return {
            "configurable": config_configurable,
            "metadata": metadata,
        }

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
        "web_search": "🌐",
        "http_request": "🌍",
        "task": "🤖",
        "write_todos": "📋",
    }

    file_op_tracker = FileOpTracker(assistant_id=assistant_id)

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

    # Handoff requests now flow through agent middlewares via interrupts.
    # We still set the config flags above; middlewares will emit an interrupt
    # which the streaming loop handles. We intentionally avoid any synchronous
    # summary generation here to ensure proper tracing and UX.

    # Stream input - may need to loop if there are interrupts
    stream_input = {"messages": [{"role": "user", "content": final_input}]}

    try:
        while True:
            current_config = build_run_config()
            interrupt_occurred = False
            hitl_response = None
            suppress_resumed_output = False
            hitl_request = None

            async for chunk in agent.astream(
                stream_input,
                stream_mode=["messages", "updates"],  # Dual-mode for HITL support
                subgraphs=True,
                config=current_config,
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

                    # Check for interrupts - just capture the data, don't handle yet
                    if "__interrupt__" in data:
                        interrupt_data = data["__interrupt__"]
                        hitl_request = _unwrap_interrupt(interrupt_data)
                        if hitl_request:
                            interrupt_occurred = True

                    # Extract chunk_data from updates for todo/proposal checking
                    # Debug: Check all values in data dict for handoff state
                    chunk_data = next(iter(data.values())) if data else None

                    # Also check if handoff state is directly in data (not nested)
                    if not chunk_data and isinstance(data, dict):
                        chunk_data = data

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

                        # Handoff interrupts are now handled via HandoffApprovalMiddleware.interrupt()
                        # Detection happens through __interrupt__ field (line 314), not state updates

                # Handle MESSAGES stream - for content and tool calls
                elif current_stream_mode == "messages":
                    # Messages stream returns (message, metadata) tuples
                    if not isinstance(data, tuple) or len(data) != 2:
                        continue

                    message, metadata = data

                    if isinstance(message, HumanMessage):
                        content = message.text()
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

                            if not spinner_active:
                                status.start()
                                spinner_active = True

                    if getattr(message, "chunk_position", None) == "last":
                        flush_text_buffer(final=True)

            # After streaming loop - handle interrupt if it occurred
            flush_text_buffer(final=True)

            # Handle human-in-the-loop after stream completes
            if interrupt_occurred and hitl_request:
                handoff_trace_metadata = None
                # hitl_request is already unwrapped by _unwrap_interrupt()
                # but double-check it's a valid dict
                if not isinstance(hitl_request, dict):
                    hitl_request = None

                decisions = []
                # Check for handoff approval interrupt (from HandoffApprovalMiddleware)
                if hitl_request and hitl_request.get("action") == "approve_handoff":
                    # Import handoff UI
                    from .handoff_ui import HandoffProposal, prompt_handoff_decision

                    payload_metadata = hitl_request.get("metadata")
                    if isinstance(payload_metadata, dict):
                        handoff_trace_metadata = payload_metadata.copy()

                    if spinner_active:
                        status.stop()
                        spinner_active = False

                    # Build proposal from interrupt payload
                    proposal = HandoffProposal(
                        handoff_id=hitl_request.get("handoff_id", ""),
                        summary_json=hitl_request.get("summary_json", {}),
                        summary_md=hitl_request.get(
                            "summary", ""
                        ),  # "summary" key in interrupt payload
                        parent_thread_id=hitl_request.get("parent_thread_id", ""),
                        assistant_id=hitl_request.get("assistant_id", ""),
                    )

                    # Get user decision (approve/refine/reject)
                    # prompt_handoff_decision is now async, so await directly
                    decision_result = await prompt_handoff_decision(
                        proposal,
                        preview_only=False,
                    )

                    # Build resume data in format HandoffApprovalMiddleware expects
                    if decision_result.type == "approve":
                        # User approved - send approval to middleware
                        decisions.append(
                            {
                                "type": "approve",
                            }
                        )

                        # Prepare handoff but DON'T switch thread yet
                        try:
                            from deepagents.middleware.handoff_summarization import HandoffSummary

                            from deepagents_cli.handoff_persistence import apply_handoff_acceptance

                            parent_thread_id = hitl_request.get("parent_thread_id", "")
                            hsum = HandoffSummary(
                                handoff_id=hitl_request.get("handoff_id", ""),
                                summary_json=decision_result.summary_json
                                or hitl_request.get("summary_json", {}),
                                summary_md=decision_result.summary_md
                                or hitl_request.get("summary", ""),
                            )

                            child_id = apply_handoff_acceptance(
                                session_state=session_state,
                                summary=hsum,
                                summary_md=hsum.summary_md,
                                summary_json=hsum.summary_json,
                                parent_thread_id=parent_thread_id,
                            )

                            # Store child_id for deferred switching (AFTER stream completes)
                            session_state.pending_handoff_child_id = child_id
                            console.print()
                            console.print("[green]✓ Handoff approved. Processing...[/green]")
                            console.print()

                            # Don't return here - must continue to where Command(resume=...)
                            # is sent to deliver the approval decision to the middleware.
                            # Thread switching will happen in main.py after execute_task() completes.

                        except (ValueError, OSError, json.JSONDecodeError) as e:
                            logger.warning(
                                "Failed to persist handoff acceptance",
                                extra={
                                    "error": str(e),
                                    "error_type": type(e).__name__,
                                    "parent_thread_id": parent_thread_id,
                                    "handoff_id": hitl_request.get("handoff_id", ""),
                                },
                            )
                            # Continue - user already approved, middleware has resume decision
                            # Handoff will still complete via middleware, persistence failure is non-fatal

                    elif decision_result.type == "refine":
                        # User wants refinement - send feedback to middleware
                        # Middleware will regenerate and interrupt again with new summary
                        decisions.append(
                            {
                                "type": "refine",
                                "feedback": decision_result.feedback or "",
                            }
                        )
                        console.print()
                        console.print("[yellow]Regenerating summary with your feedback...[/yellow]")
                        console.print()

                    else:  # reject
                        # User rejected - send rejection to middleware
                        decisions.append(
                            {
                                "type": "reject",
                                "message": "User declined handoff",
                            }
                        )

                # Handle other HITL actions (tool approvals) with legacy schema
                else:
                    action_requests = (
                        hitl_request.get("action_requests", []) if hitl_request else []
                    )

                    for action_request in action_requests:
                        action_name = action_request.get("name")

                        if session_state.auto_approve:
                            if spinner_active:
                                status.stop()
                                spinner_active = False

                            description = action_request.get("description", "tool action")
                            console.print()
                            console.print(f"  [dim]⚡ {description}[/dim]")

                            decisions.append({"type": "approve"})

                            if not spinner_active:
                                status.start()
                                spinner_active = True
                        else:
                            if spinner_active:
                                status.stop()
                                spinner_active = False

                            # prompt_for_tool_approval is now async, so await directly
                            decision = await prompt_for_tool_approval(
                                action_request,
                                assistant_id,
                            )
                            decisions.append(decision)

                # Suppress output if any action was rejected (but NOT for refine - that continues the loop)
                # For handoff decisions, check "type"; for tool approvals, check "type"
                suppress_resumed_output = any(d.get("type") == "reject" for d in decisions)

                # Format resume data based on what type of interrupt occurred
                if hitl_request and hitl_request.get("action") == "approve_handoff":
                    # HandoffApprovalMiddleware expects: {"type": "approve|refine|reject", "feedback": "..."}
                    hitl_response = decisions[0] if decisions else {"type": "reject"}
                else:
                    # Other HITL actions (tool approvals) expect {"decisions": [...]} format
                    hitl_response = {"decisions": decisions}

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

            # Persist token count to thread metadata
            if session_state and session_state.thread_manager and thread_id:
                try:
                    session_state.thread_manager.update_token_count(
                        thread_id, token_tracker.current_context
                    )
                except (ValueError, OSError, json.JSONDecodeError) as e:
                    logger.debug(
                        "Failed to update token count",
                        extra={
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "thread_id": thread_id,
                        },
                    )
                    # Non-critical - token tracking is for display only via /tokens command

    # Check for handoff cleanup flag and clear summary block if needed
    if session_state and session_state.thread_manager and thread_id:
        try:
            # Get final state to check for cleanup flag
            final_state = await agent.aget_state(build_run_config(with_trace_metadata=False))
            if final_state and final_state.values.get("_handoff_cleanup_pending"):
                # Clear the summary block from agent.md
                from datetime import datetime

                from deepagents_cli.handoff_persistence import clear_summary_block_file

                agent_md_path = session_state.thread_manager.agent_dir / "agent.md"
                clear_summary_block_file(agent_md_path)

                # Update thread metadata to mark cleanup as complete
                # Get existing handoff metadata and update only cleanup fields
                thread_meta = session_state.thread_manager.get_thread_metadata(thread_id)
                if thread_meta and "handoff" in thread_meta.get("metadata", {}):
                    existing_handoff = thread_meta["metadata"]["handoff"]
                    updated_handoff = existing_handoff | {
                        "pending": False,
                        "cleanup_required": False,
                        "last_cleanup_at": datetime.now(UTC).isoformat(),
                    }
                    session_state.thread_manager.update_thread_metadata(
                        thread_id,
                        {"handoff": updated_handoff},
                    )
        except (ValueError, OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to clean up handoff state",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "thread_id": thread_id,
                    "operation": "clear_summary_block_file",
                },
            )
            # Non-fatal - stale handoff metadata won't break functionality
            # Next handoff will overwrite or cleanup will retry on next execution

    # Touch the thread so cleanup/TTL logic sees recent activity
    if session_state and session_state.thread_manager and thread_id:
        try:
            session_state.thread_manager.touch_thread(thread_id, reason="interaction")
        except (ValueError, OSError, json.JSONDecodeError) as e:
            logger.debug(
                "Failed to touch thread timestamp",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "thread_id": thread_id,
                    "reason": "interaction",
                },
            )
            # Non-critical - TTL tracking is best-effort for cleanup scheduling
