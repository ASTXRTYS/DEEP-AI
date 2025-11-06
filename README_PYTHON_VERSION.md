# Python Version Requirements

## TL;DR: Use Python 3.11 or 3.12

**Python 3.14 is NOT supported** - Do not use it for this project.

## Why Not Python 3.14?

### Pydantic Incompatibility

Python 3.14 (released Oct 2025) has breaking changes that affect Pydantic 2.12.x:

**Symptom:**
```
pydantic.errors.PydanticUserError: `ls` is not fully defined;
you should define `AnyMessage`, then call `ls.model_rebuild()`.
```

**When it happens:**
- Subagent tool invocation
- Checkpoint deserialization
- Any Pydantic validation of TypedDict classes with inheritance chains

**Root cause:**
- LangChain uses `AgentState(TypedDict)` with field types like `AnyMessage`
- Subclasses like `FilesystemState(AgentState)` inherit these fields
- Pydantic 2.12.3 + Python 3.14 requires ALL transitive type references to be imported in EVERY file
- This is unmaintainable - inheritance chains can be deep and change over time

### LangChain Core Warning

You'll also see:
```
UserWarning: Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.
```

LangChain Core uses `pydantic.v1` compatibility layer for backward compatibility. This layer explicitly does not support Python 3.14.

## Supported Versions

**Tested and working:**
- ✅ Python 3.11.x
- ✅ Python 3.12.x

**Not supported:**
- ❌ Python 3.14.x (Pydantic incompatibility)
- ❌ Python 3.10.x (missing typing features used by dependencies)

## Migration From Python 3.14

If you're currently using Python 3.14:

### 1. Remove Current venv

```bash
cd /Users/Jason/astxrtys/DevTools/deepagents
rm -rf .venv
```

### 2. Install Python 3.11 (via Homebrew)

```bash
# If you have 3.14
brew uninstall python@3.14

# Install 3.11
brew install python@3.11
```

### 3. Recreate venv

```bash
# With uv
uv venv --python python3.11

# Or with venv
python3.11 -m venv .venv
```

### 4. Reinstall Dependencies

```bash
# With uv
uv sync --all-groups

# Or with pip
source .venv/bin/activate
cd libs/deepagents-cli
python -m pip install -e . --break-system-packages
cd ../deepagents
python -m pip install -e . --break-system-packages
```

### 5. Verify

```bash
python --version  # Should show 3.11.x
python -c "from deepagents_cli.agent import create_agent_with_config; print('✅ Imports work')"
```

## When Can We Use Python 3.14?

Monitor these before upgrading:

1. **Pydantic 2.13+** - Check release notes for Python 3.14 full support
2. **LangChain Core** - Wait for Pydantic v1 compatibility layer removal
3. **LangGraph** - Verify checkpoint serialization works with Python 3.14

Estimated timeline: Q2-Q3 2025 (6-9 months from now)

## Why This Matters

The checkpoint deserialization issue is **silent until it breaks:**
- Agent creation works fine
- Main agent tool calls work fine
- Only **subagent invocations** or **checkpoint resumption** fail
- Failures happen deep in async execution paths
- Error messages are cryptic (`AnyMessage` not defined)

This makes Python 3.14 particularly dangerous - it fails in production scenarios, not during development.

## Questions?

If you see Pydantic validation errors:
1. Check `python --version` first
2. If it's 3.14, follow migration steps above
3. If it's 3.11/3.12, file an issue with full traceback

---

**Last Updated**: 2025-01-06
**Python 3.14 Release**: 2025-10-07
**Pydantic Version**: 2.12.3
