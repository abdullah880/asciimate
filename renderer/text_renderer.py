"""Glyph caching and frame compositing.

:class:`GlyphCache` renders each character once (in white) and then tints it
on demand, caching the result.  Because colours are quantised to the web-safe
palette in "original colour" mode, the cache stays tiny (at most
``len(ramp) * 216`` surfaces) while still covering every colour the image can
produce.

:class:`FrameCompositor` owns the offscreen surface that holds the current
ASCII frame.  It performs **incremental** updates: every frame it compares the
new ``(char_indices, packed_colors)`` state against the previous one and only
re-clears and re-blits the cells that actually changed.  This is what makes
progressive / scan / wave / centre reveals essentially free per frame, and
keeps the matrix flicker bounded to the active decode band.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pygame

from renderer.color_manager import pack_rgb, quantize_array

# Sentinel stored in ``last_chars`` before the first frame so the initial diff
# forces a full redraw.
_NEVER = -999


class GlyphCache:
    """Build and cache monospaced glyph surfaces, tinted to any colour."""

    def __init__(self, ramp: str, font: pygame.font.Font) -> None:
        self.ramp = ramp
        self.font = font
        self._white: dict[int, pygame.Surface] = {}
        self._sizes: dict[int, Tuple[int, int]] = {}
        self._colored: dict[Tuple[int, int], pygame.Surface] = {}

    def _white_glyph(self, idx: int) -> pygame.Surface:
        glyph = self._white.get(idx)
        if glyph is None:
            ch = self.ramp[idx]
            glyph = self.font.render(ch, True, (255, 255, 255)).convert_alpha()
            self._white[idx] = glyph
            self._sizes[idx] = glyph.get_size()
        return glyph

    def size(self, idx: int) -> Tuple[int, int]:
        self._white_glyph(idx)
        return self._sizes[idx]

    def get(self, idx: int, packed_color: int) -> pygame.Surface:
        key = (idx, packed_color)
        glyph = self._colored.get(key)
        if glyph is None:
            white = self._white_glyph(idx)
            glyph = white.copy()
            r = (packed_color >> 16) & 0xFF
            g = (packed_color >> 8) & 0xFF
            b = packed_color & 0xFF
            # Multiply white pixels by the target colour; alpha is preserved so
            # anti-aliasing edges remain smooth.
            glyph.fill((r, g, b, 255), special_flags=pygame.BLEND_RGBA_MULT)
            self._colored[key] = glyph
        return glyph


class FrameCompositor:
    """Composite ASCII frames onto a persistent offscreen surface."""

    def __init__(
        self,
        ramp: str,
        cols: int,
        rows: int,
        font: pygame.font.Font,
        cell_w: int,
        cell_h: int,
        color_mode: str,
        foreground: Tuple[int, int, int],
    ) -> None:
        self.ramp = ramp
        self.cols = cols
        self.rows = rows
        self.font = font
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.color_mode = color_mode
        self.foreground = foreground

        self.width = cols * cell_w
        self.height = rows * cell_h
        self.frame = pygame.Surface((self.width, self.height), pygame.SRCALPHA).convert_alpha()

        self.cache = GlyphCache(ramp, font)

        # Per-character cell centring offsets, indexed by char index.
        n = len(ramp)
        self._dx = np.zeros(n, dtype=np.int32)
        self._dy = np.zeros(n, dtype=np.int32)
        for i in range(n):
            gw, gh = self.cache.size(i)
            self._dx[i] = (cell_w - gw) // 2
            self._dy[i] = (cell_h - gh) // 2

        # Packed foreground for monochrome mode (used for every cell).
        fr, fg, fb = foreground
        self._packed_fg = (fr << 16) | (fg << 8) | fb

        self.last_chars = np.full((rows, cols), _NEVER, dtype=np.int32)
        self.last_packed = np.zeros((rows, cols), dtype=np.uint32)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------
    def set_color_mode(self, mode: str, foreground: Tuple[int, int, int]) -> None:
        """Switch colour mode; forces a full redraw on the next composite."""
        changed = mode != self.color_mode or foreground != self.foreground
        self.color_mode = mode
        self.foreground = foreground
        fr, fg, fb = foreground
        self._packed_fg = (fr << 16) | (fg << 8) | fb
        if changed:
            self.invalidate()

    def invalidate(self) -> None:
        """Force the next :meth:`composite` call to redraw everything."""
        self.last_chars[:] = _NEVER

    def rebuild(self) -> None:
        """Recreate the offscreen surface (e.g. after a font/grid change)."""
        self.frame = pygame.Surface((self.width, self.height), pygame.SRCALPHA).convert_alpha()
        self.invalidate()

    # ------------------------------------------------------------------
    # Compositing
    # ------------------------------------------------------------------
    def _packed_colors(self, colors: np.ndarray) -> np.ndarray:
        if self.color_mode == "original":
            return pack_rgb(quantize_array(colors))
        # Monochrome: every cell shares the (exact) foreground colour.
        return np.full((self.rows, self.cols), self._packed_fg, dtype=np.uint32)

    def composite(self, chars: np.ndarray, colors: np.ndarray) -> pygame.Surface:
        """Update the offscreen surface for the given frame and return it.

        Uses a diff against the previously drawn state so that only cells
        which actually changed are re-cleared and re-blitted.  When every cell
        changed (common for the fade mode, or on the first frame) it takes the
        fast path of a single full-surface clear followed by one batched
        ``blits()`` call.
        """
        packed = self._packed_colors(colors)
        total = self.rows * self.cols

        if self.last_chars[0, 0] == _NEVER:
            changed = np.ones((self.rows, self.cols), dtype=bool)
        else:
            changed = (chars != self.last_chars) | (packed != self.last_packed)

        n_changed = int(changed.sum())
        if n_changed == 0:
            return self.frame

        full = n_changed == total
        if full:
            # One cheap full clear, then blit every visible cell.
            self.frame.fill((0, 0, 0, 0))
            coords = np.argwhere(chars >= 0)
        else:
            coords = np.argwhere(changed)
            # Clear only the changed cells.
            cw, ch = self.cell_w, self.cell_h
            for r, c in coords:
                self.frame.fill(
                    (0, 0, 0, 0),
                    pygame.Rect(int(c) * cw, int(r) * ch, cw, ch),
                )

        # Batch all glyph blits into a single C-level call for speed.
        cw, ch = self.cell_w, self.cell_h
        blit_list: List[Tuple[pygame.Surface, Tuple[int, int]]] = []
        for r, c in coords:
            idx = int(chars[r, c])
            if idx < 0:
                continue  # HIDDEN cell -> leave it cleared
            glyph = self.cache.get(idx, int(packed[r, c]))
            x = int(c) * cw + int(self._dx[idx])
            y = int(r) * ch + int(self._dy[idx])
            blit_list.append((glyph, (x, y)))
        if blit_list:
            self.frame.blits(blit_list)

        # Update the cached state.
        if full:
            self.last_chars[:] = chars
            self.last_packed[:] = packed
        else:
            self.last_chars[changed] = chars[changed]
            self.last_packed[changed] = packed[changed]
        return self.frame
