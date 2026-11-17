"""Convert a processed image into a compact ASCII representation.

The converter runs **once** (before animation begins) and produces an
:class:`AsciiArt` object that the animation engine and renderer reuse on every
frame.  This keeps the per-frame work cheap, which is essential for smooth
60 FPS playback.

Mapping convention
------------------
The character ramp is stored densest-first (e.g. ``"@%#*+=-:. "``).  Because
the renderer draws light characters on a dark background, *bright* image
pixels must select the **densest** character so that bright regions actually
look bright (more ink == more light).  The ``invert`` option reverses this,
producing the classic "dark pixel -> dense character" paper/negative look.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config import AppConfig
from core import image_processor
from utils.helpers import compute_ascii_dimensions, estimate_char_aspect


@dataclass
class AsciiArt:
    """A fully converted image ready to be animated and rendered."""

    cols: int
    rows: int
    char_indices: np.ndarray   # (rows, cols) int32 indices into ``ramp``
    colors: np.ndarray         # (rows, cols, 3) uint8 source colours
    brightness: np.ndarray     # (rows, cols) float32 in [0, 1] (post-process)
    ramp: str

    @property
    def cell_count(self) -> int:
        return self.cols * self.rows

    def char_at(self, row: int, col: int) -> str:
        """Return the source character for a cell (ignoring animation state)."""
        return self.ramp[int(self.char_indices[row, col])]


def convert(image, cfg: AppConfig) -> AsciiArt:
    """Convert *image* (a PIL image) into an :class:`AsciiArt` using *cfg*."""
    img_w, img_h = image.size

    char_aspect = estimate_char_aspect(cfg.font_size)
    cols, rows = compute_ascii_dimensions(
        img_w,
        img_h,
        cfg.output_width,
        cfg.output_height,
        char_aspect,
        cfg.max_width,
        cfg.max_height,
    )

    rgb_small, gray_norm = image_processor.process(image, cfg, cols, rows)

    ramp = cfg.char_ramp or "@%#*+=-:. "
    n = len(ramp)
    if n < 2:
        # A single-character ramp would make every cell identical; pad it so
        # the math stays general.
        ramp = ramp + " "
        n = len(ramp)

    # ``mapped`` is the "ink amount" we want: 0 == densest char, 1 == sparsest.
    # Default: brighter pixels get more ink -> mapped near 0.
    if cfg.invert:
        mapped = gray_norm.copy()
    else:
        mapped = 1.0 - gray_norm

    idx = np.clip(np.round(mapped * (n - 1)), 0, n - 1).astype(np.int32)

    return AsciiArt(
        cols=cols,
        rows=rows,
        char_indices=idx,
        colors=rgb_small.copy(),
        brightness=gray_norm.copy(),
        ramp=ramp,
    )
