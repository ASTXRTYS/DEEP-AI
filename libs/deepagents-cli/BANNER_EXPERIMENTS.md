# Deep-Ai CLI Banner Experiments

This document tracks the A/B experiments for the `deepagents` CLI banner and ties them back to our [Styling Guide](STYLEGUIDE.md). Use it whenever you need to preview, update, or design a banner variant.

## Overview

- **Baseline (`deepagents`)** – legacy “Deep Agents” ASCII banner. Do not modify; it remains the default run without flags.
- **Experimental flags** – pass `--vN` to load a specific Deep-Ai banner, where `N` maps to a variant listed below.
- **Goal** – iterate on the visual rebrand toward “Deep-Ai” while preserving prompt-toolkit/Rich readability described in the Styling Guide.

## Current Variant Assignments

| Flag  | Status                | Notes                                              |
|-------|-----------------------|----------------------------------------------------|
| `--v1` | ✅ **Locked**          | **Asymmetric weighted gradient.** "DEEP" predominantly red (65% width, 5 color stops), "AI" green (25% width). Transition zone at 0.65-0.75. Creates red-dominant left side with creative variations, rapid shift, then clean green on right. Uses horizontal `GradientBanner` with `blend_rgb()`. |
| `--v2` | ✅ **Locked**          | **Advanced multi-stage gradient.** Custom `GradientBanner` renderable with per-character color control. 4-color stops: emerald (#10b981) → teal (#0d9488) → indian_red (#cd5c5c) → deep red (#8b1717). Oxidized industrial aesthetic matching profile pic. Uses `__rich_console__()` protocol with `_interpolate_color()` method for smooth transitions between color stops. |
| `--v3` | 🔧 **Working Copy**    | Clone of V2 for experimentation. Same 4-color gradient implementation. Modify this to iterate on color palette variations while keeping V2 locked. |
| `--v4` | ✅ **Complete**        | **Progressive Enhancement: HLS Basics.** "Deep-Ai" format with single dash and lowercase "i" (dot + gap + stem). Uses `HLSGradientBanner` with DIMMED_MONOKAI palette (red→green, hue 0.0→0.33, saturation 0.5). Follows Rich's ColorBox technique with analogous colors for professional TUI aesthetic. Perceptually smooth transitions via HLS color space. |
| `--v5` | ✅ **Complete**        | **Style Layering: Vibrant MONOKAI.** "Deep-Ai" format with lowercase "i". `HLSGradientBanner` with full saturation (1.0) and vibrant hue range (magenta-red 0.9 → yellow-green 0.4). High-energy electric colors for maximum visual impact. Bright lightness (0.50-0.65) creates bold, attention-grabbing appearance. |
| `--v6` | ✅ **Complete**        | **Advanced: Burgundy/Dried Blood.** "Deep-Ai" format with lowercase "i". `HLSGradientBanner` with matte burgundy tones (hue 0.98→0.02). Dark lightness (0.28-0.35) and moderate saturation (0.65) create gritty, industrial dried blood aesthetic. Smooth perceptual transitions praised by user testing. |
| `--v7` | ✅ **Complete**        | **Final: Dried Blood Monochrome.** "Deep-Ai" format with single dash `─` and properly aligned lowercase "i". Uses V2's exact stone red color palette (115,65,60 → 130,75,68 → 125,72,65 → 120,70,63) that user identified as closest to dried blood aesthetic. Monochrome with subtle variations for depth. Combined V2's color + V6's smooth transitions. |

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

By isolating each variant's renderer, we can mix PyFiglet, hand-tuned art, or Rich-native renderables without impacting other flags. Developers helping with future iterations should follow these steps so every experiment stays aligned with the styling guide and the CLI's startup flow.

## Advanced Gradient Techniques

### The Math Problem: Avoiding Muddy Intermediates

When creating color gradients from green → red using mathematical RGB blending, you encounter a fundamental problem: colors in the middle become muddy browns and grays.

**Why this happens:**
- Green: RGB(16, 185, 129) - high green, low red
- Red: RGB(215, 92, 92) - high red, low green
- Middle: RGB(100, 140, 110) - R≈G≈B = **muddy gray/brown**

**Solution: Crisp Color Zones**

Instead of smooth mathematical blending, use **clear color zones with sharp transitions**:

```python
# Lines 1-3: Cool zone (emerald/teal family)
[#10b981]  # Emerald - consistency
[#10b981]  # Emerald - like v7's approach
[#0d9488]  # Teal - subtle variation

# Line 4: Sharp transition
[#cd5c5c]  # indian_red - JUMP to warm oxidized aesthetic

# Lines 5-6: Warm zone (red family)
[#b91c1c]  # Deep red
[#991b1b]  # Darker red
```

This creates professional, crisp transitions without muddy intermediates.

### Advanced Technique: Half-Height Block Characters for 2x Resolution

Rich supports **dual-color rendering** on single characters, effectively doubling your gradient resolution:

**Using "▄" (lower half block):**
- Each character displays TWO colors
- `bgcolor`: Top half of the character
- `color` (foreground): Bottom half of the character

```python
from rich.segment import Segment
from rich.style import Style

# One terminal line = TWO color bands
Segment("▄", Style(color="#0ea876", bgcolor="#10b981"))
# Result: emerald (#10b981) on top, teal (#0ea876) on bottom
```

**Impact:** 6 terminal lines = 12 gradient steps instead of just 6!

### Programmatic Gradient Generation

Use Rich's `blend_rgb()` function for smooth color interpolation:

```python
from rich.color import blend_rgb, ColorTriplet

start = ColorTriplet(16, 185, 129)   # emerald green
end = ColorTriplet(205, 92, 92)      # indian red

# Generate 12 intermediate colors
for i in range(12):
    cross_fade = i / 11  # 0.0 to 1.0
    intermediate = blend_rgb(start, end, cross_fade)
    # Use intermediate color for fine-grained gradient
```

**Reference:** See `ColorBox` class in `rich/rich/__main__.py` for a complete example of programmatic gradient generation with half-height blocks.

### When to Use Which Approach

**Crisp Color Zones (6 colors):**
- ✅ Professional, clean aesthetic
- ✅ Conflicting color families (green → red)
- ✅ Terminal branding, splash screens
- ✅ Matches v7's "crisp" quality

**Smooth Gradients (12+ colors via half-blocks):**
- ✅ Ultra-smooth transitions needed
- ✅ Same color family (cyan → blue → purple)
- ✅ Progress indicators, data visualization
- ✅ Creative explorations

### Color Theory Considerations

**Oxidized/Industrial Aesthetics:**
- Use `indian_red` (#cd5c5c) for weathered metal/rust effects
- Orangish-reds convey oxidation without tropical vibes
- Avoid pure reds when targeting gritty industrial branding

**Atmospheric Effects:**
- Emerald (#10b981) and teal (#0d9488) create cool, atmospheric tones
- Works well for cyberpunk or tech-focused branding

For more advanced Rich rendering techniques, color systems, and creative branding strategies, see:
- **STYLEGUIDE.md** - Creative branding section
- **How-To.md** - Rich gradient examples and custom renderables
- **Memory:** `/Users/Jason/.claude/memories/rich-terminal-branding-gradients.md`

## HLS Color Space Gradient Technique (V4, V5, V6)

### Why HLS Over RGB?

Rich's official `ColorBox` implementation uses `colorsys.hls_to_rgb()` for perceptually uniform gradients. HLS (Hue, Lightness, Saturation) separates color properties, avoiding the muddy mid-tones that occur with pure RGB interpolation.

**RGB Problem:**
```python
# Green RGB(16,185,129) → Red RGB(215,92,92)
# Middle: RGB(100,140,110) ← MUDDY GRAY/BROWN
```

**HLS Solution:**
```python
# Hue 0.33 (green) → Hue 0.0 (red) with consistent lightness/saturation
# Result: Clean color transitions through the color wheel
```

### The HLSGradientBanner Class

```python
class HLSGradientBanner:
    def __init__(self, lines, hue_range, lightness_range, saturation):
        # hue_range: (start, end) where 0.0=red, 0.33=green, 0.67=blue
        # lightness_range: (start, end) where 0.0=black, 1.0=white
        # saturation: 0.0=grayscale, 1.0=full color

    def __rich_console__(self, console, options):
        for char_index, char in enumerate(line):
            position = char_index / line_length

            # Interpolate in HLS space
            hue = start_hue + (end_hue - start_hue) * position
            lightness = start_light + (end_light - start_light) * position

            # Convert to RGB for display
            r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
            color = Color.from_rgb(r * 255, g * 255, b * 255)
```

### Progressive Enhancement Strategy (Expert Recommendation)

**V4: Basic HLS Gradient**
- DIMMED_MONOKAI palette via HLS
- Analogous colors (red→green, adjacent on color wheel)
- Desaturated (0.5) for professional TUI aesthetic
- Moderate lightness for readability

**V5: Advanced Vibrancy**
- Full color wheel traversal (hue 0.9→0.4)
- Maximum saturation (1.0) for electric impact
- Bright lightness (0.50-0.65) for high energy
- MONOKAI vibrant palette philosophy

**V6: Specialized Aesthetic**
- Narrow hue range (0.98→0.02) for burgundy spectrum
- Dark lightness (0.28-0.35) for matte, gritty feel
- Moderate saturation (0.65) for dried blood aesthetic
- User-tested smooth transitions

### Color Wheel Reference (Hue Values)

- **0.0 / 1.0:** Red
- **0.08:** Orange/Bronze
- **0.17:** Yellow/Gold
- **0.33:** Green
- **0.50:** Cyan
- **0.67:** Blue
- **0.83:** Purple/Violet
- **0.95:** Magenta
- **0.98:** Burgundy (red-purple)

### Lowercase "i" Implementation

All v4-v6 variants use proper lowercase "i" structure:
```
Line 1: (empty - uppercase letters only)
Line 2: ██  (dot)
Line 3: (empty - gap between dot and stem)
Line 4: ██  (stem)
Line 5: ██  (stem)
Line 6: ██  (stem base)
```

This creates visual distinction from uppercase "I" while maintaining the block font aesthetic.
