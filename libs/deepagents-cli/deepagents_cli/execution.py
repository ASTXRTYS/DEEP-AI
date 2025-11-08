"""Task execution and streaming logic for the CLI."""

import asyncio
import json
import sys
import termios
import tty
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel

from .config import COLORS, console
from .file_ops import FileOpTracker, build_approval_preview
from .handoff_approval import HandoffProposal, prompt_handoff_decision
from .handoff_summarization import apply_handoff_acceptance, clear_summary_block_file
from .input import parse_file_mentions
from .ui import (
    TokenTracker,
    format_tool_display,
    format_tool_message_content,
    render_diff_block,
    render_file_operation,
    render_todo_list,
)
from deepagents.middleware.handoff_summarization import HandoffSummary


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


def prompt_for_tool_approval(action_request: dict, assistant_id: str | None) -> dict:
    """Prompt user to approve/reject a tool action with arrow key navigation."""
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
        return {"type": "approve"}
    return {"type": "reject", "message": "User rejected the command"}


async def execute_task(
    user_input: str,
    agent,
    assistant_id: str | None,
    session_state,
    token_tracker: TokenTracker | None = None,
    *,
    handoff_request: bool = False,
    handoff_preview_only: bool = False,
) -> None:
    """Execute any task by passing it directly to the AI agent."""
    mentioned_files = []
    if handoff_request:
        # Anthropic requires non-empty content for all messages except the final assistant.
        # Provide a minimal placeholder to trigger middleware without causing 400 errors.
        final_input = "[handoff] Please prepare a handoff summary."
    else:
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

    config_metadata = {"thread_id": thread_id}
    if assistant_id:
        config_metadata["assistant_id"] = assistant_id

    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": config_metadata,
    }

    if handoff_request:
        config["configurable"]["handoff_requested"] = True
        # Mirror to metadata so middleware can read the flag even if configurable keys are filtered.
        config_metadata["handoff_requested"] = True
        config_metadata["handoff_preview_only"] = handoff_preview_only

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
            interrupt_occurred = False
            hitl_response = None
            suppress_resumed_output = False
            hitl_request = None
            last_handoff_proposal: dict | None = None

            async for chunk in agent.astream(
                stream_input,
                stream_mode=["messages", "updates"],  # Dual-mode for HITL support
                subgraphs=True,
                config=config,
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
                        if interrupt_data:
                            # LangGraph emits a list of interrupts; take the first
                            if isinstance(interrupt_data, (list, tuple)):
                                interrupt_obj = interrupt_data[0]
                            else:
                                interrupt_obj = interrupt_data

                            # Unwrap to the interrupt payload (value)
                            hitl_request = (
                                getattr(interrupt_obj, "value", interrupt_obj)
                            )

                            # If the value is itself a wrapper, unwrap again
                            if not isinstance(hitl_request, dict) and hasattr(
                                hitl_request, "value"
                            ):
                                hitl_request = hitl_request.value

                            interrupt_occurred = True

                    # Extract chunk_data from updates for todo/proposal checking
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

                        # Capture handoff proposal as a fallback if present
                        if "handoff_proposal" in data and isinstance(data["handoff_proposal"], dict):
                            last_handoff_proposal = data["handoff_proposal"]
                        elif "handoff_proposal" in chunk_data and isinstance(
                            chunk_data.get("handoff_proposal"), dict
                        ):
                            last_handoff_proposal = chunk_data["handoff_proposal"]

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
                # Coerce hitl_request into a dict payload if possible
                if not isinstance(hitl_request, dict):
                    if isinstance(hitl_request, (list, tuple)) and hitl_request:
                        maybe = hitl_request[0]
                        hitl_request = getattr(maybe, "value", maybe)
                if not isinstance(hitl_request, dict):
                    # Could not parse interrupt payload; abort HITL handling
                    hitl_request = None

                decisions = []
                handoff_interrupt_processed = False
                action_requests = (
                    hitl_request.get("action_requests", []) if hitl_request else []
                )

                for action_request in action_requests:
                    action_name = action_request.get("name")
                    if action_name == "handoff_summary":
                        if spinner_active:
                            status.stop()
                            spinner_active = False
                        decision = await _handle_handoff_interrupt(
                            action_request,
                            session_state=session_state,
                            preview_only=handoff_preview_only
                            or action_request.get("args", {}).get("preview_only", False),
                        )
                        if decision is None:
                            continue
                        decision["_action"] = action_name
                        decisions.append(decision)
                        # Per design, do not continue streaming after handoff review
                        handoff_interrupt_processed = True
                        continue

                    if session_state.auto_approve:
                        if spinner_active:
                            status.stop()
                            spinner_active = False

                        description = action_request.get("description", "tool action")
                        console.print()
                        console.print(f"  [dim]⚡ {description}[/dim]")

                        decisions.append({"type": "approve", "_action": action_name})

                        if not spinner_active:
                            status.start()
                            spinner_active = True
                    else:
                        if spinner_active:
                            status.stop()
                            spinner_active = False

                        decision = await asyncio.to_thread(
                            prompt_for_tool_approval,
                            action_request,
                            assistant_id,
                        )
                        decision["_action"] = action_name
                        decisions.append(decision)

                suppress_resumed_output = any(
                    decision.get("type") == "reject"
                    and decision.get("_action") != "handoff_summary"
                    for decision in decisions
                )

                cleaned_decisions = []
                for decision in decisions:
                    decision = dict(decision)
                    decision.pop("_action", None)
                    cleaned_decisions.append(decision)

                hitl_response = {"decisions": cleaned_decisions}

            # If we handled a handoff interrupt, exit immediately to avoid
            # further model calls or streaming. Side effects (summary write,
            # child thread creation) are already done in the handler.
            if 'handoff_interrupt_processed' in locals() and handoff_interrupt_processed:
                if spinner_active:
                    status.stop()
                    spinner_active = False
                return

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
                # No interrupt, break out of while loop or apply fallback
                if handoff_request and last_handoff_proposal:
                    if spinner_active:
                        status.stop()
                        spinner_active = False
                    synthetic_action = {
                        "name": "handoff_summary",
                        "description": "Preview handoff summary for approval",
                        "args": {
                            "handoff_id": last_handoff_proposal.get("handoff_id"),
                            "summary_json": last_handoff_proposal.get("summary_json"),
                            "summary_md": last_handoff_proposal.get("summary_md"),
                            "assistant_id": last_handoff_proposal.get("assistant_id"),
                            "parent_thread_id": last_handoff_proposal.get("parent_thread_id"),
                            "preview_only": config.get("metadata", {}).get("handoff_preview_only", False),
                        },
                    }
                    decision = await _handle_handoff_interrupt(
                        synthetic_action,
                        session_state=session_state,
                        preview_only=config.get("metadata", {}).get("handoff_preview_only", False),
                    )
                    return

                # Secondary fallback: try to fetch proposal from agent state
                if handoff_request and not last_handoff_proposal:
                    try:
                        state_snapshot = await agent.aget_state(config)
                        proposal = state_snapshot.values.get("handoff_proposal")
                    except Exception:
                        proposal = None
                    if isinstance(proposal, dict):
                        if spinner_active:
                            status.stop()
                            spinner_active = False
                        action_request = {
                            "name": "handoff_summary",
                            "description": "Preview handoff summary for approval",
                            "args": {
                                "handoff_id": proposal.get("handoff_id"),
                                "summary_json": proposal.get("summary_json"),
                                "summary_md": proposal.get("summary_md"),
                                "assistant_id": proposal.get("assistant_id"),
                                "parent_thread_id": proposal.get("parent_thread_id"),
                                "preview_only": config.get("metadata", {}).get("handoff_preview_only", False),
                            },
                        }
                        _ = await _handle_handoff_interrupt(
                            action_request,
                            session_state=session_state,
                            preview_only=config.get("metadata", {}).get("handoff_preview_only", False),
                        )
                        return

                # Tertiary fallback: generate summary on the fly using middleware helper
                if handoff_request and not last_handoff_proposal:
                    try:
                        from deepagents.middleware.handoff_summarization import (
                            generate_handoff_summary,
                        )
                        state_snapshot = await agent.aget_state(config)
                        messages = state_snapshot.values.get("messages", [])
                        summary = generate_handoff_summary(
                            model=session_state.model if hasattr(session_state, "model") else agent,
                            messages=messages,
                            assistant_id=assistant_id or "agent",
                            parent_thread_id=thread_id,
                        )
                        if spinner_active:
                            status.stop()
                            spinner_active = False
                        action_request = {
                            "name": "handoff_summary",
                            "description": "Preview handoff summary for approval",
                            "args": {
                                "handoff_id": summary.handoff_id,
                                "summary_json": summary.summary_json,
                                "summary_md": summary.summary_md,
                                "assistant_id": assistant_id or "agent",
                                "parent_thread_id": thread_id,
                                "preview_only": config.get("metadata", {}).get("handoff_preview_only", False),
                            },
                        }
                        _ = await _handle_handoff_interrupt(
                            action_request,
                            session_state=session_state,
                            preview_only=config.get("metadata", {}).get("handoff_preview_only", False),
                        )
                        return
                    except Exception:
                        pass

                break

    except asyncio.CancelledError:
        # Event loop cancelled the task (e.g. Ctrl+C during streaming) - clean up and return
        if spinner_active:
            status.stop()
        console.print("\n[yellow]Interrupted by user[/yellow]")
        console.print("Updating agent state...", style="dim")

        try:
            await agent.aupdate_state(
                config=config,
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
                config=config,
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
                except Exception:  # pragma: no cover - defensive
                    pass

    # Touch the thread so cleanup/TTL logic sees recent activity
    if session_state and session_state.thread_manager and thread_id:
        _cleanup_pending_handoff(session_state, thread_id)
        try:
            session_state.thread_manager.touch_thread(thread_id, reason="interaction")
        except Exception:  # pragma: no cover - defensive
            pass


async def _handle_handoff_interrupt(
    action_request: dict,
    *,
    session_state,
    preview_only: bool,
) -> dict | None:
    args = action_request.get("args") or {}

    if not session_state or not getattr(session_state, "thread_manager", None):
        console.print("[red]Thread manager not available; cannot complete handoff.[/red]")
        console.print()
        return {"type": "reject"}
    proposal = HandoffProposal(
        handoff_id=args.get("handoff_id", ""),
        summary_json=args.get("summary_json") or {},
        summary_md=args.get("summary_md") or "",
        parent_thread_id=args.get("parent_thread_id", ""),
        assistant_id=args.get("assistant_id", ""),
    )

    decision = await asyncio.to_thread(
        prompt_handoff_decision,
        proposal,
        preview_only=preview_only,
    )

    if decision.status == "preview":
        console.print("[dim]Preview-only mode — no changes were applied.[/dim]")
        console.print()
        return {"type": "reject"}

    if decision.status == "declined":
        console.print("[yellow]Handoff summary declined by user.[/yellow]")
        console.print()
        return {"type": "reject"}

    if decision.status != "accepted":
        console.print("[red]Unexpected handoff status. Aborting handoff.[/red]")
        console.print()
        return {"type": "reject"}

    summary_json = dict(decision.summary_json or proposal.summary_json)
    summary_md = decision.summary_md or proposal.summary_md
    summary = HandoffSummary(
        handoff_id=proposal.handoff_id,
        summary_json=summary_json,
        summary_md=summary_md,
    )

    child_thread_id = apply_handoff_acceptance(
        session_state=session_state,
        summary=summary,
        summary_md=summary_md,
        summary_json=summary_json,
        parent_thread_id=proposal.parent_thread_id,
    )

    console.print(f"[green]✓ Handoff approved. New thread {child_thread_id[:8]} is now active.[/green]")
    console.print("[dim]The summary was injected into agent.md for the next assistant turn.[/dim]")
    console.print()

    return {
        "type": "approve",
        "args": {
            "summary_json": summary_json,
            "summary_md": summary_md,
            "child_thread_id": child_thread_id,
        },
    }


def _cleanup_pending_handoff(session_state, thread_id: str) -> None:
    thread_manager = getattr(session_state, "thread_manager", None)
    if not thread_manager:
        return

    metadata_record = thread_manager.get_thread_metadata(thread_id)
    if not metadata_record:
        return

    metadata = metadata_record.get("metadata")
    if not isinstance(metadata, dict):
        return

    handoff_meta = metadata.get("handoff")
    if not isinstance(handoff_meta, dict):
        return

    if not (handoff_meta.get("pending") and handoff_meta.get("cleanup_required")):
        return

    agent_md_path = thread_manager.agent_dir / "agent.md"
    try:
        clear_summary_block_file(agent_md_path)
    except Exception:  # pragma: no cover - defensive
        console.print("[yellow]Failed to clear handoff summary block.[/yellow]")
        return

    updated = dict(handoff_meta)
    updated["pending"] = False
    updated["cleanup_required"] = False
    updated["last_cleanup_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    try:
        thread_manager.update_thread_metadata(thread_id, {"handoff": updated})
    except Exception:  # pragma: no cover - defensive
        pass
    else:
        console.print("[dim]Cleared handoff summary after first assistant reply.[/dim]")
