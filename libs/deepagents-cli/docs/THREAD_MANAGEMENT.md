# Thread Management Architecture

This document describes the thread management system in deepagents-cli and how it adapts to different deployment modes.

## Overview

The CLI implements a **dual-layer persistence architecture** for thread management:

1. **Metadata Layer**: JSON file (`~/.deepagents/{agent}/threads.json`) storing thread metadata
   - Thread names, timestamps, parent relationships
   - Token counts for context window planning
   - Custom metadata (handoff state, user preferences)
   - Managed by `ThreadManager` + `ThreadStore`

2. **State Layer**: LangGraph checkpointer storing conversation state
   - Message history and graph execution state
   - Managed by LangGraph's `SqliteSaver` or Platform backend

This architecture enables:
- Rich thread metadata (names, timestamps, lineage)
- Local-only operation (SQLite checkpointer)
- Platform deployment (managed Postgres backend)
- Graceful degradation when server unavailable

## Deployment Modes

### Local Mode (SQLite Checkpointer)

**When**: Running CLI without LangGraph Platform server

**Characteristics**:
- Thread IDs: Server-generated UUIDs (via `create_thread_on_server()`)
- Metadata: `threads.json` with file locking for cross-process safety
- State: Local SQLite database (`checkpoints.db`)
- Reconciliation: Required to sync metadata ↔ checkpoint DB
- TTL/Cleanup: Manual methods (`cleanup_old_threads()`, `vacuum_database()`)
- Forking: Manual state copy via `get_state()` / `update_state()`

**Components**:
```python
# ThreadStore provides atomic file operations
ThreadStore(threads.json, file_lock=True)

# ThreadManager coordinates metadata + checkpointer
ThreadManager(agent_dir, assistant_id)
  → create_thread() # Server API → metadata file
  → fork_thread()   # Fallback to manual copy
  → reconcile_with_checkpointer() # Sync metadata ↔ DB
```

**Trade-offs**:
- ✅ Works offline, no external dependencies
- ✅ Simple deployment (single user, local dev)
- ⚠️ File locking overhead (negligible for CLI use)
- ⚠️ Manual reconciliation required
- ⚠️ SQLite scaling limits for high-volume usage

---

### Platform Mode (Managed Backend)

**When**: Deploying with LangGraph Platform server

**Characteristics**:
- Thread IDs: Server-generated UUIDs (via Platform API)
- Metadata: Platform's metadata field (Postgres-backed)
- State: Managed Postgres checkpointer
- Reconciliation: **Not needed** (Platform handles consistency)
- TTL/Cleanup: Platform TTL config (`checkpointer.ttl` in `langgraph.json`)
- Forking: Server API (`threads.copy()`) handles state copy

**Migration Path**:
```python
# Current: Use ThreadManager as-is
# Platform handles concurrency, no file locking needed

# Optimize: Use Platform metadata field instead of threads.json
# (Future enhancement - currently dual-layer for compatibility)
```

**Trade-offs**:
- ✅ Scalable, production-ready persistence
- ✅ Built-in TTL and cleanup
- ✅ No file locking or reconciliation overhead
- ✅ Concurrent access handled by Platform
- ⚠️ Requires Platform server deployment
- ⚠️ Current implementation redundant (file + Platform metadata)

---

## Feature Comparison Matrix

| Feature | Local (SQLite) | Platform (Managed) |
|---------|---------------|-------------------|
| **Thread IDs** | Server-gen UUID | Server-gen UUID |
| **Metadata Storage** | `threads.json` + file lock | Platform metadata field |
| **State Storage** | SQLite (`checkpoints.db`) | Managed Postgres |
| **Reconciliation** | Required (`reconcile_with_checkpointer()`) | Not needed |
| **TTL/Cleanup** | Manual methods | Platform TTL config |
| **Forking** | `get_state()` / `update_state()` fallback | `threads.copy()` API preferred |
| **Concurrency** | File locking | Platform-managed |
| **Scaling** | Single user / local dev | Multi-user / production |
| **Deployment** | No external deps | Requires Platform server |

---

## Thread Lifecycle Operations

### Create Thread

**Local Mode**:
```python
thread_id = create_thread_on_server(name="New conversation")
# Server generates UUID
# Add to threads.json metadata
```

**Platform Mode**:
```python
thread_id = create_thread_on_server(name="New conversation")
# Server generates UUID + stores metadata
# Metadata propagates to Platform backend
```

### Fork Thread

**Local Mode** (Fallback):
```python
# Try server fork first
try:
    new_id = fork_thread_on_server(source_id)
except LangGraphError:
    # Fallback: Manual copy
    new_id = create_thread(name=fork_name)
    state = agent.get_state(source_config)
    agent.update_state(new_config, state.values)
```

**Platform Mode** (Preferred):
```python
# Server handles state copy
new_id = fork_thread_on_server(source_id)
# No manual copy needed
```

### Delete Thread

**Both Modes**:
```python
# Delete from checkpointer
agent.checkpointer.delete_thread(thread_id)

# Remove metadata entry
threads.json.remove(thread_id)
```

### Reconciliation (Local Only)

**When**: Periodically or on startup

**Purpose**: Sync metadata ↔ checkpoint DB
```python
report = thread_manager.reconcile_with_checkpointer(apply=True)
# - Removes stale metadata (no checkpoint)
# - Adds missing metadata (orphaned checkpoints)
```

**Platform Mode**: Not needed (Platform ensures consistency)

---

## Handoff System

The handoff system enables context window management across thread boundaries.

### Components

1. **HandoffToolMiddleware**: Provides `/handoff` tool to agent
2. **HandoffSummarizationMiddleware**: Auto-generates summaries
3. **HandoffCleanupMiddleware**: Clears summary blocks after use
4. **`apply_handoff_acceptance()`**: Persists summary + creates child thread

### Flow

```
User/Agent triggers handoff
  → Generate summary (LLM call)
  → Write to agent.md (<current_thread_summary> block)
  → Create child thread (with parent_id)
  → Update metadata (parent + child handoff state)
  → Switch to child thread
```

### Failure Handling (Transaction-like)

```python
try:
    write_summary_block(agent.md)
    child_id = create_thread(...)
    update_thread_metadata(parent_id, ...)
    update_thread_metadata(child_id, ...)
except Exception:
    # Rollback
    clear_summary_block(agent.md)
    if child_id:
        delete_thread(child_id)
    raise
```

---

## Monitoring Metrics

Use `ThreadManager.get_health_metrics()` for operational insights:

```python
metrics = thread_manager.get_health_metrics(active_days=7)

# Returns:
{
    "thread_count": 42,           # Total threads
    "active_threads": 15,         # Used within 7 days
    "inactive_threads": 27,       # Not used within 7 days
    "avg_token_count": 28500.5,   # Average context size
    "max_token_count": 95000,     # Largest context
    "db_size_mb": 125.3,          # Checkpoint DB size
    "checkpoint_count": 834       # Total checkpoints
}
```

**Use cases**:
- Capacity planning (DB size growth rate)
- Cleanup strategies (inactive thread ratios)
- Context window planning (token count trends)

---

## Best Practices

### Local Mode
1. Run `reconcile_with_checkpointer()` on startup
2. Schedule periodic cleanup (`cleanup_old_threads()`)
3. Monitor DB size, run `vacuum_database()` when needed
4. Use health metrics to understand usage patterns

### Platform Mode
1. Configure TTL in `langgraph.json`:
   ```json
   {
     "checkpointer": {
       "ttl": {
         "default_ttl": "30d",
         "sweep_interval_minutes": 60
       }
     }
   }
   ```
2. Use Platform metadata field for custom attributes
3. Rely on server fork API (automatic state copy)
4. Monitor Platform metrics dashboard

### Both Modes
1. Store `token_count` in metadata for quick access
2. Use `parent_id` for thread lineage tracking
3. Implement handoff for context window management
4. Log handoff operations for debugging

---

## Future Enhancements

### Migration to Platform-First
When Platform is available, optimize the dual-layer approach:

1. **Use Platform metadata field** instead of `threads.json`
   - Eliminates file locking overhead
   - Single source of truth
   - Better concurrency

2. **Remove reconciliation** for Platform mode
   - Platform ensures consistency
   - Reduces operational complexity

3. **Keep local fallback** for compatibility
   - Graceful degradation
   - Local development workflow

### Implementation Strategy
```python
# Detect deployment mode
if is_platform_available():
    # Use Platform metadata field
    metadata_backend = PlatformMetadataBackend()
else:
    # Use threads.json fallback
    metadata_backend = FileMetadataBackend(threads.json)

# ThreadManager adapts to backend
ThreadManager(metadata_backend, checkpointer)
```

---

## References

- [LangGraph Threading Docs](https://langchain-ai.github.io/langgraph/concepts/low_level/#threads)
- [LangGraph Platform Persistence](https://langchain-ai.github.io/langgraph/cloud/concepts/deployment/#persistence)
- [ThreadManager Implementation](../deepagents_cli/thread_manager.py)
- [Handoff System](../deepagents_cli/handoff_persistence.py)
