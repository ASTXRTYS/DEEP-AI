"""Async-friendly shell middleware tweaks for LangGraph dev server."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

from deepagents.middleware.resumable_shell import ResumableShellToolMiddleware
from langchain.agents.middleware.shell_tool import (
    _PersistentShellTool,
    _SessionResources,
)
from langchain.agents.middleware.types import AgentState
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command


class AsyncResumableShellToolMiddleware(ResumableShellToolMiddleware):
    """Wrap shell middleware so async LangGraph runs avoid blocking calls."""

    def before_agent(self, state, runtime):  # type: ignore[override]
        """Skip eager shell setup to avoid blocking in async environments."""
        return state

    async def abefore_agent(self, state, runtime):  # type: ignore[override]
        """Async variant also skips eager setup."""
        return state

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if isinstance(request.tool, _PersistentShellTool):
            resources = await self._aget_or_create_resources(request.state)
            return await asyncio.to_thread(
                self._run_shell_tool,
                resources,
                request.tool_call["args"],
                tool_call_id=request.tool_call.get("id"),
            )
        return await super().awrap_tool_call(request, handler)

    async def _aget_or_create_resources(
        self, state: AgentState
    ) -> _SessionResources:
        resources = state.get("shell_session_resources")
        if isinstance(resources, _SessionResources):
            return resources

        new_resources = await asyncio.to_thread(self._create_resources)
        cast("dict[str, Any]", state)["shell_session_resources"] = new_resources
        return new_resources
