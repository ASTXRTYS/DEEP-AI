"""Graph export for LangGraph server deployment.

This module exports the Deep Agent graph for use with `langgraph dev` and LangGraph Server.
It reuses the exact same agent creation logic as the CLI, ensuring consistency.

Usage:
    langgraph dev  # Starts local server with Studio UI at http://localhost:2024
"""

from langchain_anthropic import ChatAnthropic

from deepagents_cli.agent import create_agent_with_config
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


# Create the graph using the CLI's agent creation logic
# This ensures the LangGraph server runs the EXACT same agent as the CLI
model = _get_default_model()
tools = _get_default_tools()

# Use "agent" as the default assistant ID for the server
# This creates the agent with all the same configuration:
# - Persistent checkpointing (SqliteSaver)
# - Long-term memory (PostgresStore)
# - All middleware and tools
graph = create_agent_with_config(
    model=model,
    assistant_id="agent",
    tools=tools,
)
