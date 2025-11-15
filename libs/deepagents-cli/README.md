# deepagents cli

This is the CLI for deepagents

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
