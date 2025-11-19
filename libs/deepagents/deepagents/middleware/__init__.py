"""Middleware for the DeepAgent."""

from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.handoff_approval import HandoffApprovalMiddleware
from deepagents.middleware.handoff_cleanup import HandoffCleanupMiddleware
from deepagents.middleware.handoff_summarization import HandoffSummarizationMiddleware
from deepagents.middleware.handoff_tool import HandoffToolMiddleware, request_handoff
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware

__all__ = [
    "CompiledSubAgent",
    "FilesystemMiddleware",
    "SubAgent",
    "SubAgentMiddleware",
    # Local handoff extensions (tool -> summary -> cleanup). Approval middleware is deprecated but exported for compatibility.
    "HandoffToolMiddleware",
    "request_handoff",
    "HandoffSummarizationMiddleware",
    "HandoffCleanupMiddleware",
    "HandoffApprovalMiddleware",
]
