"""Graph export for LangGraph server deployment.

This module exports the Deep Agent graph for use with `langgraph dev` and LangGraph Server.
It creates the agent WITHOUT custom checkpointer/store since LangGraph server handles persistence.

Usage:
    langgraph dev  # Starts local server with Studio UI at http://localhost:2024
"""

import os
from pathlib import Path

from deepagents_cli._bootstrap import ensure_workspace_on_path

ensure_workspace_on_path()


from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from langchain.agents.middleware import HostExecutionPolicy
from langchain_anthropic import ChatAnthropic

from deepagents_cli.agent_memory import AgentMemoryMiddleware
from deepagents_cli.config import settings
from deepagents_cli.middleware_stack import build_handoff_middleware_stack
from deepagents_cli.resumable_shell_async import AsyncResumableShellToolMiddleware
from deepagents_cli.tools import http_request, tavily_client, web_search


def _get_default_model():
    """Get the default model for the agent."""
    return ChatAnthropic(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        temperature=0,
        timeout=60,
        max_retries=2,
    )


def _get_default_tools():
    """Get the default tools for the agent (same as CLI)."""
    tools = [http_request]
    if tavily_client is not None:
        tools.append(web_search)
    return tools


def _get_system_prompt() -> str:
    """Get system prompt for server deployment."""
    # Simplified version - for full prompts, use CLI
    return """You are a helpful coding assistant with access to file operations, shell commands, and web search.

### Tool Usage - CRITICAL

**ALWAYS provide ALL required parameters when calling tools.**
- Check the tool schema carefully before making a call
- Do NOT leave required fields empty or missing
- If you don't have all the information needed, ask the user first
- Example: `write_file` REQUIRES both `file_path` AND `content` - never call it with just one

Malformed tool calls will cause execution errors and interrupt your work."""


# Create the graph for LangGraph server
# NOTE: LangGraph server provides its own checkpointer and store
# We do NOT pass custom checkpointer/store here
model = _get_default_model()
tools = _get_default_tools()

# Set up middleware (same as CLI)
shell_middleware = AsyncResumableShellToolMiddleware(
    workspace_root=os.getcwd(), execution_policy=HostExecutionPolicy()
)

# File system backend (for sub-agents to access files)
agent_dir = Path.home() / ".deepagents" / "agent"
agent_dir.mkdir(parents=True, exist_ok=True)

long_term_backend = FilesystemBackend(root_dir=agent_dir, virtual_mode=True)
backend = CompositeBackend(default=FilesystemBackend(), routes={"/memories/": long_term_backend})

agent_middleware = [
    AgentMemoryMiddleware(settings=settings, assistant_id="agent"),
    shell_middleware,
]
agent_middleware.extend(build_handoff_middleware_stack(model))

# Create agent WITHOUT checkpointer/store (server provides these)
# IMPORTANT: LangGraph server v0.4.20 EXPLICITLY REJECTS custom checkpointers
# Error: "Your graph includes a custom checkpointer... will be ignored when deployed"
# This is BY DESIGN - Studio and CLI use separate persistence systems
graph = create_deep_agent(
    model=model,
    system_prompt=_get_system_prompt(),
    tools=tools,
    backend=backend,
    middleware=agent_middleware,
    # NO checkpointer or store - LangGraph server provides these automatically
)
