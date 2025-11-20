# deepagents cli

This is the CLI for deepagents

## Usage

```bash
# Start the default agent
deepagents

# Start a specific agent (uses ~/.deepagents/my-agent/)
deepagents --agent my-agent

# Enable auto-approval for all tools (no Human-in-the-Loop)
deepagents --auto-approve

# Run code in a remote sandbox (keeps your local machine safe)
deepagents --sandbox modal
deepagents --sandbox daytona
deepagents --sandbox runloop
```

## Interactive Commands

The CLI supports several slash commands to manage your session:

- **/threads** - Manage conversation threads
  - `/threads list` - Show all threads with token usage and trace stats
  - `/threads switch <id>` - Switch to a different conversation history
  - `/threads rename <id> <name>` - Rename a thread for better organization
  - `/threads delete <id>` - Delete a thread (use `--force` to skip confirmation)
  - `/threads info <id>` - View detailed metadata for a thread

- **/handoff** - Summarize and start fresh
  - Creates a high-quality summary of the current conversation
  - Persists the summary to memory
  - Switches to a new, clean thread with the summary injected
  - Usage: `/handoff` or `/handoff --preview` to review first

- **/clear** - Clear the terminal screen
- **/quit**, **/exit** - Exit the CLI
- **!cmd** - Run a bash command directly (e.g., `!ls -la`)

## Memory & Configuration Structure

The CLI uses a dual-scope memory system with both **global** (per-agent) and **project-specific** configuration:

### Global Configuration

Each agent has its own global configuration directory at `~/.deepagents/<agent_name>/`:

```
~/.deepagents/<agent_name>/
  ├── agent.md              # Auto-loaded global personality/style
  ├── skills/               # Auto-loaded agent-specific skills
  │   ├── web-research/
  │   │   └── SKILL.md
  │   └── langgraph-docs/
  │       └── SKILL.md
```

- **agent.md**: Defines your agent's personality, style, and general instructions (applies to all projects)
- **skills/**: Reusable capabilities that can be invoked across any project

### Project-Specific Configuration

Projects can override or extend the global configuration with project-specific instructions:

```
my-project/
  ├── .git/
  └── .deepagents/
      └── agent.md
```

The CLI automatically detects project roots (via `.git`) and loads project-specific `agent.md` from `[project-root]/.deepagents/agent.md`.

Both global and project agent.md files are loaded together, allowing you to:
- Keep general coding style/preferences in global agent.md
- Add project-specific context, conventions, or guidelines in project agent.md

### How the System Prompt is Constructed

The CLI uses a middleware stack to dynamically construct the system prompt on each model call:

1. **AgentMemoryMiddleware**:
   - **Prepends** the contents of both agent.md files (`<user_memory>` and `<project_memory>`)
   - **Appends** memory management instructions

2. **SkillsMiddleware**:
   - **Appends** list of available skills (name + description)
   - **Appends** progressive disclosure instructions (how to read full SKILL.md when needed)

3. **Handoff & Shell Middleware**:
   - **HandoffMiddleware**: Manages conversation summarization and state persistence
   - **ShellMiddleware**: Provides safe filesystem and shell access (local or sandboxed)

4. **Base System Prompt**:
   - **Current Working Directory**: Context about the environment (local vs. sandbox)
   - **Skills Directory**: Where to find skill scripts
   - **Human-in-the-Loop Guidance**: Protocols for tool approval/rejection
   - **Web Search Usage**: Best practices for synthesis and citation
   - **Todo List Management**: Rules for maintaining a focused task list

**Final prompt structure:**
```
<user_memory>...</user_memory>
<project_memory>...</project_memory>

[Base system prompt: CWD, Skills Path, HITL, Search, Todos]

[Memory management instructions]

[Skills list + progressive disclosure instructions]
```

This approach ensures that agent.md contents are always loaded, while skills use progressive disclosure (metadata shown, full instructions read on-demand).

## Skills

Skills are reusable agent capabilities that can be loaded into the CLI. Each agent has its own skills directory at `~/.deepagents/{AGENT_NAME}/skills/`.

For the default agent (named `agent`), skills are stored in `~/.deepagents/agent/skills/`.

### Example Skills

Example skills are provided in the `examples/skills/` directory:

- **web-research** - Structured web research workflow with planning, parallel delegation, and synthesis
- **langgraph-docs** - LangGraph documentation lookup and guidance

To use an example skill with the default agent, copy it to your agent's skills directory:

```bash
mkdir -p ~/.deepagents/agent/skills
cp -r examples/skills/web-research ~/.deepagents/agent/skills/
```

For a custom agent, replace `agent` with your agent name:

```bash
mkdir -p ~/.deepagents/my-agent/skills
cp -r examples/skills/web-research ~/.deepagents/my-agent/skills/
```

### Managing Skills

```bash
# List available skills
deepagents skills list

# Create a new skill from template
deepagents skills create my-skill

# View detailed information about a skill
deepagents skills info web-research
```

## Development

### CLI UI conventions

- Prompt-toolkit surfaces (REPL, `/threads`, new dialogs) must import the
  shared theme from `deepagents_cli.prompt_theme`. The concrete checklist lives
  in [`STYLEGUIDE.md`](STYLEGUIDE.md). Review it before adding or modifying
  interactive UI so we preserve the current look-and-feel.
- Visual reference screenshots (`CLI-HomePage.JPG`, `CLI-Main-Menu.JPG`,
  `CLI-Thread-Picker.JPG`) are checked into the repo root. Compare against
  them if you change styles or add new menus.

### Running Tests

To run the test suite:

```bash
uv sync --all-groups

make test
```
