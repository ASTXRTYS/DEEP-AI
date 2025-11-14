"""Guarded prompt caching middleware for Anthropic models."""

from __future__ import annotations

from langchain.agents.middleware.types import ModelRequest
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import BaseMessage
from langchain_core.runnables.config import get_callback_manager_for_config


def _message_has_content(message: BaseMessage) -> bool:
    """Return True if the message has at least one content chunk."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return bool(content)
    return content is not None


class SafeAnthropicPromptCachingMiddleware(AnthropicPromptCachingMiddleware):
    """Anthropic prompt caching middleware that skips empty-tail requests.

    Anthropic requires the final assistant message to contain at least one content block
    when cache control metadata is attached. LangChain allows an empty final assistant
    message (e.g., after tool handoffs), which would trigger an IndexError inside the
    Anthropic SDK when cache control is applied. This subclass simply skips prompt
    caching for such requests to avoid the crash.
    """

    def _last_message_has_content(self, request: ModelRequest) -> bool:
        if not request.messages:
            return False
        last_message = request.messages[-1]
        return _message_has_content(last_message)

    def _should_apply_caching(self, request: ModelRequest) -> bool:  # type: ignore[override]
        if not super()._should_apply_caching(request):
            try:
                cb = get_callback_manager_for_config(getattr(request.runtime, "config", {}))
                if cb:
                    cb.add_metadata({"prompt_cache.applied": False, "prompt_cache.reason": "super_disallowed"}, inherit=False)
            except Exception:
                pass
            return False

        # Only applies to Anthropic chat models; defensive double-check.
        if not isinstance(request.model, ChatAnthropic):
            try:
                cb = get_callback_manager_for_config(getattr(request.runtime, "config", {}))
                if cb:
                    cb.add_metadata({"prompt_cache.applied": False, "prompt_cache.reason": "not_anthropic"}, inherit=False)
            except Exception:
                pass
            return False

        if not self._last_message_has_content(request):
            try:
                cb = get_callback_manager_for_config(getattr(request.runtime, "config", {}))
                if cb:
                    cb.add_metadata({"prompt_cache.applied": False, "prompt_cache.reason": "empty_tail"}, inherit=False)
            except Exception:
                pass
            return False

        # Skip caching entirely for handoff-triggered runs to avoid Anthropic crashes.
        config = getattr(request.runtime, "config", {}) or {}
        configurable = dict(config.get("configurable") or {})
        metadata = dict(config.get("metadata") or {})
        if configurable.get("handoff_requested") or metadata.get("handoff_requested"):
            try:
                cb = get_callback_manager_for_config(getattr(request.runtime, "config", {}))
                if cb:
                    cb.add_metadata({"prompt_cache.applied": False, "prompt_cache.reason": "handoff"}, inherit=False)
            except Exception:
                pass
            return False

        try:
            cb = get_callback_manager_for_config(getattr(request.runtime, "config", {}))
            if cb:
                cb.add_metadata({"prompt_cache.applied": True}, inherit=False)
        except Exception:
            pass
        return True

    def _apply_cache_control(self, request: ModelRequest) -> None:  # type: ignore[override]
        if not self._last_message_has_content(request):
            return
        super()._apply_cache_control(request)
