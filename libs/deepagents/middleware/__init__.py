"""Middleware for the DeepAgent."""

from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.filesystem_permission import handle_filesystem_permissions
from deepagents.middleware.handoff_approval import HandoffApprovalMiddleware
from deepagents.middleware.handoff_cleanup import HandoffCleanupMiddleware
from deepagents.middleware.handoff_summarization import (
    HandoffSummary,
    HandoffSummarizationMiddleware,
    generate_handoff_summary,
)
from deepagents.middleware.handoff_tool import HandoffToolMiddleware, request_handoff
from deepagents.middleware.prompt_cache import SafeAnthropicPromptCachingMiddleware
from deepagents.middleware.resumable_shell import ResumableShellToolMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware

__all__ = [
    "CompiledSubAgent",
    "FilesystemMiddleware",
    "HandoffApprovalMiddleware",
    "HandoffCleanupMiddleware",
    "HandoffSummary",
    "HandoffSummarizationMiddleware",
    "HandoffToolMiddleware",
    "SafeAnthropicPromptCachingMiddleware",
    "generate_handoff_summary",
    "handle_filesystem_permissions",
    "request_handoff",
    "ResumableShellToolMiddleware",
    "SubAgent",
    "SubAgentMiddleware",
]
