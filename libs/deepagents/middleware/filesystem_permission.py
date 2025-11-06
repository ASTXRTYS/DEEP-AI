"""Middleware wrapper for handling filesystem permission errors."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Awaitable

from langchain.agents.middleware import wrap_tool_call
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)

FILESYSTEM_TOOLS = {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}
PERMISSION_ERRORS = (PermissionError, OSError)


@wrap_tool_call
async def handle_filesystem_permissions(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:
    """Catch permission-related errors from filesystem tools and respond gracefully."""
    tool_name = request.tool_call.get("name", "unknown")
    if tool_name not in FILESYSTEM_TOOLS:
        return await handler(request)

    try:
        return await handler(request)
    except PERMISSION_ERRORS as exc:  # type: ignore[misc]
        tool_call_id = request.tool_call.get("id")
        if logger.isEnabledFor(logging.DEBUG):
            # F-string avoids double %-formatting errors in logging.
            logger.debug(f"Permission error in {tool_name}: {exc}")
        message = (
            f"[Permission denied] {tool_name} could not access the requested resource. "
            "The path is protected or requires elevated permissions."
        )
        return ToolMessage(content=message, tool_call_id=tool_call_id, name=tool_name)
