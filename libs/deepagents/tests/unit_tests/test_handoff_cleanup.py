from types import SimpleNamespace

from deepagents.middleware.handoff_cleanup import HandoffCleanupMiddleware


def _runtime_for(handoff_block):
    return SimpleNamespace(config={"metadata": {"handoff": handoff_block}})


def test_cleanup_middleware_sets_flag_once():
    middleware = HandoffCleanupMiddleware()
    state: dict[str, object] = {}
    runtime = _runtime_for({"pending": True, "cleanup_required": True})

    update = middleware.after_agent(state, runtime)
    assert update == {"_handoff_cleanup_pending": True, "_handoff_cleanup_done": True}

    state.update(update)
    assert middleware.after_agent(state, runtime) is None


def test_cleanup_middleware_ignores_non_pending_threads():
    middleware = HandoffCleanupMiddleware()

    assert (
        middleware.after_agent({}, _runtime_for({"pending": False, "cleanup_required": True}))
        is None
    )
    assert (
        middleware.after_agent({}, _runtime_for({"pending": True, "cleanup_required": False}))
        is None
    )
    assert middleware.after_agent({}, SimpleNamespace(config={"metadata": {}})) is None
