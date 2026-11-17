"""Pygame-based renderer: window, main loop, input and presentation.

This module ties everything together at runtime:

* it owns the :class:`FrameCompositor` that paints the current frame,
* it drives the :class:`AnimationEngine` with real delta-time,
* it handles all keyboard controls listed in the README,
* it scales/centres the artwork into a resizable window and draws the
  optional information panel, scan-line decoration and bloom glow, and
* it can record the animation to an MP4 video at a configurable frame
  rate (default 60 FPS) with a title overlay burned into every frame.
"""

from __future__ import annotations

import os
import re
import sys
import time

import numpy as np
import pygame

from config import AppConfig, MODE_NAMES
from core import ascii_converter
from core.animation_engine import AnimationEngine
from core.ascii_converter import AsciiArt
from renderer.color_manager import resolve_theme, theme_names
from renderer.text_renderer import FrameCompositor


class PygameRenderer:
    """Top-level application controller."""

    def __init__(
        self,
        art: AsciiArt,
        engine: AnimationEngine,
        cfg: AppConfig,
        image,
        filename: str,
    ) -> None:
        self.art = art
        self.engine = engine
        self.cfg = cfg
        self.image = image
        self.filename = filename

        # --- Fonts ----------------------------------------------------------
        self.font = self._load_font(cfg.font_path, cfg.font_size)
        # Monospaced advance measured from a representative glyph.
        self.cell_w, self.cell_h = self.font.size("M")
        self.info_font = self._load_font(cfg.font_path, max(10, cfg.font_size - 4))
        # A slightly larger, prominent font for the video title overlay.
        self.title_font = self._load_font(cfg.font_path, max(18, cfg.font_size + 6))

        # --- Window (must exist before any convert_alpha() call) -----------
        art_w = art.cols * self.cell_w
        art_h = art.rows * self.cell_h
        win_w = cfg.window_width or art_w
        win_h = cfg.window_height or art_h
        win_w = max(win_w, 360)
        win_h = max(win_h, 260)
        flags = pygame.RESIZABLE if cfg.resizable else 0
        self.screen = pygame.display.set_mode((win_w, win_h), flags)
        pygame.display.set_caption(f"Animated ASCII Renderer - {filename}")

        # --- Compositor (now that the display format is known) -------------
        self.compositor = FrameCompositor(
            ramp=art.ramp,
            cols=art.cols,
            rows=art.rows,
            font=self.font,
            cell_w=self.cell_w,
            cell_h=self.cell_h,
            color_mode=cfg.color_mode,
            foreground=cfg.foreground_color,
        )

        self.clock = pygame.time.Clock()
        self.show_info = cfg.show_info_panel
        self.running = True
        self.fps = 0.0
        self._theme_index = theme_names().index(cfg.theme) if cfg.theme in theme_names() else 0

        # --- Title + recording state --------------------------------------
        self.title = cfg.title or filename
        # The video writer is created lazily when recording starts so the
        # application runs fine even if imageio is not installed.
        self.recording = False
        self.video_writer = None
        self.rec_path = ""
        self.rec_start_ticks = 0
        self.rec_frames = 0
        # Transient on-screen messages ("Recording started", "Saved ...", ...).
        self.flash_text = ""
        self.flash_until = 0

        # --- Auto-record (set by --record) -------------------------------
        # 0.0 = disabled; -1.0 = until animation finishes + hold; >0 = seconds.
        self.auto_record = cfg.record_seconds != 0.0
        self.auto_record_seconds = cfg.record_seconds
        self.auto_rec_elapsed = 0.0
        self._finished_at = None
        # Time accumulator that decouples the capture rate from the render
        # rate so the video is always real-time at ``record_fps``.
        self._capture_accum = 0.0
        self._last_dt = 1.0 / max(cfg.target_fps, 1)

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _load_font(path: str, size: int) -> pygame.font.Font:
        if path and os.path.isfile(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass
        # Fall back to a system monospaced font, then pygame's default.
        return pygame.font.SysFont(
            "dejavusansmono,consolas,couriernew,courier,monospace", size
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        try:
            if self.auto_record:
                # ``--record``: start capturing immediately on launch.
                self._start_recording()
                if not self.recording:
                    # imageio missing or the writer failed to open.
                    print("error: could not start recording "
                          "(is imageio installed?).", file=sys.stderr)
                    self.running = False
            while self.running:
                # Delta time, clamped so a pause in the debugger or a slow
                # frame never makes the animation jump absurdly far.
                dt = self.clock.tick(self.cfg.target_fps) / 1000.0
                dt = min(dt, 1.0 / 15.0)

                self._handle_events()
                self.engine.update(dt)
                self._last_dt = dt
                self._draw()
                self.fps = self.clock.get_fps()

                # Auto-record stop / quit logic.
                if self.auto_record and self.recording:
                    self.auto_rec_elapsed += dt
                    if self._should_auto_stop():
                        self._stop_recording()
                        self.running = False
        finally:
            # Make sure any in-progress recording is finalised cleanly so the
            # MP4 file is not left half-written.
            self._stop_recording()
            pygame.quit()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._stop_recording()
                self.running = False
            elif event.type == pygame.VIDEORESIZE:
                if self.recording:
                    # The video writer needs a constant frame size.
                    self._set_flash("Stop recording to resize", 1.5)
                else:
                    flags = pygame.RESIZABLE if self.cfg.resizable else 0
                    self.screen = pygame.display.set_mode(
                        (max(event.w, 360), max(event.h, 260)), flags
                    )
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event.key)

    def _handle_key(self, key: int) -> None:
        cfg = self.cfg
        if key == pygame.K_ESCAPE:
            self._stop_recording()
            self.running = False
        elif key == pygame.K_SPACE:
            self.engine.toggle_pause()
        elif key == pygame.K_r:
            self.engine.restart()
            self.compositor.invalidate()
        elif key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                     pygame.K_5, pygame.K_6, pygame.K_7):
            mode = key - pygame.K_0
            self.engine.set_mode(mode)
            self.compositor.invalidate()
        elif key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.engine.adjust_speed(0.25)
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.engine.adjust_speed(-0.25)
        elif key == pygame.K_c:
            new_mode = self.engine.toggle_color_mode()
            self.compositor.set_color_mode(new_mode, self.engine.foreground)
        elif key == pygame.K_i:
            cfg.invert = not cfg.invert
            self.art = ascii_converter.convert(self.image, cfg)
            self.engine.replace_art(self.art)
            self.compositor.invalidate()
        elif key == pygame.K_h:
            self.show_info = not self.show_info
        elif key == pygame.K_t:
            names = theme_names()
            self._theme_index = (self._theme_index + 1) % len(names)
            fg, bg = resolve_theme(names[self._theme_index])
            cfg.theme = names[self._theme_index]
            cfg.foreground_color = fg
            cfg.background_color = bg
            self.engine.set_foreground(fg)
            self.engine.background = bg
            self.compositor.set_color_mode(self.engine.color_mode, fg)
        elif key == pygame.K_g:
            cfg.glow = not cfg.glow
        elif key == pygame.K_s:
            self._save_screenshot()
        elif key == pygame.K_v:
            if self.recording:
                self._stop_recording()
            else:
                self._start_recording()

    def _output_dir(self) -> str:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")

    def _save_screenshot(self) -> None:
        out_dir = self._output_dir()
        os.makedirs(out_dir, exist_ok=True)
        name = f"screenshot_{int(time.time())}.png"
        try:
            pygame.image.save(self.screen, os.path.join(out_dir, name))
            self._set_flash(f"Saved {name}", 2.0)
        except Exception as exc:
            self._set_flash(f"save failed: {exc}", 2.5)

    # ------------------------------------------------------------------
    # Video recording (V key)
    # ------------------------------------------------------------------
    def _start_recording(self) -> None:
        """Begin capturing frames to an MP4 file at ``cfg.record_fps`` FPS."""
        try:
            import imageio.v2 as imageio  # type: ignore
        except ImportError:
            self._set_flash("pip install imageio imageio-ffmpeg", 4.0)
            return
        title = self.title or self.filename or "ascii"
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") or "ascii"
        out_dir = self._output_dir()
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{safe}_{int(time.time())}.mp4")
        try:
            self.video_writer = imageio.get_writer(
                path,
                fps=self.cfg.record_fps,
                codec="libx264",
                # CRF 20 is a good quality/size balance; imageio's ffmpeg
                # writer already defaults to the broadly-compatible yuv420p
                # pixel format, so we do not duplicate it here.
                output_params=["-crf", "20"],
                macro_block_size=1,
            )
        except Exception as exc:
            self.video_writer = None
            self._set_flash(f"record start failed: {exc}", 3.0)
            return
        self.recording = True
        self.rec_path = path
        self.rec_start_ticks = pygame.time.get_ticks()
        self.rec_frames = 0
        self._set_flash(f"Recording @ {self.cfg.record_fps} fps", 1.5)

    def _stop_recording(self) -> None:
        """Finalise and close the current recording (if any)."""
        if not self.recording:
            return
        self.recording = False
        writer = self.video_writer
        self.video_writer = None
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        if self.rec_frames > 0:
            self._set_flash(
                f"Saved {self.rec_frames} frames -> {os.path.basename(self.rec_path)}",
                4.0,
            )
            # In scripted (--record) mode, print the result so it can be
            # captured by shell pipelines.
            if self.auto_record:
                print(
                    f"Saved video: {self.rec_path} "
                    f"({self.rec_frames} frames @ {self.cfg.record_fps} fps)",
                    flush=True,
                )

    def _should_auto_stop(self) -> bool:
        """Decide whether an auto-recording (--record) should stop now."""
        if self.auto_record_seconds > 0.0:
            # Fixed duration requested.
            return self.auto_rec_elapsed >= self.auto_record_seconds
        # Sentinel -1.0: hold one second past the animation finishing so the
        # completed frame is captured cleanly before the file closes.
        if self.engine.finished:
            if self._finished_at is None:
                self._finished_at = self.auto_rec_elapsed
            return self.auto_rec_elapsed >= self._finished_at + 1.0
        return False

    def _capture_frame(self) -> None:
        """Grab the current screen into the video writer (single frame)."""
        if self.video_writer is None:
            return
        try:
            # pygame surfarray is indexed (x, y); video frames are (y, x).
            arr = pygame.surfarray.array3d(self.screen)
            arr = np.transpose(arr, (1, 0, 2))
            h, w = arr.shape[0], arr.shape[1]
            # libx264 with yuv420p requires even dimensions.
            if h % 2:
                h -= 1
            if w % 2:
                w -= 1
            self.video_writer.append_data(np.ascontiguousarray(arr[:h, :w]))
            self.rec_frames += 1
        except Exception as exc:
            self._set_flash(f"record error: {exc}", 3.0)
            self._stop_recording()

    def _capture_at_steady_fps(self) -> None:
        """Capture frames at ``cfg.record_fps`` regardless of the render rate.

        A time accumulator decides how many frames to grab this iteration: a
        fast render loop skips captures (avoiding wasted work) while a slow
        one duplicates the latest frame, so the saved video always plays back
        in real time at exactly the requested frame rate.  Captures per
        iteration are capped so a single slow frame cannot stall the loop.
        """
        if self.video_writer is None:
            return
        interval = 1.0 / max(self.cfg.record_fps, 1)
        self._capture_accum += self._last_dt
        captures = 0
        while self._capture_accum >= interval and captures < 2:
            self._capture_frame()
            self._capture_accum -= interval
            captures += 1
        # Drop any large backlog (e.g. the program was paused) so we do not
        # spiral into a cascade of catch-up captures.
        if self._capture_accum > interval * 2:
            self._capture_accum = 0.0

    def _set_flash(self, text: str, seconds: float = 2.0) -> None:
        """Show a transient message near the bottom of the window."""
        self.flash_text = text
        self.flash_until = pygame.time.get_ticks() + int(seconds * 1000)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def _draw(self) -> None:
        cfg = self.cfg
        self.screen.fill(cfg.background_color)

        chars, colors = self.engine.get_frame()
        frame = self.compositor.composite(chars, colors)

        fw, fh = frame.get_size()
        sw, sh = self.screen.get_size()
        scale = min(sw / fw, sh / fh) if fw and fh else 1.0

        if scale < 1.0:
            display = pygame.transform.smoothscale(
                frame, (max(1, int(fw * scale)), max(1, int(fh * scale)))
            )
        else:
            display = frame

        dw, dh = display.get_size()
        pos = ((sw - dw) // 2, (sh - dh) // 2)

        if cfg.glow:
            self._blit_glow(display, pos)
        self.screen.blit(display, pos)

        self._draw_decorations(pos, (dw, dh))
        if self.recording:
            # Burn the title into the frame, capture at a steady record_fps,
            # then add the live-only REC indicator on top so the recording
            # stays clean.
            self._draw_title()
            self._capture_at_steady_fps()
            self._draw_rec_indicator()
        elif self.show_info:
            self._draw_info_panel((dw, dh))
        self._draw_flash()
        pygame.display.flip()

    def _blit_glow(self, surface: pygame.Surface, pos) -> None:
        """Add a soft additive bloom around bright glyphs."""
        w, h = surface.get_size()
        if w < 4 or h < 4:
            return
        small = pygame.transform.smoothscale(surface, (max(1, w // 3), max(1, h // 3)))
        glow = pygame.transform.smoothscale(small, (w, h))
        # Halve the intensity so the bloom stays subtle.
        glow.fill((120, 120, 120), special_flags=pygame.BLEND_RGB_MULT)
        self.screen.blit(glow, pos, special_flags=pygame.BLEND_RGB_ADD)

    def _draw_decorations(self, pos, size) -> None:
        dec = self.engine.decorations()
        if "scan_row" in dec:
            _, dh = size
            sr = dec["scan_row"]
            y = pos[1] + int(sr * dh / max(self.art.rows, 1))
            x0, x1 = pos[0], pos[0] + size[0]
            # A bright leading line with a faint trailing ghost.
            pygame.draw.line(self.screen, self.cfg.foreground_color, (x0, y), (x1, y), 1)
            ghost = tuple(min(255, c // 3) for c in self.cfg.foreground_color)
            pygame.draw.line(self.screen, ghost, (x0, y - 2), (x1, y - 2), 1)

    # ------------------------------------------------------------------
    # Information panel
    # ------------------------------------------------------------------
    def _draw_info_panel(self, art_size) -> None:
        cfg = self.cfg
        eng = self.engine
        lines = [
            f"File:   {self.filename}",
            f"Mode:   {MODE_NAMES.get(eng.mode, '?')}  [{eng.mode}/7]",
            f"Progress: {eng.progress * 100:5.1f}%",
            f"FPS:    {self.fps:5.1f}",
            f"Size:   {self.art.cols} x {self.art.rows} chars  ({art_size[0]}x{art_size[1]} px)",
            f"Color:  {eng.color_mode}   Theme: {cfg.theme}",
            f"Speed:  {eng.speed:.2f}x   Glow: {'on' if cfg.glow else 'off'}",
            f"State:  {'PAUSED' if eng.paused else ('DONE' if eng.finished else 'PLAYING')}",
            "Keys: SPACE pause | R restart | 1-7 mode | +/- speed",
            "      C color | I invert | H hide | T theme | G glow",
            "      S screenshot | V record video | ESC quit",
        ]

        line_h = self.info_font.get_height()
        pad = 8
        panel_w = 0
        for line in lines:
            w, _ = self.info_font.size(line)
            panel_w = max(panel_w, w)
        panel_w += pad * 2
        panel_h = line_h * len(lines) + pad * 2

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 170))
        pygame.draw.rect(panel, cfg.foreground_color, panel.get_rect(), 1)

        fg = cfg.foreground_color
        for i, line in enumerate(lines):
            text = self.info_font.render(line, True, fg)
            panel.blit(text, (pad, pad + i * line_h))

        self.screen.blit(panel, (10, 10))

    # ------------------------------------------------------------------
    # Title overlay + REC indicator (recording)
    # ------------------------------------------------------------------
    def _draw_title(self) -> None:
        """Draw the video title banner at the top-centre of the window."""
        title = self.title
        if not title:
            return
        text = self.title_font.render(title, True, (235, 235, 235))
        tw, th = text.get_size()
        pad_x, pad_y = 14, 6
        rect = pygame.Rect(0, 0, tw + pad_x * 2, th + pad_y * 2)
        rect.centerx = self.screen.get_width() // 2
        rect.top = 10
        banner = pygame.Surface(rect.size, pygame.SRCALPHA)
        banner.fill((0, 0, 0, 170))
        pygame.draw.rect(banner, (235, 235, 235), banner.get_rect(), 1)
        self.screen.blit(banner, rect.topleft)
        self.screen.blit(text, (rect.x + pad_x, rect.y + pad_y))

    def _draw_rec_indicator(self) -> None:
        """Draw a live-only 'REC mm:ss' indicator at the top-right corner."""
        elapsed = (pygame.time.get_ticks() - self.rec_start_ticks) / 1000.0
        mm = int(elapsed // 60)
        ss = int(elapsed % 60)
        label = f"REC  {mm:02d}:{ss:02d}"
        text = self.info_font.render(label, True, (255, 90, 90))
        sw = self.screen.get_width()
        pad = 12
        x = sw - text.get_width() - pad - 12
        y = pad + 2
        pygame.draw.circle(
            self.screen, (255, 60, 60), (x - 10, y + text.get_height() // 2), 6
        )
        self.screen.blit(text, (x, y))

    def _draw_flash(self) -> None:
        """Draw a transient status message at the bottom-centre."""
        if not self.flash_text:
            return
        if pygame.time.get_ticks() >= self.flash_until:
            self.flash_text = ""
            return
        text = self.info_font.render(self.flash_text, True, (240, 240, 240))
        pad_x, pad_y = 12, 6
        rect = pygame.Rect(
            0, 0, text.get_width() + pad_x * 2, text.get_height() + pad_y * 2
        )
        rect.centerx = self.screen.get_width() // 2
        rect.bottom = self.screen.get_height() - 12
        banner = pygame.Surface(rect.size, pygame.SRCALPHA)
        banner.fill((0, 0, 0, 180))
        pygame.draw.rect(banner, (240, 240, 240), banner.get_rect(), 1)
        self.screen.blit(banner, rect.topleft)
        self.screen.blit(text, (rect.x + pad_x, rect.y + pad_y))
