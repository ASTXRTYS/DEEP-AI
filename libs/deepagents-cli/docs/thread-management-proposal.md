# Thread Management Enhancement Proposal

**Date**: 2025-01-11
**Status**: Research & Planning Phase
**Priority**: High (Solves 1M+ token thread issue)
**For**: Future Claude instances working on this feature

---

## Executive Summary

**Problem**: DeepAgents CLI user accumulated 1M+ tokens in a single conversation thread with no way to start fresh while preserving memory files.

**Root Cause**: Static `thread_id = assistant_id` design means same agent name = same thread forever.

**Solution**: Implement Amp-style in-CLI thread management with `/new`, `/threads`, `/threads continue` commands.

**Safety**: Validated safe by LangGraph documentation - thread switching is intended behavior, backward compatible.

**Status**: Research complete, implementation ready to start.

---

## Background: How We Discovered the Issue

### User Report (2025-01-11)
User asked: *"how do i start a new thread? currently ive been in the same thread which is well over 1 million tokens. i even opened a new terminal and started the cli"*

### Investigation Timeline

1. **Initial Discovery**: User's CLI session had grown to 1M+ tokens
2. **Attempted Workaround**: Opening new terminal didn't help - resumed same thread
3. **Code Review**: Found `execution.py:210` uses static thread_id
4. **Git History**: Confirmed we changed from `thread_id="main"` to `thread_id=assistant_id` but forgot rotation
5. **Documentation Error**: CLAUDE.md incorrectly documented format as `{assistant_id}_{timestamp}`

### Original Design Flaw

**Git diff showed**:
```python
# OLD (everyone shared one thread):
config = {"configurable": {"thread_id": "main"}}

# OUR PARTIAL FIX (each agent gets own thread, but still static):
config = {"configurable": {"thread_id": assistant_id or "main"}}
```

We improved from "one thread for everyone" to "one thread per agent", but forgot to add rotation/management.

### Current Behavior
```python
# execution.py:210
config = {"configurable": {"thread_id": assistant_id or "main"}}
```

- Same agent name = same thread forever
- No thread rotation or management
- `/clear` command breaks persistence (replaces checkpointer with InMemorySaver)

---

## Research Summary

### Critical Question We Had to Answer
**"Will changing thread_id dynamically break existing checkpoints or cause data loss?"**

### Research Process (2025-01-11)

1. **Searched LangGraph documentation** for thread_id patterns
2. **Read GitHub discussions** #1454, #1211, #3640 on thread safety
3. **Analyzed LangGraph persistence concepts** documentation
4. **Researched industry examples** (Sourcegraph Amp CLI)
5. **Validated with web search** for production patterns

### Key Findings from LangGraph Documentation

#### 1. Dynamic Thread Switching is SAFE and INTENDED ✅

**Sources**:
- https://langchain-ai.github.io/langgraph/concepts/persistence/
- GitHub Discussion #1454: "Is CompiledStateGraph Thread safe"
- GitHub Discussion #1211: "Is a LangGraph compiled graph thread-safe"

**Key Quotes from Documentation**:
> "The checkpointer is entirely safe to share between executions, whether they happen concurrently or not, because no state is ever stored on the graph instance."

> "Neither the graph nor the checkpointer keep any internal state so using one global instance or a new one per request makes no difference."

**What This Means**:
- Switching `thread_id` in config is the **standard pattern**
- Same checkpointer instance can handle unlimited threads
- Each thread is isolated automatically
- No special cleanup or migration needed

#### 2. Thread Isolation is Automatic ✅

**How It Works**:
```python
# Thread 1
config = {"configurable": {"thread_id": "agent:abc123"}}
graph.invoke(input, config)  # Conversation A

# Thread 2
config = {"configurable": {"thread_id": "agent:def456"}}
graph.invoke(input, config)  # Conversation B (completely separate)

# Back to Thread 1
config = {"configurable": {"thread_id": "agent:abc123"}}
graph.invoke(input, config)  # Resumes Conversation A exactly where it left off
```

**Proof**: checkpoints.db stores entries keyed by thread_id. Switching thread_id = switching conversation.

#### 3. Multiple Threads in Same Database is Standard ✅

**From Research**:
- Production apps use patterns like `tenant-{id}:user-{id}:session-{id}`
- One checkpoints.db can store unlimited threads
- No performance degradation with many threads
- SqliteSaver handles this automatically

#### 4. Memory Architecture Has Two Layers

**Short-term Memory (Checkpointer)**:
- Scope: Per-thread
- Storage: `checkpoints.db` keyed by thread_id
- Purpose: Conversation history, state
- Behavior: Switching thread = switching conversation

**Long-term Memory (Store + /memories/)**:
- Scope: Cross-thread (shared)
- Storage: PostgresStore + `~/.deepagents/{agent}/` files
- Purpose: Knowledge that persists across all conversations
- Behavior: Accessible from ANY thread

**This is the key insight**: Memory files in `/memories/` will work across ALL threads because they're filesystem-based, not thread-scoped!

### Industry Example: Sourcegraph Amp CLI

**Source**: https://ampcode.com/manual

Commands:
```bash
/new                      # Start new thread
/threads                  # List all threads
/threads continue <id>    # Switch to thread
/threads fork             # Branch from current
```

## Proposed Solution

### Amp-Style Thread Management

**New slash commands**:
- `/new` - Create new thread with UUID
- `/threads` - List all threads for current agent
- `/threads continue <id>` - Switch to specific thread
- `/threads fork` - Fork current thread
- `/clear` - Fixed to create new thread (not break persistence)

**Thread ID format**: `{assistant_id}:{uuid_short}`
- Example: `agent:a1b2c3d4`, `dev:f9g0h1i2`
- Follows LangGraph multi-tenant pattern

**Metadata storage**: `~/.deepagents/{agent}/threads.json`

---

## Detailed Implementation Plan

### Thread ID Format

**Pattern**: `{assistant_id}:{uuid_short}`

**Examples**:
- `agent:a1b2c3d4`
- `dev:f9g0h1i2`
- `research:e5f6g7h8`

**Rationale**:
- Follows LangGraph multi-tenant pattern (`tenant:user:session`)
- Agent namespace preserved (can filter in DB)
- UUID ensures uniqueness
- Short UUID (8 chars) is human-readable
- Can match with prefix (e.g., `/threads continue a1b2`)

### Thread Metadata Schema

**File**: `~/.deepagents/{agent}/threads.json`

```json
{
  "threads": {
    "agent:a1b2c3d4": {
      "created_at": "2025-01-11T14:30:22Z",
      "last_used_at": "2025-01-11T16:45:10Z",
      "message_count": 47,
      "total_tokens": 125000,
      "title": "Implementing thread management system"
    },
    "agent:e5f6g7h8": {
      "created_at": "2025-01-10T09:15:33Z",
      "last_used_at": "2025-01-10T18:22:05Z",
      "message_count": 89,
      "total_tokens": 890000,
      "title": "Debugging authentication issues"
    }
  },
  "current_thread": "agent:a1b2c3d4",
  "default_behavior": "continue_last"
}
```

### ThreadManager Class Design

**File**: `deepagents_cli/thread_manager.py`

```python
from pathlib import Path
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

class ThreadManager:
    """Manages thread lifecycle and metadata for an agent."""

    def __init__(self, agent_dir: Path, assistant_id: str):
        self.agent_dir = agent_dir
        self.assistant_id = assistant_id
        self.threads_file = agent_dir / "threads.json"
        self.current_thread_id: Optional[str] = None
        self._load_metadata()

    def create_thread(self, title: Optional[str] = None) -> str:
        """Create new thread with UUID."""
        thread_id = f"{self.assistant_id}:{uuid.uuid4().hex[:8]}"
        self._save_thread_metadata(thread_id, title=title)
        self.current_thread_id = thread_id
        return thread_id

    def list_threads(self) -> List[Dict]:
        """List all threads for this agent."""
        # Return sorted by last_used_at descending

    def switch_thread(self, thread_id: str):
        """Switch to existing thread."""
        if not self._thread_exists(thread_id):
            raise ValueError(f"Thread {thread_id} not found")
        self.current_thread_id = thread_id
        self._update_last_used(thread_id)

    def fork_thread(self, source_thread_id: str) -> str:
        """Create copy of thread state with new UUID."""
        # Uses checkpointer.get_state() to copy state
        new_thread_id = self.create_thread(title=f"Fork of {source_thread_id}")
        # Copy checkpointer state from source to new thread
        return new_thread_id
```

### Phase-by-Phase Implementation

#### Phase 1: Infrastructure (Non-Breaking) ⚡ LOW RISK

**Branch**: `phase-1-infrastructure`

**Files to Create**:
- `deepagents_cli/thread_manager.py` - ThreadManager class
- `deepagents_cli/tests/test_thread_manager.py` - Unit tests

**Files Modified**: NONE (zero risk!)

**Tasks**:
1. Implement ThreadManager class
2. Add comprehensive unit tests
3. Ensure threads.json format is correct
4. Test edge cases (missing file, corrupt JSON, etc.)

**Exit Criteria**:
- [ ] All unit tests pass
- [ ] Can create threads
- [ ] Can list threads
- [ ] Can switch threads
- [ ] Metadata saves/loads correctly
- [ ] NO impact on existing CLI

**Verification**:
```bash
pytest deepagents_cli/tests/test_thread_manager.py -v
# All tests pass
git checkout main
deepagents  # Still works exactly as before
```

#### Phase 2: Commands (Additive) ⚡ LOW RISK

**Branch**: `phase-2-commands`

**Files Modified**:
- `deepagents_cli/commands.py` - Add thread commands
- `deepagents_cli/ui.py` - Add thread display functions
- `deepagents_cli/main.py` - Initialize ThreadManager

**Changes to commands.py**:
```python
def handle_command(command: str, agent, token_tracker, thread_manager) -> str | bool:
    # ...existing commands...

    # NEW: Thread management
    if cmd == "new":
        thread_id = thread_manager.create_thread()
        console.print(f"✨ Created new thread: {thread_id}")
        return True

    if cmd == "threads":
        if len(cmd_parts) == 1:
            display_threads(thread_manager.list_threads(), thread_manager.current_thread_id)
        elif cmd_parts[1] == "continue" and len(cmd_parts) == 3:
            thread_manager.switch_thread(cmd_parts[2])
            console.print(f"↪️  Switched to thread: {cmd_parts[2]}")
        elif cmd_parts[1] == "fork":
            new_id = thread_manager.fork_thread(thread_manager.current_thread_id)
            console.print(f"🔱 Forked to: {new_id}")
        return True
```

**Important**: Commands work but execution.py still uses old thread_id (behavior unchanged yet).

**Exit Criteria**:
- [ ] `/threads` lists threads
- [ ] `/new` creates threads
- [ ] `/threads continue <id>` switches (but doesn't affect conversation yet)
- [ ] Thread metadata updates
- [ ] Existing behavior unchanged
- [ ] Can still rollback to main

#### Phase 3: Integration (Behavior Change) ⚠️ MEDIUM RISK

**Branch**: `phase-3-integration`

**Files Modified**:
- `deepagents_cli/execution.py` - Line 210 (THE CRITICAL CHANGE)
- `deepagents_cli/commands.py` - Fix `/clear` command

**Critical Code Change**:
```python
# OLD (execution.py:210)
config = {"configurable": {"thread_id": assistant_id or "main"}}

# NEW (execution.py:210)
config = {
    "configurable": {
        "thread_id": getattr(thread_manager, "current_thread_id", None) or assistant_id or "main"
    },
    "metadata": {"assistant_id": assistant_id}
}
```

**Fixed `/clear` Command**:
```python
# OLD (commands.py:19-34) - BROKEN
if cmd == "clear":
    agent.checkpointer = InMemorySaver()  # ❌ Breaks persistence!

# NEW - FIXED
if cmd == "clear":
    new_thread_id = thread_manager.create_thread()
    thread_manager.switch_thread(new_thread_id)
    token_tracker.reset()
    console.clear()
    console.print("✨ Started fresh thread!")
    return True
```

**Testing Requirements**:
1. Create new thread, verify conversation resets
2. Switch to old thread, verify conversation resumes
3. Write to `/memories/`, verify accessible from all threads
4. Verify old thread (thread_id="agent") still accessible

**Exit Criteria**:
- [ ] Thread switching actually changes conversation
- [ ] Old threads remain accessible
- [ ] `/memories/` files work across threads
- [ ] `/clear` creates new thread (doesn't break persistence)
- [ ] Graceful fallback if ThreadManager fails

#### Phase 4: Polish (Optional) 🎨

**Branch**: `phase-4-polish`

**Features**:
- Auto-generate thread titles from first message
- Token count warnings (>500K, >1M)
- `/compact` command (summarization)
- Thread search/filter
- Thread export/import
- Thread archival/cleanup

---

## Safety Validation & Testing Strategy

### Git Branching Strategy

```
main (production - always working)
  └── feature/thread-management
       ├── phase-1-infrastructure (ThreadManager class)
       ├── phase-2-commands (Slash commands)
       ├── phase-3-integration (execution.py changes)
       └── phase-4-polish (Optional enhancements)
```

**Workflow**:
1. Create `feature/thread-management` from `main`
2. Create phase branch from feature branch
3. Implement phase, test thoroughly
4. Merge phase back to feature branch
5. Only merge to `main` when fully tested

**Rollback**:
```bash
# At any point, switch back to working version
git checkout main
deepagents  # Works exactly as before
```

### Safety Checklist Before Each Phase Merge

**Before Phase 1**:
- [ ] Unit tests pass
- [ ] No changes to existing files
- [ ] Can switch back to main

**Before Phase 2**:
- [ ] Slash commands work
- [ ] Existing behavior unchanged
- [ ] No errors in logs

**Before Phase 3** (CRITICAL):
- [ ] Backup checkpoints.db: `cp ~/.deepagents/agent/checkpoints.db{,.backup}`
- [ ] Test thread switching with real conversation
- [ ] Verify old thread still accessible
- [ ] Test `/memories/` access from multiple threads
- [ ] Verify no data loss in checkpoints.db
- [ ] Test rollback procedure

**Before Merge to Main**:
- [ ] All phases complete and tested
- [ ] Documentation updated (README.md, CLAUDE.md)
- [ ] User can start fresh thread
- [ ] User can access old 1M+ token thread
- [ ] Memory files work across all threads

### Test Scenarios

**Scenario 1: Fresh Thread Creation**
```bash
deepagents --agent test
> Hello, I'm Alice
Agent: "Hi Alice!"
> /new
> Hello, I'm Bob
Agent: "Hi Bob!"  # Should NOT remember Alice
```

**Scenario 2: Thread Switching**
```bash
> /threads  # Lists: thread1 (Alice), thread2 (Bob)
> /threads continue {thread1}
> What's my name?
Agent: "Alice!"  # ✅ Remembers correctly
```

**Scenario 3: Memory Persistence Across Threads**
```bash
> /new  # Thread 3
> write_file /memories/test.md "Hello from thread 3"
> /new  # Thread 4
> read_file /memories/test.md
Agent shows: "Hello from thread 3"  # ✅ Cross-thread memory works
```

**Scenario 4: Fixed `/clear` Command**
```bash
> /clear
# Creates new thread, resets conversation
> Hello
Agent: Greets as if first interaction  # ✅ Fresh start
> /threads
# Shows old threads still exist  # ✅ Persistence maintained
```

**Scenario 5: Old Thread Still Accessible**
```bash
> /threads
# Should see old thread with thread_id="agent"
> /threads continue agent
# Should resume 1M+ token conversation ✅
```

### Monitoring & Validation

**During Implementation**:
```bash
# Check checkpoints.db size (should never decrease!)
ls -lh ~/.deepagents/agent/checkpoints.db

# Verify threads.json format
cat ~/.deepagents/agent/threads.json | python -m json.tool

# Run tests
pytest deepagents_cli/tests/ -v

# Check for errors
tail -f /tmp/deepagents-cli.log  # If we add logging
```

**After Implementation**:
```bash
# Verify user can solve their problem
deepagents
> /new  # ✅ Starts fresh thread
> /threads  # ✅ Can see all threads
> /threads continue {old_id}  # ✅ Can resume old conversation
```

---

## References & Sources

### LangGraph Documentation
- **Persistence**: https://langchain-ai.github.io/langgraph/concepts/persistence/
- **Memory Concepts**: https://docs.langchain.com/oss/python/concepts/memory
- **Threads API**: https://docs.langchain.com/oss/python/langgraph/persistence

### GitHub Discussions
- **#1454**: "Is CompiledStateGraph Thread safe" - Confirms thread safety
- **#1211**: "Is a LangGraph compiled graph thread-safe" - Architecture confirmation
- **#3640**: "How to get all threads" - Thread management patterns
- **#634**: Thread ID and timestamp handling

### Industry Examples
- **Amp CLI Manual**: https://ampcode.com/manual
- **Amp CLI Guide**: https://github.com/sourcegraph/amp-examples-and-guides/blob/main/guides/cli/README.md

### Code References (This Repo)
- `execution.py:210` - Current thread_id logic (needs change)
- `commands.py:19-34` - Broken `/clear` command (needs fix)
- `agent.py:142-305` - Agent creation with checkpointer
- `agent.py:160` - SqliteSaver with `check_same_thread=False` (already thread-safe!)

---

## Summary for Future Claude Instances

**If you're reading this with zero context, here's what you need to know**:

1. **The Problem**: User had 1M+ tokens in single thread, couldn't start fresh
2. **Root Cause**: Static `thread_id = assistant_id` in execution.py:210
3. **The Solution**: Add ThreadManager for Amp-style thread switching
4. **Safety**: Validated safe by LangGraph docs, backward compatible
5. **Implementation**: 3 phases (infra → commands → integration), git branched
6. **Current State**: Research complete, ready to implement Phase 1

**To Continue This Work**:
1. Read this entire document
2. Review CLAUDE.md section on thread management (lines 497-653)
3. Start with Phase 1 on `phase-1-infrastructure` branch
4. Follow exit criteria for each phase
5. Test thoroughly before merging to main

**Critical Files**:
- This proposal: Full context and plan
- CLAUDE.md: Quick reference and current behavior
- execution.py:210: The line that needs changing (Phase 3)
- commands.py: Needs thread commands and fixed `/clear`

**Key Insight**: Thread switching is SAFE and INTENDED by LangGraph. The `/memories/` files will work across ALL threads because they're filesystem-based, not thread-scoped.

---

**Document Status**: Complete and comprehensive
**Last Updated**: 2025-01-11
**Next Action**: Create `feature/thread-management` branch and begin Phase 1
