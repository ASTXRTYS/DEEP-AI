"""Internal compatibility shims for deepagents-cli.

Temporary implementations until functionality is released in langchain upstream.
"""

from langchain.agents.middleware.shell_tool import ShellToolMiddleware

# LangChain ShellToolMiddleware now includes HITL resumability via _get_or_create_resources()
# No need for custom implementation - the functionality has been upstreamed
ResumableShellToolMiddleware = ShellToolMiddleware

__all__ = ["ResumableShellToolMiddleware"]
