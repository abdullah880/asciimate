"""Centralized configuration for the Animated ASCII Image Renderer.

This module defines :class:`AppConfig`, a single dataclass that holds every
user-tunable parameter of the application, together with sensible defaults and
a helper to build an instance from command-line arguments.

Keeping all configuration in one place makes the rest of the codebase clean:
modules simply receive an :class:`AppConfig` and read whatever they need from
it, instead of each module parsing its own arguments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Tuple

# ---------------------------------------------------------------------------
# Default character ramps.
# ---------------------------------------------------------------------------
# Ordered from darkest (most ink) to brightest (least ink).  The first
# character represents near-black pixels and the last character represents
# near-white pixels.

# A compact, classic ramp that reads well in a terminal.
DEFAULT_RAMP: str = "@%#*+=-:. "

# A denser ramp offering finer tonal gradation.
DENSE_RAMP: str = (
    "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`'. "
)

# A minimal ramp for a high-contrast, blocky look.
MINIMAL_RAMP: str = "###...   "

# A ramp using only block characters (clean, "pixel" feel).
BLOCK_RAMP: str = "\u2588\u2593\u2592\u2591 "

# Named ramps selectable from the CLI via ``--ramp <name>``.
RAMPS: dict[str, str] = {
    "default": DEFAULT_RAMP,
    "dense": DENSE_RAMP,
    "minimal": MINIMAL_RAMP,
    "block": BLOCK_RAMP,
}

# ---------------------------------------------------------------------------
# Animation mode registry.
# ---------------------------------------------------------------------------
# 1-based so that the keyboard digits (1..7) map directly to a mode.

MODE_PROGRESSIVE = 1
MODE_RANDOM = 2
MODE_SCAN = 3
MODE_CENTER = 4
MODE_WAVE = 5
MODE_MATRIX = 6
MODE_FADE = 7

MODE_NAMES: dict[int, str] = {
    MODE_PROGRESSIVE: "Progressive Reveal",
    MODE_RANDOM: "Random Decode",
    MODE_SCAN: "Top-to-Bottom Scan",
    MODE_CENTER: "Center Expansion",
    MODE_WAVE: "Wave Reveal",
    MODE_MATRIX: "Matrix Decode",
    MODE_FADE: "Fade-In",
}

ALL_MODES: tuple[int, ...] = tuple(MODE_NAMES.keys())

# ---------------------------------------------------------------------------
# Color presets (foreground/background) for the monochrome themes.
# ---------------------------------------------------------------------------
# Each theme is (foreground, background).  Values chosen to look like classic
# phosphor terminals without being eye-straining.

THEMES: dict[str, Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = {
    "white": ((224, 224, 224), (8, 8, 12)),
    "green": ((120, 255, 120), (4, 8, 4)),
    "amber": ((255, 176, 64), (10, 6, 2)),
    "cyan": ((120, 220, 255), (2, 8, 12)),
}

DEFAULT_THEME = "green"


def default_font_path() -> str:
    """Return a sensible default monospaced font path if one exists."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/Library/Fonts/Menlo.ttc",
        "C:/Windows/Fonts/consola.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    # Empty string -> the renderer will fall back to pygame's built-in font.
    return ""


@dataclass
class AppConfig:
    """All runtime configuration for the application.

    Attributes are intentionally simple primitives so the object can be
    constructed trivially from the command line or from a literal in tests.
    """

    # --- Source ----------------------------------------------------------------
    image_path: str = ""

    # --- Output dimensions -----------------------------------------------------
    # 0 means "compute automatically".  When both are 0 the width is derived
    # from the window size and the height follows from the aspect ratio.
    output_width: int = 0
    output_height: int = 0

    # Hard limits to keep performance acceptable on huge images.
    max_width: int = 320
    max_height: int = 200

    # --- Character mapping -----------------------------------------------------
    char_ramp: str = DEFAULT_RAMP

    # --- Display / font --------------------------------------------------------
    font_path: str = field(default_factory=default_font_path)
    font_size: int = 16

    # --- Animation -------------------------------------------------------------
    animation_mode: int = MODE_PROGRESSIVE
    animation_speed: float = 1.0
    target_fps: int = 60

    # --- Colors ----------------------------------------------------------------
    # Default to "original" so photographic content is immediately recognizable
    # (the source pixel colours give strong subject cues).  Mono / phosphor
    # terminal themes are one keypress away (C) or via --color mono.
    color_mode: str = "original"
    theme: str = DEFAULT_THEME
    foreground_color: Tuple[int, int, int] = field(
        default_factory=lambda: THEMES[DEFAULT_THEME][0]
    )
    background_color: Tuple[int, int, int] = field(
        default_factory=lambda: THEMES[DEFAULT_THEME][1]
    )
    glow: bool = False

    # --- Image processing ------------------------------------------------------
    brightness: float = 1.0
    contrast: float = 1.0
    gamma: float = 1.0
    invert: bool = False
    edge_enhance: bool = False

    # --- Window ----------------------------------------------------------------
    window_width: int = 0             # 0 => auto (based on artwork)
    window_height: int = 0            # 0 => auto
    resizable: bool = True

    # --- UI --------------------------------------------------------------------
    show_info_panel: bool = True

    # --- Recording -------------------------------------------------------------
    # Title overlay burned into recorded videos.  Empty string => use the
    # source filename as the title.
    title: str = ""
    # Video frame rate for recordings (the spec asks for 60 FPS).
    record_fps: int = 60
    # Auto-record on launch (set by ``--record``).  0.0 = disabled (use the V
    # key interactively instead); -1.0 = record until the animation finishes
    # plus a short hold; >0 = record for that many seconds.  When auto-record
    # finishes the application quits, which makes it scriptable.
    record_seconds: float = 0.0

    # Reveal duration at speed 1.0, before scaling for image size (seconds).
    base_duration: float = 6.0

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    def clamp(self) -> "AppConfig":
        """Return *self* after clamping numeric fields to safe ranges.

        Invalid values are repaired in-place so the rest of the application
        can assume every field is sane.
        """
        self.output_width = max(0, min(self.output_width, self.max_width))
        self.output_height = max(0, min(self.output_height, self.max_height))
        self.font_size = max(6, min(self.font_size, 96))
        self.animation_speed = max(0.05, min(self.animation_speed, 16.0))
        self.target_fps = max(15, min(self.target_fps, 240))
        self.brightness = max(0.0, min(self.brightness, 4.0))
        self.contrast = max(0.0, min(self.contrast, 4.0))
        self.gamma = max(0.1, min(self.gamma, 4.0))
        self.window_width = max(0, self.window_width)
        self.window_height = max(0, self.window_height)
        self.record_fps = max(15, min(self.record_fps, 120))
        if not self.char_ramp:
            self.char_ramp = DEFAULT_RAMP
        if self.animation_mode not in MODE_NAMES:
            self.animation_mode = MODE_PROGRESSIVE
        if self.theme not in THEMES:
            self.theme = DEFAULT_THEME
            self.foreground_color, self.background_color = THEMES[DEFAULT_THEME]
        if self.color_mode not in ("mono", "original"):
            self.color_mode = "mono"
        return self

    def as_dict(self) -> dict:
        """Return a plain-dict snapshot of the configuration."""
        return {f.name: getattr(self, f.name) for f in fields(self)}
