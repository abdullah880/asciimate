"""Small, dependency-free helper functions used across the project."""

from __future__ import annotations

import math
from typing import Tuple


def clamp(value: float, low: float, high: float) -> float:
    """Clamp *value* into the inclusive range ``[low, high]``."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between *a* and *b* by factor *t* in [0, 1]."""
    return a + (b - a) * clamp(t, 0.0, 1.0)


def ease_in_out_cubic(t: float) -> float:
    """Smooth ease-in/ease-out curve, good for natural-looking reveals."""
    t = clamp(t, 0.0, 1.0)
    if t < 0.5:
        return 4 * t * t * t
    return 1 - ((-2 * t + 2) ** 3) / 2


def ease_out_cubic(t: float) -> float:
    """Decelerating ease-out curve."""
    t = clamp(t, 0.0, 1.0)
    return 1 - (1 - t) ** 3


def compute_ascii_dimensions(
    img_w: int,
    img_h: int,
    output_width: int,
    output_height: int,
    char_aspect: float,
    max_width: int,
    max_height: int,
) -> Tuple[int, int]:
    """Compute the (cols, rows) character grid for an image.

    Parameters
    ----------
    img_w, img_h:
        Source image pixel dimensions.
    output_width, output_height:
        Requested character dimensions.  ``0`` means "derive automatically".
    char_aspect:
        Width / height of a single character cell.  Monospaced glyphs are
        typically about half as wide as they are tall, so a value around
        0.5 keeps the displayed artwork proportional to the source image.
    max_width, max_height:
        Upper safety limits so that gigantic images never produce an
        unrenderable grid.
    """
    if img_w <= 0 or img_h <= 0:
        return (0, 0)

    source_aspect = img_w / img_h

    if output_width > 0 and output_height > 0:
        cols, rows = output_width, output_height
    elif output_width > 0:
        cols = output_width
        # height_in_chars = cols * (img_h/img_w) * char_aspect
        rows = max(1, round(cols / source_aspect * char_aspect))
    elif output_height > 0:
        rows = output_height
        cols = max(1, round(rows * source_aspect / char_aspect))
    else:
        # Auto: pick a comfortable width and derive the height.
        cols = 160
        rows = max(1, round(cols / source_aspect * char_aspect))

    cols = max(1, min(cols, max_width))
    rows = max(1, min(rows, max_height))
    return cols, rows


def estimate_char_aspect(font_size: int) -> float:
    """Estimate the width/height ratio of a monospaced glyph.

    Most monospaced fonts have an advance width of roughly 0.6 of the em
    size.  We use 0.55 as a safe default that compensates for the visual
    "weight" of characters so the rendered artwork does not look stretched
    vertically.
    """
    return 0.55


def distance(x: float, y: float, cx: float, cy: float) -> float:
    """Euclidean distance between (x, y) and (cx, cy)."""
    return math.hypot(x - cx, y - cy)


def human_list(items) -> str:
    """Join items into a human-friendly comma/``or`` list."""
    items = [str(i) for i in items]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " or " + items[-1]
