"""Configuration, constants, and model creation for the CLI."""

import colorsys
import os
import sys
from pathlib import Path
from typing import Any

import dotenv
from rich.console import Console, ConsoleOptions, RenderResult
from rich.color import Color, blend_rgb
from rich.color_triplet import ColorTriplet
from rich.segment import Segment
from rich.style import Style

dotenv.load_dotenv()

# Color scheme
COLORS = {
    "primary": "#10b981",
    "dim": "#6b7280",
    "user": "#ffffff",
    "agent": "#10b981",
    "thinking": "#34d399",
    "tool": "#fbbf24",
}

# ASCII art banner (default - current Deep Agents branding)
DEEP_AGENTS_ASCII = """
 ██████╗  ███████╗ ███████╗ ██████╗
 ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗
 ██║  ██║ █████╗   █████╗   ██████╔╝
 ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝
 ██████╔╝ ███████╗ ███████╗ ██║
 ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝

  █████╗   ██████╗  ███████╗ ███╗   ██╗ ████████╗ ███████╗
 ██╔══██╗ ██╔════╝  ██╔════╝ ████╗  ██║ ╚══██╔══╝ ██╔════╝
 ███████║ ██║  ███╗ █████╗   ██╔██╗ ██║    ██║    ███████╗
 ██╔══██║ ██║   ██║ ██╔══╝   ██║╚██╗██║    ██║    ╚════██║
 ██║  ██║ ╚██████╔╝ ███████╗ ██║ ╚████║    ██║    ███████║
 ╚═╝  ╚═╝  ╚═════╝  ╚══════╝ ╚═╝  ╚═══╝    ╚═╝    ╚══════╝
"""

# Experimental Deep-Ai banner variants.
# These are opt-in via CLI flags (e.g., --v1, --v2, ...).

class GradientBanner:
    """Custom renderable for smooth per-character gradient banners with color stops.

    Uses Rich's __rich_console__() protocol to yield Segment objects with
    programmatically calculated colors for each character position, creating
    smooth gradient transitions through multiple color stops.
    """

    def __init__(self, lines: list[str], color_stops: list[tuple[float, tuple[int, int, int]]]):
        """Initialize multi-stage gradient banner.

        Args:
            lines: List of ASCII art lines (without markup)
            color_stops: List of (position, RGB) tuples where position is 0.0-1.0
                        Example: [(0.0, (16,185,129)), (0.5, (0,255,136)), (1.0, (205,92,92))]
        """
        self.lines = lines
        self.color_stops = sorted(color_stops, key=lambda x: x[0])

    def _interpolate_color(self, position: float) -> ColorTriplet:
        """Get interpolated RGB color at given position (0.0-1.0).

        Uses Rich's blend_rgb() function for proper color interpolation.
        """
        # Clamp position to valid range
        position = max(0.0, min(1.0, position))

        # Find the two color stops to interpolate between
        for i in range(len(self.color_stops) - 1):
            pos1, color1 = self.color_stops[i]
            pos2, color2 = self.color_stops[i + 1]

            if pos1 <= position <= pos2:
                # Calculate local ratio between these two stops
                if pos2 - pos1 == 0:
                    local_ratio = 0
                else:
                    local_ratio = (position - pos1) / (pos2 - pos1)

                # Use Rich's blend_rgb() function
                color1_triplet = ColorTriplet(*color1)
                color2_triplet = ColorTriplet(*color2)
                return blend_rgb(color1_triplet, color2_triplet, local_ratio)

        # If position is beyond last stop, return last color
        return ColorTriplet(*self.color_stops[-1][1])

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Yield Segment objects with per-character gradient colors.

        Creates a HORIZONTAL gradient across each line (left to right),
        not a vertical gradient down the banner.
        """
        for line in self.lines:
            line_length = len(line)

            for char_index, char in enumerate(line):
                # Calculate position WITHIN THIS LINE (0.0 to 1.0)
                # This creates a horizontal gradient, not vertical
                position = char_index / line_length if line_length > 0 else 0

                # Get interpolated color using Rich's blend_rgb()
                color_triplet = self._interpolate_color(position)
                color = Color.from_triplet(color_triplet)
                yield Segment(char, Style(color=color))

            # End of line
            yield Segment.line()


class HLSGradientBanner:
    """Advanced gradient banner using HLS color space for smoother transitions.

    Based on Rich's ColorBox implementation, this uses colorsys.hls_to_rgb()
    for perceptually uniform gradients that avoid muddy mid-tones common in
    RGB interpolation. Supports the half-block technique for double resolution.
    """

    def __init__(self, lines: list[str], hue_range: tuple[float, float],
                 lightness_range: tuple[float, float], saturation: float = 1.0,
                 use_half_blocks: bool = False):
        """Initialize HLS-based gradient banner.

        Args:
            lines: List of ASCII art lines
            hue_range: (start_hue, end_hue) where 0.0-1.0 represents the color wheel
                      Examples: 0.0=red, 0.33=green, 0.67=blue
            lightness_range: (start_lightness, end_lightness) where 0.0=black, 1.0=white
            saturation: Color saturation (0.0=grayscale, 1.0=full color)
            use_half_blocks: Use "▄" with dual colors for 2x vertical resolution
        """
        self.lines = lines
        self.hue_start, self.hue_end = hue_range
        self.light_start, self.light_end = lightness_range
        self.saturation = saturation
        self.use_half_blocks = use_half_blocks

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Yield Segment objects with HLS-calculated gradient colors."""
        for line in self.lines:
            line_length = len(line)

            for char_index, char in enumerate(line):
                # Calculate horizontal position (0.0 to 1.0)
                position = char_index / line_length if line_length > 0 else 0

                # Interpolate hue and lightness using HLS color space
                hue = self.hue_start + (self.hue_end - self.hue_start) * position
                lightness = self.light_start + (self.light_end - self.light_start) * position

                # Convert HLS to RGB
                r, g, b = colorsys.hls_to_rgb(hue, lightness, self.saturation)
                color = Color.from_rgb(r * 255, g * 255, b * 255)

                yield Segment(char, Style(color=color))

            yield Segment.line()


# V1: Matte red → matte green (desaturated, restrained gradient)
# Professional aesthetic: muted tones similar to Rich's own logo design
DEEP_AI_ASCII_V1 = GradientBanner(
    lines=[
        " ██████╗  ███████╗ ███████╗ ██████╗       █████╗        ██╗",
        " ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗     ██╔══██╗       ██║",
        " ██║  ██║ █████╗   █████╗   ██████╔╝     ███████║       ██║",
        " ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝      ██╔══██║       ██║",
        " ██████╔╝ ███████╗ ███████╗ ██║          ██║  ██║       ██║",
        " ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝          ╚═╝  ╚═╝       ╚═╝",
    ],
    color_stops=[
        # DEEP region: 0.0-0.65 (matte red dominant) - desaturated, earthy reds
        (0.00, (120, 70, 65)),     # Dark matte red (stone-like)
        (0.20, (140, 80, 70)),     # Medium matte red
        (0.40, (135, 85, 75)),     # Lighter matte red (subtle variation)
        (0.60, (110, 95, 85)),     # Red-gray transition (neutral, muted)

        # Transition zone: 0.65-0.75 (short, subtle shift)
        (0.70, (85, 100, 90)),     # Gray-green (desaturated neutral)

        # AI region: 0.75-1.0 (matte green) - desaturated emerald similar to default
        (0.80, (50, 120, 100)),    # Matte emerald (desaturated #10b981)
        (0.90, (40, 130, 105)),    # Slightly brighter matte green
        (1.00, (45, 125, 100)),    # Matte emerald (consistent with Deep Agents default)
    ]
)

# V2: Stone red monochrome (single matte red palette, profile pic aesthetic)
# Minimal, restrained: subtle variations within desaturated red spectrum only
DEEP_AI_ASCII_V2 = GradientBanner(
    lines=[
        " ██████╗  ███████╗ ███████╗ ██████╗       █████╗        ██╗",
        " ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗     ██╔══██╗       ██║",
        " ██║  ██║ █████╗   █████╗   ██████╔╝     ███████║       ██║",
        " ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝      ██╔══██║       ██║",
        " ██████╔╝ ███████╗ ███████╗ ██║          ██║  ██║       ██║",
        " ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝          ╚═╝  ╚═╝       ╚═╝",
    ],
    color_stops=[
        # Monochrome stone red: very subtle variations for depth, no other colors
        (0.0, (115, 65, 60)),      # Dark stone red (shadows)
        (0.3, (130, 75, 68)),      # Medium stone red
        (0.6, (125, 72, 65)),      # Slightly lighter stone red (subtle highlight)
        (1.0, (120, 70, 63)),      # Return to darker stone red (consistent depth)
    ]
)

# V3: HORIZONTAL gradient with vibrant neon green → blood red
# Using Rich's blend_rgb() with horizontal flow (left to right per line)
DEEP_AI_ASCII_V3 = GradientBanner(
    lines=[
        " ██████╗  ███████╗ ███████╗ ██████╗       █████╗        ██╗",
        " ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗     ██╔══██╗       ██║",
        " ██║  ██║ █████╗   █████╗   ██████╔╝     ███████║       ██║",
        " ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝      ██╔══██║       ██║",
        " ██████╔╝ ███████╗ ███████╗ ██║          ██║  ██║       ██║",
        " ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝          ╚═╝  ╚═╝       ╚═╝",
    ],
    color_stops=[
        (0.0, (57, 255, 20)),      # Bright neon green (AI/electric green)
        (0.2, (30, 255, 60)),      # Vibrant electric green
        (0.4, (0, 255, 100)),      # Pure electric green
        (0.6, (255, 100, 0)),      # Orange transition (fire)
        (0.8, (220, 20, 20)),      # Bright blood red
        (1.0, (139, 0, 0)),        # Dark blood red (Warhammer aesthetic)
    ]
)

# V4: Progressive Enhancement - Basic HLS gradient with DIMMED_MONOKAI palette
# Follows Rich's ColorBox technique using HLS color space for smooth perceptual transitions
# Analogous colors (red→gold→green hue progression) for professional aesthetic
DEEP_AI_ASCII_V4 = HLSGradientBanner(
    lines=[
        " ██████╗  ███████╗ ███████╗ ██████╗            █████╗          ",
        " ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗    ━     ██╔══██╗     ██  ",  # Dot for lowercase i
        " ██║  ██║ █████╗   █████╗   ██████╔╝    ━     ███████║         ",  # Gap between dot and stem
        " ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝     ━     ██╔══██║     ██  ",  # Stem starts
        " ██████╔╝ ███████╗ ███████╗ ██║         ━     ██║  ██║     ██  ",  # Stem continues
        " ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝               ╚═╝  ╚═╝     ██  ",  # Stem base
    ],
    hue_range=(0.0, 0.33),          # Red (0.0) → Green (0.33) - analogous color progression
    lightness_range=(0.35, 0.55),   # Moderate lightness for DIMMED_MONOKAI aesthetic
    saturation=0.5                   # Desaturated for professional TUI appearance
)

# V5: Style Layering - Vibrant MONOKAI with high saturation HLS gradient
# Advanced: Full color wheel traversal for maximum visual impact
# High saturation + varied lightness for electric, vibrant aesthetic
DEEP_AI_ASCII_V5 = HLSGradientBanner(
    lines=[
        " ██████╗  ███████╗ ███████╗ ██████╗            █████╗          ",
        " ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗    ━     ██╔══██╗     ██  ",  # Dot for lowercase i
        " ██║  ██║ █████╗   █████╗   ██████╔╝    ━     ███████║         ",  # Gap between dot and stem
        " ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝     ━     ██╔══██║     ██  ",  # Stem starts
        " ██████╔╝ ███████╗ ███████╗ ██║         ━     ██║  ██║     ██  ",  # Stem continues
        " ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝               ╚═╝  ╚═╝     ██  ",  # Stem base
    ],
    hue_range=(0.9, 0.4),           # Magenta-red (0.9) → Yellow-green (0.4) - vibrant spectrum
    lightness_range=(0.50, 0.65),   # Bright lightness for high-energy MONOKAI aesthetic
    saturation=1.0                   # Full saturation for maximum vibrancy
)

# V6: Advanced - Matte burgundy/dried blood gradient with HLS smoothness
# Dark red-burgundy tones with subtle transition for gritty, industrial aesthetic
# User feedback: "smooth transition" achieved via HLS color space
DEEP_AI_ASCII_V6 = HLSGradientBanner(
    lines=[
        " ██████╗  ███████╗ ███████╗ ██████╗            █████╗          ",
        " ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗    ━     ██╔══██╗     ██  ",  # Dot for lowercase i
        " ██║  ██║ █████╗   █████╗   ██████╔╝    ━     ███████║         ",  # Gap between dot and stem
        " ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝     ━     ██╔══██║     ██  ",  # Stem starts
        " ██████╔╝ ███████╗ ███████╗ ██║         ━     ██║  ██║     ██  ",  # Stem continues
        " ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝               ╚═╝  ╚═╝     ██  ",  # Stem base
    ],
    hue_range=(0.98, 0.02),         # Burgundy-red (0.98) → Deep red (0.02) - dried blood spectrum
    lightness_range=(0.28, 0.35),   # Dark for matte, dried blood aesthetic
    saturation=0.65                  # Moderate saturation for matte burgundy (not glossy)
)

# V7: Final - V2's dried blood color + V6's smooth HLS transitions
# Stone red monochrome palette with subtle variations for depth
# Single dash, properly aligned lowercase "i" matching baseline
DEEP_AI_ASCII_V7 = GradientBanner(
    lines=[
        " ██████╗  ███████╗ ███████╗ ██████╗       ─      █████╗       ██  ",
        " ██╔══██╗ ██╔════╝ ██╔════╝ ██╔══██╗      ─     ██╔══██╗          ",
        " ██║  ██║ █████╗   █████╗   ██████╔╝      ─     ███████║      ██  ",
        " ██║  ██║ ██╔══╝   ██╔══╝   ██╔═══╝       ─     ██╔══██║      ██  ",
        " ██████╔╝ ███████╗ ███████╗ ██║           ─     ██║  ██║      ██  ",
        " ╚═════╝  ╚══════╝ ╚══════╝ ╚═╝                 ╚═╝  ╚═╝      ██  ",
    ],
    color_stops=[
        # V2's stone red palette - the dried blood color you liked
        # Monochrome with subtle variations for depth (not gradient across spectrum)
        (0.0, (115, 65, 60)),      # Dark stone red (shadows)
        (0.3, (130, 75, 68)),      # Medium stone red
        (0.6, (125, 72, 65)),      # Slightly lighter stone red (subtle highlight)
        (1.0, (120, 70, 63)),      # Return to darker stone red (consistent depth)
    ]
)

BANNER_VARIANTS: dict[str, str] = {
    "v1": DEEP_AI_ASCII_V1,
    "v2": DEEP_AI_ASCII_V2,
    "v3": DEEP_AI_ASCII_V3,
    "v4": DEEP_AI_ASCII_V4,
    "v5": DEEP_AI_ASCII_V5,
    "v6": DEEP_AI_ASCII_V6,
    "v7": DEEP_AI_ASCII_V7,
}


def get_banner_ascii(banner_variant: str | None) -> str:
    """Return the appropriate banner ASCII art for the given variant.

    Args:
        banner_variant: Variant key such as "v1", "v2", etc., or None.

    Returns:
        ASCII art string for the selected banner. Defaults to DEEP_AGENTS_ASCII
        when no variant (or an unknown variant) is provided.
    """
    if not banner_variant:
        return DEEP_AGENTS_ASCII
    return BANNER_VARIANTS.get(banner_variant, DEEP_AGENTS_ASCII)

# Interactive commands (shown in autocomplete)
# Only essential, high-signal commands are listed here for clean UX.
# Advanced commands still work but are hidden from autocomplete.
COMMANDS = {
    "help": "Show help and available commands",
    "new": "Create a new thread (/new [name])",
    "threads": "Switch threads (interactive)",
    "handoff": "Summarize current thread and start a child",
    "tokens": "Show token usage statistics",
    "clear": "Clear screen",
    "quit": "Exit (also: /exit)",
    "exit": "Exit the CLI",
}


# Maximum argument length for display
MAX_ARG_LENGTH = 150

# Agent configuration
config = {"recursion_limit": 1000}

# Rich console instance
console = Console(highlight=False)

# Server request timeout (seconds)
try:
    SERVER_REQUEST_TIMEOUT: float = float(os.getenv("LANGGRAPH_SERVER_TIMEOUT", "5"))
except ValueError:
    SERVER_REQUEST_TIMEOUT = 5.0

# Async checkpointer (required since execute_task is async)
# Set to "0" only for debugging/compatibility testing
USE_ASYNC_CHECKPOINTER = os.getenv("DEEPAGENTS_USE_ASYNC_CHECKPOINTER", "1") in {
    "1",
    "true",
    "True",
}


class SessionState:
    """Holds mutable session state (auto-approve mode, thread manager, etc)."""

    def __init__(
        self,
        auto_approve: bool = False,
        thread_manager: Any | None = None,
        banner_variant: str | None = None,
    ) -> None:
        self.auto_approve = auto_approve
        self.thread_manager = thread_manager
        self.banner_variant = banner_variant
        self.model = None
        self.pending_handoff_child_id: str | None = None  # Deferred handoff target
        self.menu_requested: bool = False  # Reserved for manual menu triggers
        self.exit_hint_until: float | None = None
        self.exit_hint_handle = None

    def toggle_auto_approve(self) -> bool:
        """Toggle auto-approve and return new state."""
        self.auto_approve = not self.auto_approve
        return self.auto_approve


def get_default_coding_instructions() -> str:
    """Get the default coding agent instructions.

    These are the immutable base instructions that cannot be modified by the agent.
    Long-term memory (agent.md) is handled separately by the middleware.
    """
    default_prompt_path = Path(__file__).parent / "default_agent_prompt.md"
    return default_prompt_path.read_text()


def create_model():
    """Create the appropriate model based on available API keys.

    Returns:
        ChatModel instance (OpenAI or Anthropic)

    Raises:
        SystemExit if no API key is configured
    """
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if openai_key:
        from langchain_openai import ChatOpenAI

        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        console.print(f"[dim]Using OpenAI model: {model_name}[/dim]")
        return ChatOpenAI(
            model=model_name,
        )
    if anthropic_key:
        from langchain_anthropic import ChatAnthropic

        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        console.print(f"[dim]Using Anthropic model: {model_name}[/dim]")
        return ChatAnthropic(
            model_name=model_name,
            max_tokens=20000,
        )
    console.print("[bold red]Error:[/bold red] No API key configured.")
    console.print("\nPlease set one of the following environment variables:")
    console.print("  - OPENAI_API_KEY     (for OpenAI models like gpt-5-mini)")
    console.print("  - ANTHROPIC_API_KEY  (for Claude models)")
    console.print("\nExample:")
    console.print("  export OPENAI_API_KEY=your_api_key_here")
    console.print("\nOr add it to your .env file.")
    sys.exit(1)
