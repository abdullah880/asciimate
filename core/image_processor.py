"""Image processing: resize, tone adjustments, grayscale, edge enhancement.

Everything here operates on NumPy arrays for speed.  The pipeline is
deliberately stateless: :func:`process` takes a PIL image plus the
configuration and returns the small per-cell colour and brightness arrays
that the ASCII converter needs.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
from PIL import Image, ImageFilter

from config import AppConfig


def resize_for_ascii(image: Image.Image, cols: int, rows: int) -> Image.Image:
    """Resize *image* so that each output pixel corresponds to one ASCII cell.

    PIL uses ``(width, height)`` ordering, which maps directly to
    ``(cols, rows)``.  LANCZOS gives clean down-sampling; for the rare case of
    up-scaling a tiny image it still produces acceptable results.
    """
    cols = max(1, int(cols))
    rows = max(1, int(rows))
    if image.size == (cols, rows):
        return image
    return image.resize((cols, rows), resample=Image.LANCZOS)


def _apply_tone(rgb_float: np.ndarray, cfg: AppConfig) -> np.ndarray:
    """Apply brightness / contrast / gamma to a float RGB array (0..255)."""
    # Brightness is a simple multiplicative gain.
    if cfg.brightness != 1.0:
        rgb_float = rgb_float * cfg.brightness

    # Contrast pivots around mid-grey (128).
    if cfg.contrast != 1.0:
        rgb_float = (rgb_float - 128.0) * cfg.contrast + 128.0

    # Gamma operates in linear-normalised space.
    if cfg.gamma != 1.0:
        normalised = np.clip(rgb_float / 255.0, 0.0, 1.0)
        rgb_float = 255.0 * np.power(normalised, cfg.gamma)

    return rgb_float


def _sobel_edges(gray_uint8: np.ndarray) -> np.ndarray:
    """Return a normalised edge-magnitude map (0..255) for *gray_uint8*.

    Uses Pillow's highly optimised FIND_EDGES filter (a Sobel-based operator)
    for speed, then normalises to the full range so the strength is
    predictable regardless of image content.
    """
    edges_img = Image.fromarray(gray_uint8).filter(ImageFilter.FIND_EDGES)
    edges = np.asarray(edges_img, dtype=np.float32)
    peak = float(edges.max())
    if peak > 1e-6:
        edges = edges * (255.0 / peak)
    return edges


def process(
    image: Image.Image, cfg: AppConfig, cols: int, rows: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Produce the per-cell colour and brightness arrays.

    Parameters
    ----------
    image:
        Source RGB PIL image at full resolution.
    cfg:
        Application configuration (brightness/contrast/gamma/edge_enhance...).
    cols, rows:
        Character-grid dimensions the image should be sampled to.

    Returns
    -------
    rgb_small : np.ndarray
        ``(rows, cols, 3)`` ``uint8`` array of per-cell colours (tone-adjusted
        but otherwise faithful to the source).  Used for original-colour
        rendering.
    gray_norm : np.ndarray
        ``(rows, cols)`` ``float32`` array in ``[0, 1]`` giving the brightness
        used to select an ASCII character.  Edge-enhanced when requested.
    """
    small = resize_for_ascii(image, cols, rows)

    # Work in float for tone math, then snap back to uint8 for colour output.
    rgb_float = np.asarray(small, dtype=np.float32)
    if rgb_float.ndim != 3 or rgb_float.shape[2] != 3:
        # Defensive: ensure 3 channels even for exotic inputs.
        rgb_float = np.asarray(small.convert("RGB"), dtype=np.float32)

    rgb_float = _apply_tone(rgb_float, cfg)
    rgb_small = np.clip(rgb_float, 0.0, 255.0).astype(np.uint8)

    # Perceptual luminance (Rec. 601 weights) for brightness mapping.
    gray_uint8 = (
        0.299 * rgb_small[:, :, 0]
        + 0.587 * rgb_small[:, :, 1]
        + 0.114 * rgb_small[:, :, 2]
    ).astype(np.float32)

    if cfg.edge_enhance:
        edges = _sobel_edges(gray_uint8.astype(np.uint8))
        # Blend edges into brightness so outlines map to denser characters.
        # The 1.6 weight emphasises structure without blowing out midtones.
        gray_uint8 = np.clip(gray_uint8 + edges * 1.6, 0.0, 255.0)

    gray_norm = np.clip(gray_uint8 / 255.0, 0.0, 1.0).astype(np.float32)
    return rgb_small, gray_norm
