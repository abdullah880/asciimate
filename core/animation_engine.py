"""The animation engine.

The engine owns the converted :class:`AsciiArt` and, given the elapsed time,
produces per-frame ``(char_indices, colors)`` arrays that the renderer paints.
All seven animation modes share a single, unified model:

    alpha(row, col) = clamp((progress - threshold) / window, 0, 1)

* ``threshold`` is a per-cell value in ``[0, 1]`` describing *when* the cell
  should begin to appear.  Its shape depends on the mode (diagonal sweep,
  random order, distance from the centre, a travelling sine wave, ...).
* ``window`` is how long (in normalised progress) a cell takes to fade from
  invisible to fully visible, which makes every reveal smooth instead of a
  hard pop-in.
* Thresholds are normalised to ``[0, 1 - window]`` so the whole image is
  guaranteed to be fully revealed exactly when ``progress`` reaches 1.

This design keeps the per-frame work to a handful of NumPy operations, which
is what lets the renderer stay at 60 FPS even for large grids.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from config import (
    AppConfig,
    MODE_CENTER,
    MODE_FADE,
    MODE_MATRIX,
    MODE_PROGRESSIVE,
    MODE_RANDOM,
    MODE_SCAN,
    MODE_WAVE,
)
from core.ascii_converter import AsciiArt
from utils.helpers import clamp

# Per-mode fade window (in normalised progress units).  Larger values make a
# slower, softer cell fade-in; the matrix window also defines the "decode
# band" width where characters flicker.
_WINDOWS = {
    MODE_PROGRESSIVE: 0.06,
    MODE_RANDOM: 0.08,
    MODE_SCAN: 0.05,
    MODE_CENTER: 0.08,
    MODE_WAVE: 0.10,
    MODE_MATRIX: 0.25,
    # A window of 1.0 makes the fade uniform across all cells: every cell's
    # alpha equals the global progress, so the whole image develops together.
    MODE_FADE: 1.00,
}

# Sentinel meaning "draw nothing in this cell" (used by the renderer).
HIDDEN = -1


class AnimationEngine:
    """Drive the progressive reveal of an :class:`AsciiArt`."""

    def __init__(self, art: AsciiArt, cfg: AppConfig) -> None:
        self.art = art
        self.cfg = cfg
        self.rows = art.rows
        self.cols = art.cols

        self.mode = cfg.animation_mode
        self.speed = cfg.animation_speed
        self.color_mode = cfg.color_mode
        self.foreground = cfg.foreground_color
        self.background = cfg.background_color

        self.paused = False
        self.elapsed = 0.0
        self.duration = self._compute_duration()

        # Lazily initialised per-mode data.
        self.thresholds: np.ndarray = np.zeros((self.rows, self.cols), np.float32)
        self.scramble: np.ndarray | None = None

        self._base_colors = self._compute_base_colors()
        self._configure_mode(self.mode)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _compute_duration(self) -> float:
        """Total reveal time, scaled by image size and speed."""
        n = self.art.cell_count
        # Larger images get a little more time so the reveal stays legible.
        size_scale = clamp((n / 4000.0) ** 0.5, 0.5, 2.0)
        duration = self.cfg.base_duration / max(self.speed, 0.05) * size_scale
        return clamp(duration, 1.5, 30.0)

    def _window(self) -> float:
        return _WINDOWS.get(self.mode, 0.08)

    def _compute_base_colors(self) -> np.ndarray:
        """Return the ``(rows, cols, 3)`` uint8 colour array for the current mode."""
        if self.color_mode == "original":
            return self.art.colors.copy()
        fg = np.array(self.foreground, dtype=np.uint8)
        return np.broadcast_to(fg, (self.rows, self.cols, 3)).copy()

    def _compute_thresholds(self, mode: int) -> np.ndarray:
        """Build the per-cell threshold matrix for *mode*."""
        r, c = self.rows, self.cols
        rs = np.arange(r, dtype=np.float32)[:, None]
        cs = np.arange(c, dtype=np.float32)[None, :]

        if mode == MODE_PROGRESSIVE:
            denom_r = max(r - 1, 1)
            denom_c = max(c - 1, 1)
            t = (rs / denom_r + cs / denom_c) / 2.0

        elif mode == MODE_RANDOM:
            flat = np.arange(r * c, dtype=np.float32)
            np.random.shuffle(flat)
            t = flat.reshape(r, c) / max(r * c - 1, 1)

        elif mode == MODE_SCAN:
            row_t = np.arange(r, dtype=np.float32) / max(r - 1, 1)
            t = np.broadcast_to(row_t[:, None], (r, c)).astype(np.float32).copy()

        elif mode == MODE_CENTER:
            cy = (r - 1) / 2.0
            cx = (c - 1) / 2.0
            dist = np.sqrt((rs - cy) ** 2 + (cs - cx) ** 2)
            peak = float(dist.max()) or 1.0
            t = dist / peak

        elif mode == MODE_WAVE:
            denom_c = max(c - 1, 1)
            yc = rs / max(r, 1)
            t = cs / denom_c + 0.30 * np.sin(2.0 * np.pi * 2.0 * yc)
            t = np.clip(t, 0.0, 1.0)

        elif mode == MODE_MATRIX:
            flat = np.arange(r * c, dtype=np.float32)
            np.random.shuffle(flat)
            t = flat.reshape(r, c) / max(r * c - 1, 1)

        elif mode == MODE_FADE:
            # Brighter cells develop first, like a photo print emerging.
            t = 1.0 - self.art.brightness
        else:
            t = np.zeros((r, c), dtype=np.float32)

        t = t.astype(np.float32)
        # Normalise so the last cell finishes exactly at progress == 1.
        window = self._window()
        span = 1.0 - window
        mx = float(t.max())
        if mx > 1e-6:
            t = t * (span / mx)
        else:
            t = np.zeros_like(t)
        return np.clip(t, 0.0, 1.0).astype(np.float32)

    def _configure_mode(self, mode: int) -> None:
        """Reset state for a (possibly new) animation mode."""
        self.mode = mode
        self.thresholds = self._compute_thresholds(mode)
        if mode == MODE_MATRIX:
            ramp_len = len(self.art.ramp)
            self.scramble = np.random.randint(
                0, ramp_len, size=(self.rows, self.cols)
            ).astype(np.int32)
        else:
            self.scramble = None
        self.elapsed = 0.0
        self.paused = False

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------
    @property
    def progress(self) -> float:
        if self.duration <= 0.0:
            return 1.0
        return clamp(self.elapsed / self.duration, 0.0, 1.0)

    @property
    def finished(self) -> bool:
        return self.elapsed >= self.duration

    def update(self, dt: float) -> None:
        """Advance the animation by *dt* seconds (delta-time based)."""
        if self.paused or self.finished:
            return
        self.elapsed = min(self.elapsed + dt, self.duration)

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        return self.paused

    def restart(self) -> None:
        """Re-shuffle and replay the current mode from the beginning."""
        self._configure_mode(self.mode)

    def set_mode(self, mode: int) -> None:
        if mode == self.mode:
            self.restart()
            return
        self._configure_mode(mode)

    def set_speed(self, speed: float) -> None:
        """Change speed without causing a visual jump in progress."""
        old_progress = self.progress
        self.speed = max(0.05, speed)
        self.duration = self._compute_duration()
        self.elapsed = old_progress * self.duration

    def adjust_speed(self, delta: float) -> float:
        self.set_speed(self.speed + delta)
        return self.speed

    def set_color_mode(self, mode: str) -> None:
        if mode not in ("mono", "original") or mode == self.color_mode:
            return
        self.color_mode = mode
        self._base_colors = self._compute_base_colors()

    def toggle_color_mode(self) -> str:
        self.set_color_mode("original" if self.color_mode == "mono" else "mono")
        return self.color_mode

    def set_foreground(self, color) -> None:
        self.foreground = tuple(color)
        if self.color_mode == "mono":
            self._base_colors = self._compute_base_colors()

    def replace_art(self, art: AsciiArt) -> None:
        """Swap in a freshly converted :class:`AsciiArt` (e.g. after invert).

        Dimensions are assumed unchanged; thresholds and base colours are
        rebuilt and the animation restarts so the new mapping is visible.
        """
        self.art = art
        self.rows = art.rows
        self.cols = art.cols
        self._base_colors = self._compute_base_colors()
        self._configure_mode(self.mode)

    # ------------------------------------------------------------------
    # Frame production
    # ------------------------------------------------------------------
    def _blend(self, low, high: np.ndarray, alpha: np.ndarray) -> np.ndarray:
        """Blend between *low* (a 3-tuple) and *high* (r,c,3) by *alpha* (r,c)."""
        a = alpha[..., None].astype(np.float32)
        low_arr = np.array(low, dtype=np.float32)
        out = low_arr * (1.0 - a) + high.astype(np.float32) * a
        return np.clip(out, 0, 255).astype(np.uint8)

    def get_frame(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return ``(char_indices, colors)`` for the current instant.

        ``char_indices`` is ``(rows, cols)`` int32.  ``HIDDEN`` (-1) means the
        cell is currently empty.  ``colors`` is ``(rows, cols, 3)`` uint8 and
        is always valid for every visible cell.
        """
        p = self.progress
        thresholds = self.thresholds
        window = self._window()
        alpha = np.clip((p - thresholds) / window, 0.0, 1.0).astype(np.float32)
        base = self._base_colors

        if self.mode == MODE_FADE:
            # Every cell is present; only its brightness ramps up.
            chars = self.art.char_indices.copy()
            colors = self._blend(self.background, base, alpha)
            return chars, colors

        if self.mode == MODE_MATRIX:
            revealed = alpha >= 1.0
            # Flicker the "decode band" (cells part-way through revealing).
            if not self.paused and not self.finished and self.scramble is not None:
                band = (alpha > 0.0) & (~revealed)
                if band.any():
                    ramp_len = len(self.art.ramp)
                    self.scramble[band] = np.random.randint(
                        0, ramp_len, size=int(band.sum())
                    )
            chars = self.art.char_indices.copy()
            if self.scramble is not None:
                chars[~revealed] = self.scramble[~revealed]
            # Revealed cells are full-bright; unrevealed ones glow faintly so
            # the matrix "rain" is always visible.
            eff_alpha = np.where(
                revealed, 1.0, np.maximum(alpha, 0.12)
            ).astype(np.float32)
            colors = self._blend(self.background, base, eff_alpha)
            return chars, colors

        # Standard reveal modes: hide cells that have not started appearing.
        chars = self.art.char_indices.copy()
        chars[alpha <= 0.0] = HIDDEN
        colors = self._blend(self.background, base, alpha)
        return chars, colors

    # ------------------------------------------------------------------
    # Optional visual decorations (e.g. a moving scan line)
    # ------------------------------------------------------------------
    def decorations(self) -> dict:
        """Return mode-specific overlay hints for the renderer."""
        if self.mode == MODE_SCAN and not self.finished:
            return {"scan_row": float(self.progress * max(self.rows - 1, 0))}
        return {}
