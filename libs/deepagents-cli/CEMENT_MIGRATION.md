# Migration to Cement + Rich CLI Framework

## Overview

The DeepAgents CLI has been migrated from Questionary-based interactive menus to a Cement + Rich architecture. This document explains the changes, benefits, and new features.

## What Changed?

### Before (Questionary)
- **Arrow-key navigation**: Interactive menus with up/down arrow keys
- **Procedural flow**: Sequential prompt-based interaction
- **Limited structure**: Menu logic mixed with business logic

### After (Cement + Rich)
- **Numbered selection**: Type numbers to select menu options
- **Controller-based architecture**: Structured, testable, maintainable code
- **Enhanced visuals**: Beautiful Rich panels, tables, and styling
- **Cement framework**: Industry-standard CLI application structure

## New Architecture

### Core Components

```
deepagents_cli/
├── cement_main.py           # Main Cement App and entry point
├── cement_interactive.py    # Interactive REPL loop
├── cement_menu_system.py    # Menu system with numbered selection
├── rich_ui.py              # Rich UI components and utilities
├── main.py                  # Legacy entry point (preserved)
└── menu_system/            # Original Questionary system (preserved)
```

### Entry Points

The CLI now provides multiple entry points:

1. **Default (Cement-based)**: `deepagents` or `deepagents-cli`
   - Uses the new Cement + Rich architecture
   - Enhanced visual presentation
   - Numbered menu selection

2. **Legacy (Questionary-based)**: Access via `cli_main_legacy` (if needed)
   - Original arrow-key navigation
   - Preserved for compatibility testing

## Key Features

### 1. **Cement Framework Integration**

The app now uses Cement's structured architecture:

```python
from cement import App, Controller, ex

class BaseController(Controller):
    @ex(help="list all agents")
    def list(self):
        # Implementation
        pass
```

**Benefits:**
- Clear command structure
- Built-in help generation
- Extensible architecture
- Industry-standard patterns

### 2. **Enhanced Rich UI Components**

Beautiful terminal interfaces with:

#### Rich Panels
```python
from rich.panel import Panel
panel = Panel(
    "Content here",
    title="[bold]Title[/bold]",
    border_style="cyan"
)
```

#### Thread Tables
Comprehensive thread listings with:
- Thread IDs and names
- Message counts
- Token usage
- Active status indicators

#### Syntax Highlighting
Code snippets with beautiful syntax highlighting:
```python
syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
```

#### Progress Bars
Real-time progress tracking for long operations

### 3. **Numbered Menu System**

Menus now use numbered selection:

```
🤖 DEEP AGENTS - Main Menu
What would you like to do?

 1. 🧵  Thread Management    Browse and manage conversation threads
 2. 🚀  New Thread          Start a fresh conversation
 3. 📊  Token Statistics    View usage and cost information
 4. ⚙️   Settings            Configure CLI preferences
 5. ❓  Help & Commands     Show available commands
 6. 🚪  Exit                Quit the application

Type the number and press Enter • Ctrl+C to cancel

Select an option:
```

**How to use:**
- Type the number of your choice
- Press Enter to confirm
- Press Ctrl+C to cancel and return

### 4. **Improved Visual Design**

#### ASCII Banner
Displays the DeepAgents logo on startup

#### Status Indicators
- 🟢 Connected to LangGraph server
- 🔴 Not connected to LangGraph server
- ⚠️  Warning messages
- ✓ Success indicators

#### Color-Coded Output
- Primary actions: Cyan
- Success messages: Green
- Warnings: Yellow
- Errors: Red
- System info: Dim

## Usage Examples

### Starting the CLI

```bash
# Using the new Cement-based CLI (default)
deepagents

# With options
deepagents --agent myagent --auto-approve

# Show help
deepagents --help

# List agents
deepagents list

# Reset an agent
deepagents reset --agent myagent
```

### Interactive Mode

Once started:

1. **Main prompt**: Type your coding requests naturally
2. **Menu system**: Press `Ctrl+M` to open the menu
3. **Slash commands**: Use `/help`, `/threads`, etc.
4. **Bash execution**: Use `!command` for bash commands
5. **Exit**: Type `quit`, `exit`, or press `Ctrl+C`

### Menu Navigation

1. **Read the options**: Each numbered item shows its purpose
2. **Type the number**: Enter the number for your choice
3. **Press Enter**: Confirm your selection
4. **Cancel anytime**: Press `Ctrl+C` to go back

## Benefits of the Migration

### 1. **Better Code Organization**
- Clear separation of concerns
- Controller-based architecture
- Testable components
- Reusable utilities

### 2. **Enhanced User Experience**
- Beautiful Rich formatting
- Clear visual hierarchy
- Progress indicators
- Syntax highlighting

### 3. **Easier Maintenance**
- Structured codebase
- Standard patterns
- Documented architecture
- Extensible design

### 4. **Future-Proof**
- Industry-standard framework
- Active community support
- Rich ecosystem of extensions
- Easy to add new features

## Technical Details

### Cement Prompt Integration

The `RichPrompt` class bridges Cement's shell utilities with Rich's beautiful output:

```python
from cement.utils import shell
from rich.panel import Panel

class RichPrompt:
    def menu(self, title, options, subtitle=None):
        # Display Rich panel
        panel = Panel(content, title=title, border_style="cyan")
        console.print(panel)

        # Use Cement's numbered prompt
        prompt = shell.Prompt(
            "Select an option",
            options=option_labels,
            numbered=True,
            max_attempts=5
        )

        return prompt.input
```

### Async Support

The CLI maintains full async support:

```python
async def start_interactive_mode(assistant_id, session_state):
    async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as checkpointer:
        agent = create_agent_with_config(model, assistant_id, tools, checkpointer)
        await simple_cli_loop(agent, assistant_id, session_state, baseline_tokens)
```

### State Management

Session state flows through the application:

```python
class SessionState:
    auto_approve: bool
    menu_requested: bool
    thread_manager: ThreadManager
    model: BaseChatModel
    pending_handoff_child_id: str | None
```

## Migration Checklist

If you're updating from the Questionary version:

- [x] Cement framework added to dependencies
- [x] Rich UI components enhanced with panels and tables
- [x] Numbered menu system implemented
- [x] Legacy Questionary code preserved for compatibility
- [x] Entry point updated to use Cement by default
- [x] Documentation updated
- [ ] Tests updated for new architecture
- [ ] User feedback collected

## Troubleshooting

### "Missing required CLI dependencies: cement"

**Solution**: Install cement:
```bash
pip install cement
# or
pip install 'deepagents[cli]' cement
```

### Menus look broken or garbled

**Solution**: Ensure your terminal supports UTF-8 and colors:
```bash
export LANG=en_US.UTF-8
export TERM=xterm-256color
```

### Want to use arrow-key menus again?

The original Questionary-based menu system is preserved in the codebase. You can access it programmatically:

```python
from deepagents_cli import cli_main_legacy
cli_main_legacy()
```

## Future Enhancements

Potential improvements enabled by this architecture:

1. **Plugin System**: Cement's extension mechanism for custom tools
2. **Configuration Files**: YAML/JSON config support via Cement
3. **Custom Controllers**: Easy to add new command groups
4. **Rich Themes**: Customizable color schemes
5. **Advanced Tables**: Sortable, filterable thread views
6. **Progress Tracking**: Real-time agent execution visualization
7. **Export Functionality**: Save conversations to markdown/HTML with Rich

## Contributing

When adding new features:

1. **Create a new controller** for major feature groups
2. **Add Rich components** in `rich_ui.py` for reusability
3. **Use numbered menus** for consistency
4. **Follow Cement patterns** for command structure
5. **Document with examples** in docstrings

## Resources

- [Cement Documentation](https://docs.builtoncement.com/)
- [Rich Documentation](https://rich.readthedocs.io/)
- [DeepAgents Documentation](https://github.com/langchain-ai/deepagents)

## Questions?

For issues or questions about the new CLI:

1. Check this migration guide
2. Review the code examples in `cement_main.py` and `rich_ui.py`
3. Open an issue on GitHub with the `cement-migration` label
