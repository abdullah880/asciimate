"""Colour helpers: theme presets and palette quantisation.

In "original colour" mode each cell may have a unique colour, which would
make per-(char, colour) glyph caching explode.  We therefore quantise colours
to the 6-level web-safe palette (216 colours) so the glyph cache stays small
while still preserving the image's general colour mood.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from config import THEMES

# 6 evenly spaced levels -> the classic web-safe palette (6^3 = 216 colours).
_LEVEL_DIV = 51.0


def quantize_color(color) -> Tuple[int, int, int]:
    """Quantise a single ``(r, g, b)`` colour to the web-safe palette."""
    arr = np.asarray(color, dtype=np.float32).flatten()
    levels = np.clip(np.round(arr / _LEVEL_DIV), 0, 5).astype(np.uint8)
    q = (levels * 51).tolist()
    return (int(q[0]), int(q[1]), int(q[2]))


def quantize_array(colors: np.ndarray) -> np.ndarray:
    """Vectorised web-safe quantisation of an ``(r, c, 3)`` uint8 array."""
    levels = np.clip(np.round(colors.astype(np.float32) / _LEVEL_DIV), 0, 5).astype(np.uint8)
    return levels * 51


def pack_rgb(colors: np.ndarray) -> np.ndarray:
    """Pack an ``(r, c, 3)`` uint8 array into an ``(r, c)`` uint32 array."""
    r = colors[:, :, 0].astype(np.uint32)
    g = colors[:, :, 1].astype(np.uint32)
    b = colors[:, :, 2].astype(np.uint32)
    return (r << 16) | (g << 8) | b


def unpack_rgb(packed: int) -> Tuple[int, int, int]:
    return ((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)


def resolve_theme(name: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """Return ``(foreground, background)`` for a theme name (with fallback)."""
    if name in THEMES:
        return THEMES[name]
    return THEMES["green"]


def theme_names() -> list:
    return list(THEMES.keys())
