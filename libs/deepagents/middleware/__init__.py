"""Middleware for the DeepAgent."""

from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.filesystem_permission import handle_filesystem_permissions
from deepagents.middleware.handoff_approval import HandoffApprovalMiddleware
from deepagents.middleware.handoff_summarization import HandoffSummarizationMiddleware
from deepagents.middleware.prompt_cache import SafeAnthropicPromptCachingMiddleware
from deepagents.middleware.resumable_shell import ResumableShellToolMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware

__all__ = [
    "CompiledSubAgent",
    "FilesystemMiddleware",
    "HandoffApprovalMiddleware",
    "HandoffSummarizationMiddleware",
    "SafeAnthropicPromptCachingMiddleware",
    "handle_filesystem_permissions",
    "ResumableShellToolMiddleware",
    "SubAgent",
    "SubAgentMiddleware",
]
