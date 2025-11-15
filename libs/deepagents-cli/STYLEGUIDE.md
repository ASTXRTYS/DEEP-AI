# DeepAgents CLI Style Guide

This short guide documents the prompt-toolkit and Rich styling conventions for
`deepagents-cli`. The goal is to ensure every interactive surface (REPL,
menus, slash-command dialogs) uses the same palette and UX affordances.

## Prompt toolkit

- **Shared Style:** Always import `BASE_PROMPT_STYLE` or
  `build_thread_prompt_style()` from `deepagents_cli.prompt_theme`. Do not
  construct ad-hoc `Style` objects inside prompts. This keeps the prompt glyph,
  toolbar bands, and completion menus consistent.
- **Toolbar conventions:** Use `get_bottom_toolbar()` from `input.py` for the
  main REPL and the `threads-menu.*` classes defined in `prompt_theme.py` for
  specialized dialogs. If a new dialog needs custom hints, add named classes to
  `prompt_theme.py` rather than inline style strings.
- **Completions:** Prefer `CompleteStyle.MULTI_COLUMN` with
  `FormattedText` entries for display + `display_meta` so we can show multi-line
  previews, stats, or shortcuts that match the palette.
- **Threads dashboard:** The `/threads` selector reuses the main slash-command
  menu palette for its preview band (`threads-menu.meta-header` /
  `threads-menu.meta-footer`) and a dedicated bottom toolbar band via
  `build_thread_prompt_style()`. When tweaking colors, keep those three layers
  (grid, preview, toolbar) visually cohesive and aligned with the base
  completion-menu colors.
- **Prompt sessions:** Reuse an existing `PromptSession` when possible. When a
  dedicated session is necessary, instantiate it with the shared style module
  and reuse the same key bindings/toolbar semantics.

## Rich components

- Panels, tables, and menus should use helpers in
  `deepagents_cli.ui_components` or the styles defined in
  `deepagents_cli.menu_system.styles`. Adding new colors? Extend the centralized
  constants in `ui_constants.py` or `prompt_theme.py` instead of introducing
  raw color literals.

## Screenshot reference

The expected look for the CLI home screen, main command menu, and `/threads`
selector is captured in the root-level screenshots:

- `CLI-HomePage.JPG` – landing state after connecting to the LangGraph server.
- `CLI-Main-Menu.JPG` – slash-command menu (`/help`, `/new`, etc.).
- `CLI-Thread-Picker.JPG` – interactive thread selector with preview band.

Use these as visual QA when introducing new UI or tweaking styles.

## Checklist for new UI code

1. Import the shared style from `prompt_theme.py`.
2. Route toolbar hints through named classes (no inline `bg:#...`).
3. Keep completion previews multi-line friendly via `FormattedText`.
4. Reference this guide in PRs when adding CLI UI changes.

Following this checklist ensures future enhancements inherit the same polished
experience instead of reinventing the wheel.
