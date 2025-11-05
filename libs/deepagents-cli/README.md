# DeepAgents CLI

AI coding assistant powered by Claude Sonnet 4.5 with persistent memory, file operations, and web search.

## Quick Start

### 1. Install
```bash
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

### 2. Configure Environment
Create `.env` file with your API keys:
```bash
cp .env.example .env  # If example exists, otherwise create new .env
```

Required in `.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
TAVILY_API_KEY=tvly-dev-...  # Optional - for web search
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=deepagents-cli
DEEPAGENTS_DATABASE_URL=postgresql://localhost/deepagents
```

### 3. Setup PostgreSQL
```bash
# Start PostgreSQL
brew services start postgresql@14

# Create database
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents
```

### 4. Run

#### Option A: CLI Only
```bash
deepagents
```

#### Option B: With Studio Debugging
```bash
# Terminal 1: Start LangGraph dev server
./start-dev-server.sh

# Terminal 2: Start CLI
deepagents
```

#### Option C: Both Together
```bash
# Starts server in background, then CLI
# Automatically stops server when CLI exits
./start-dev.sh
```

#### Option D: Tmux Split Panes
```bash
# Server on left, CLI on right
./start-tmux.sh
```

## Usage

### Basic Commands
```bash
# Start with default agent
deepagents

# Use specific agent
deepagents --agent myagent

# Auto-approve mode (no prompts)
deepagents --auto-approve

# List all agents
deepagents list

# Reset agent to default
deepagents reset --agent myagent

# Help
deepagents help
```

### In-Session Commands

**General**:
- `/help` - Show help
- `/tokens` - Show token usage
- `/clear` - Clear conversation
- `!command` - Execute shell command
- `quit`, `exit`, `q` - Exit

**Thread Management**:
- `/new [name]` - Create new thread
- `/threads` - List all threads
- `/threads continue <id>` - Switch to thread
- `/threads fork [name]` - Fork current thread
- `/threads info [id]` - Show thread details
- `/threads rename <id> <name>` - Rename thread
- `/threads delete <id>` - Delete thread (with confirmation)
- `/threads cleanup [--days N]` - Delete threads older than N days (default: 30)
- `/threads sync` - Reconcile metadata with checkpoints (recover or prune threads)
- `/threads vacuum` - Reclaim disk space from deleted threads
- `/threads stats` - Show database statistics

### Memory System

The agent has persistent memory across sessions:

**File Memory** (`/memories/` virtual path):
```
Agent: ls /memories/
Agent: write_file /memories/guide.md "content..."
Agent: read_file /memories/guide.md
```

Stored in: `~/.deepagents/{agent_name}/`

**Conversation Memory**: Automatically saved, resume with same agent name

**Long-term Store**: Shared knowledge across all conversations (PostgreSQL)

### Thread Cleanup & Maintenance

**Automatic Cleanup (Server Mode Only)**:
- When running with LangGraph server (`./start-dev.sh`), threads older than 14 days are automatically deleted
- Cleanup runs every 2 hours in the background
- **Note**: Standalone CLI (`deepagents`) does NOT run automatic cleanup

**Manual Cleanup (All Modes)**:
```bash
# Check database size and thread count
/threads stats

# Delete threads older than 30 days
/threads cleanup --days 30

# Reclaim disk space after deletions
/threads vacuum

# Repair metadata if automatic TTL deleted checkpoints
/threads sync
```

**Best Practices**:
- **CLI-only users**: Run `/threads cleanup --days 14` every 1-2 weeks
- **Server users**: Automatic cleanup handles new threads, use `/threads cleanup` for old threads
- Run `/threads vacuum` after bulk deletions to reclaim disk space
- Monitor with `/threads stats` regularly

## LangGraph Studio

Free visual debugging interface:

1. Start server: `./start-dev-server.sh`
2. Open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
3. Execute tasks and see step-by-step execution
4. Inspect state, time-travel debug

## Development

See [CLAUDE.md](CLAUDE.md) for comprehensive technical documentation including:
- Architecture details
- Memory system internals
- Middleware stack
- Known issues & solutions
- Testing checklist

## Troubleshooting

### Server won't start
Check logs and ensure .env exists:
```bash
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
cat .env  # Verify exists and has API keys
langgraph dev  # See full error output
```

### PostgreSQL connection error
```bash
# Check if PostgreSQL is running
brew services list

# Start if needed
brew services start postgresql@14

# Create database if missing
/opt/homebrew/opt/postgresql@14/bin/createdb deepagents
```

### Import errors
Reinstall package:
```bash
cd /Users/Jason/astxrtys/DevTools/deepagents/libs/deepagents-cli
python3.11 -m pip install -e . --break-system-packages
```

### Scripts not executable
```bash
chmod +x start-dev-server.sh start-dev.sh start-tmux.sh
```

## Features

- ✅ Persistent memory (conversations + long-term storage)
- ✅ File operations (read, write, edit, search)
- ✅ Shell command execution with approval
- ✅ Web search (Tavily integration)
- ✅ Subagent spawning for complex tasks
- ✅ Human-in-the-loop approval for sensitive operations
- ✅ Token usage tracking
- ✅ Auto-approve mode for trusted environments
- ✅ Multiple agent profiles
- ✅ LangGraph Studio debugging (free for local server)
- ✅ LangSmith tracing

## Project Structure

```
deepagents-cli/
├── .env                          # Environment variables
├── langgraph.json               # Server config
├── start-dev-server.sh          # Launch server only
├── start-dev.sh                 # Launch server + CLI
├── start-tmux.sh                # Launch in tmux
├── CLAUDE.md                    # Technical docs for AI
├── README.md                    # This file
└── deepagents_cli/
    ├── agent.py                 # Agent creation (shared)
    ├── graph.py                 # Server export
    ├── tools.py                 # Tool definitions
    ├── main.py                  # CLI entry point
    └── ...
```

## License

MIT
