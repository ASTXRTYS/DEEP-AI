# Deep-Ai CLI Banner Experiments

This document tracks the A/B experiments for the `deepagents` CLI banner and ties them back to our [Styling Guide](STYLEGUIDE.md). Use it whenever you need to preview, update, or design a banner variant.

## Overview

- **Baseline (`deepagents`)** – legacy “Deep Agents” ASCII banner. Do not modify; it remains the default run without flags.
- **Experimental flags** – pass `--vN` to load a specific Deep-Ai banner, where `N` maps to a variant listed below.
- **Goal** – iterate on the visual rebrand toward “Deep-Ai” while preserving prompt-toolkit/Rich readability described in the Styling Guide.

## Current Variant Assignments

| Flag  | Status                | Notes                                              |
|-------|-----------------------|----------------------------------------------------|
| `--v1` | ✅ **Locked**          | Canonical Deep-Ai block lettering (matches default layout). |
| `--v2` | ✅ **Locked**          | Boxed panel design with dim cyan borders and bright cyan title. |
| `--v3` | Draft / stub         | Reserved for upcoming iteration (currently a simple placeholder banner string). |
| `--v4` | ✅ **Complete**        | Cyan-to-green gradient effect. Transitions from bright_cyan → cyan → #10b981 (emerald). |
| `--v5` | ✅ **Complete**        | Dual-tone split design. Bright cyan "DEEP" + bright magenta "-AI" creating visual contrast. |
| `--v6` | ✅ **Complete**        | Electric/neon variant with yellow-to-white gradient on black background for high contrast. |
| `--v7` | ✅ **Complete**        | Minimal/clean aesthetic with dim cyan "DEEP" fading to bold white "-AI". |

To test a variant locally:

```bash
cd libs/deepagents-cli
deepagents --v1      # swap the banner to the locked Deep-Ai design
deepagents --v2      # load the experimental v2 banner (if defined)
```

## Editing Workflow

1. **Update ASCII constants** in `libs/deepagents-cli/deepagents_cli/config.py` (`DEEP_AI_ASCII_VN`).
2. **Verify rendering** inside the CLI via the corresponding `--vN` flag. Capture screenshots for review.
3. **Document the change** in this file (status, notes, screenshots if needed).
4. **Align with the Styling Guide**:
   - Reuse the palette, spacing, and typography guidelines in [STYLEGUIDE.md](STYLEGUIDE.md).
   - Keep each glyph rectangular and under 70 columns so Rich/prompt_toolkit renders them consistently.
   - Use blank-line separators when stacking words to match our standard layout rhythm.

## Visual Guidelines (from the Styling Guide)

- **Palette**: Pull colors from `COLORS` in `config.py` or the `ui_constants` palette. Avoid ad-hoc hex codes.
- **Typography**: Follow the monospace grid described in [STYLEGUIDE.md](STYLEGUIDE.md); prefer repeating glyph modules so letters feel cohesive.
- **Spacing & Layout**: Maintain the same vertical rhythm as the default banner (six-line blocks with a blank separator) to keep UX expectations stable.
- **Advanced renderables**: For gradient panels, rule-based separators, or Rich protocol examples, see [`How-To.md`](../../How-To.md). Any new v2/v3 experimentation must review that guide before introducing a new rendering framework.

Keeping these constraints synchronized with the styling guide ensures new banners slot into the CLI without regressions.

## Upcoming Experiments & Framework Mixing

- **Next target (`--v2`)** – prototype a PyFiglet-based Deep-Ai banner so we can compare hand-tuned ASCII vs generated fonts.
- **Future slots (`--v3`, `--v4`)** – may use other generators or bespoke renderables (e.g., custom Rich panels, prompt_toolkit layouts). Each slot can adopt a different rendering approach as long as the output ultimately feeds `console.print`.

### How to iterate on a framework-specific variant

1. **Render logic per variant**  
   Update `get_banner_ascii()` (or a helper) so a variant key can point to either a string or a callable. For example, `v2` can call a PyFiglet renderer while `v1` remains a literal string.

2. **PyFiglet pattern**  
   - Import `pyfiglet.Figlet`.
   - Render with a constrained width (≤ 80) and convert to a Rich-safe object via `Text.from_ansi()` to preserve spacing and colors.
   - Cache or pre-render the text if the font generation becomes expensive.

3. **Other frameworks**  
   If a future request specifies a different generator, wrap it in the same callable pattern: generate the ASCII/string, ensure it respects styling-guide constraints, and return text that Rich can print directly (either plain str or `Text`/custom renderable).

4. **Verification**  
   Always test via the flag (`deepagents --vN`) to confirm prompt_toolkit and Rich render the banner cleanly. Capture screenshots and update the table above with the new status/notes.

By isolating each variant’s renderer, we can mix PyFiglet, hand-tuned art, or Rich-native renderables without impacting other flags. Developers helping with future iterations should follow these steps so every experiment stays aligned with the styling guide and the CLI’s startup flow.
