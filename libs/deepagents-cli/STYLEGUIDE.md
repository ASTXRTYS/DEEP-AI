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

## Creative Branding with Rich

### Advanced Color Gradient Techniques

When creating custom branding elements like banners, menus, or dashboard headers, Rich provides powerful gradient capabilities beyond basic color application.

#### The Gradient Problem: Avoiding Muddy Intermediates

**Mathematical RGB blending creates problems with conflicting color families:**

```python
# This creates muddy browns in the middle ❌
Green RGB(16,185,129) → Middle RGB(100,140,110) → Red RGB(215,92,92)
#                         ↑ MUDDY GRAY/BROWN
```

**Solution: Use crisp color zones with sharp transitions:**

```python
# Professional approach ✅
Lines 1-3: Cool zone (emerald/teal) - consistent colors
Line 4:    Sharp transition to warm zone
Lines 5-6: Warm zone (reds) - consistent colors
```

#### Double Your Gradient Resolution: Half-Height Blocks

Rich supports **dual-color rendering** on single characters using Unicode half-blocks:

```python
from rich.segment import Segment
from rich.style import Style

# "▄" (lower half block) shows TWO colors per line:
# - bgcolor: top half
# - color: bottom half
Segment("▄", Style(color="#0ea876", bgcolor="#10b981"))
```

**Impact:** 6 lines = 12 gradient bands (not just 6)

#### Programmatic Color Generation

```python
from rich.color import blend_rgb, ColorTriplet

start = ColorTriplet(16, 185, 129)   # brand emerald
end = ColorTriplet(205, 92, 92)      # accent red

# Generate smooth intermediate colors
for i in range(12):
    cross_fade = i / 11
    color = blend_rgb(start, end, cross_fade)
```

**Reference:** `ColorBox` class in `rich/rich/__main__.py` demonstrates this pattern.

### Color Palette Guidance

**Brand Colors:**
- Primary: `#10b981` (emerald) - atmospheric, tech-forward
- Teal: `#0d9488` - cool transitions
- Rust/Industrial: `#cd5c5c` (`indian_red`) - oxidized, gritty aesthetic
- Deep Red: `#b91c1c`, `#991b1b` - warm accents

**Aesthetic Considerations:**
- **Oxidized/Industrial:** Use `indian_red` for weathered metal effects (not pure red)
- **Atmospheric/Tech:** Emerald + teal combinations create cyberpunk vibes
- **Avoid:** Yellow/orange intermediates when transitioning green → red (creates tropical aesthetics)

### When to Use Advanced Techniques

**Crisp Color Zones (standard):**
- Terminal branding, splash screens
- Conflicting color families (green ↔ red)
- Professional, clean aesthetic

**Smooth Gradients (advanced):**
- Progress indicators, dashboards
- Same color family transitions (cyan → blue → purple)
- Data visualization

**Half-Height Blocks (expert):**
- Ultra-smooth gradients needed (12+ color steps)
- Creative explorations
- High-impact visual elements

### Resources

- **BANNER_EXPERIMENTS.md** - Practical gradient examples, color theory
- **How-To.md** - Rich rendering techniques, custom renderables
- **Memory:** `/Users/Jason/.claude/memories/rich-terminal-branding-gradients.md`
- **DeepWiki:** `ASTXRTYS/Python-TUI-INDEX` for Rich framework patterns
