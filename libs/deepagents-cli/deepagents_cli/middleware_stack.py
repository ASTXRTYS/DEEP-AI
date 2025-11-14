"""Shared helpers for constructing CLI middleware stacks."""

from __future__ import annotations

import inspect
from typing import Any, Type, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel

from deepagents.middleware.handoff_cleanup import HandoffCleanupMiddleware
from deepagents.middleware.handoff_summarization import HandoffSummarizationMiddleware
from deepagents.middleware.handoff_tool import HandoffToolMiddleware


def instantiate_middleware(cls: Type[Any], **kwargs: Any) -> Any:
    """Instantiate middleware, filtering kwargs to those accepted by __init__."""

    try:
        params = list(inspect.signature(cls.__init__).parameters.values())[1:]
    except (TypeError, ValueError):
        return cls(**kwargs)

    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params)
    if accepts_kwargs:
        return cls(**kwargs)

    accepted = {
        param.name
        for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    filtered_kwargs = {key: value for key, value in kwargs.items() if key in accepted}
    return cls(**filtered_kwargs)


def build_handoff_middleware_stack(model: BaseChatModel | str) -> list[AgentMiddleware]:
    """Return the consistent HITL middleware stack for CLI + server deployments."""

    return [
        cast(AgentMiddleware, instantiate_middleware(HandoffToolMiddleware)),
        cast(
            AgentMiddleware,
            instantiate_middleware(HandoffSummarizationMiddleware, model=model),
        ),
        cast(AgentMiddleware, instantiate_middleware(HandoffCleanupMiddleware)),
    ]


__all__ = ["build_handoff_middleware_stack", "instantiate_middleware"]
