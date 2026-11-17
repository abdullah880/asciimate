"""Animated ASCII Image Renderer - application entry point.

Run from the project root (the ``animated_ascii`` directory)::

    python main.py --image assets/example.jpg

All command-line options have sensible defaults, so the program also works
with no arguments at all once an example image is present.
"""

from __future__ import annotations

import argparse
import sys

import pygame

from config import (
    AppConfig,
    DEFAULT_THEME,
    MODE_NAMES,
    THEMES,
)
from core import ascii_converter, image_loader
from core.animation_engine import AnimationEngine
from renderer.color_manager import resolve_theme
from utils import validators
from utils.validators import ValidationError


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python main.py",
        description="Convert an image into ASCII art and animate its reveal.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument("--image", default="assets/example.jpg",
                   help="Path to the source image (png/jpg/jpeg/bmp/webp).")
    p.add_argument("--width", type=int, default=0,
                   help="ASCII output width in characters (0 = auto).")
    p.add_argument("--height", type=int, default=0,
                   help="ASCII output height in characters (0 = auto).")
    p.add_argument("--ramp", default="default",
                   help="Character ramp: a name (default/dense/minimal/block) "
                        "or a literal ramp string.")
    p.add_argument("--font-path", default="",
                   help="Path to a monospaced TTF/OTF font (default: DejaVu Sans Mono).")
    p.add_argument("--font-size", type=int, default=16,
                   help="Font size in pixels.")
    p.add_argument("--mode", type=int, default=1, choices=list(MODE_NAMES.keys()),
                   help="Animation mode (1=Progressive 2=Random 3=Scan "
                        "4=Center 5=Wave 6=Matrix 7=Fade).")
    p.add_argument("--speed", type=float, default=1.0,
                   help="Animation speed multiplier.")
    p.add_argument("--fps", type=int, default=60,
                   help="Target frames per second.")
    p.add_argument("--color", choices=["mono", "original"], default="original",
                   help="Colour rendering mode (mono uses the theme foreground).")
    p.add_argument("--theme", choices=list(THEMES.keys()), default=DEFAULT_THEME,
                   help="Monochrome colour theme.")
    p.add_argument("--fg", default="",
                   help="Override monochrome foreground as 'r,g,b'.")
    p.add_argument("--bg", default="",
                   help="Override background as 'r,g,b'.")
    p.add_argument("--brightness", type=float, default=1.0,
                   help="Brightness multiplier (0-4).")
    p.add_argument("--contrast", type=float, default=1.0,
                   help="Contrast multiplier (0-4).")
    p.add_argument("--gamma", type=float, default=1.0,
                   help="Gamma correction (0.1-4).")
    p.add_argument("--invert", action="store_true",
                   help="Invert the brightness->character mapping.")
    p.add_argument("--edges", action="store_true",
                   help="Edge-enhance the ASCII output for extra detail.")
    p.add_argument("--window", default="",
                   help="Initial window size as WxH (e.g. 1280x720).")
    p.add_argument("--no-info", action="store_true",
                   help="Hide the information panel at start.")
    p.add_argument("--glow", action="store_true",
                   help="Enable a subtle bloom glow around bright glyphs.")
    p.add_argument("--title", default="",
                   help="Title overlay burned into recorded videos "
                        "(default: the source filename).")
    p.add_argument("--record-fps", type=int, default=60,
                   help="Frame rate for video recording (default 60).")
    p.add_argument("--record", nargs="?", const=-1.0, default=None, type=float,
                   metavar="SECONDS",
                   help="Auto-record on launch and quit when done. Use "
                        "'--record' alone to record until the animation "
                        "finishes, or '--record N' for N seconds.")
    p.add_argument("--max-width", type=int, default=320,
                   help="Hard cap on ASCII width (performance safeguard).")
    p.add_argument("--max-height", type=int, default=200,
                   help="Hard cap on ASCII height (performance safeguard).")
    p.add_argument("--list-modes", action="store_true",
                   help="Print the animation modes and exit.")
    return p


def _parse_color(text: str):
    """Parse an 'r,g,b' string into a tuple of ints, or return None."""
    if not text:
        return None
    try:
        parts = [int(p.strip()) for p in text.split(",")]
    except ValueError:
        raise ValidationError(f"Colour must be 'r,g,b', got {text!r}.")
    if len(parts) != 3 or not all(0 <= p <= 255 for p in parts):
        raise ValidationError(f"Colour channels must be 0-255, got {text!r}.")
    return (parts[0], parts[1], parts[2])


def _parse_window(text: str):
    """Parse a 'WxH' window-size string."""
    if not text:
        return (0, 0)
    try:
        w, h = text.lower().split("x")
        return (int(w), int(h))
    except ValueError:
        raise ValidationError(f"Window must be 'WxH' (e.g. 1280x720), got {text!r}.")


def build_config(args: argparse.Namespace) -> AppConfig:
    """Translate parsed CLI args into a validated :class:`AppConfig`."""
    cfg = AppConfig()
    cfg.image_path = args.image
    cfg.output_width = args.width
    cfg.output_height = args.height
    cfg.char_ramp = validators.validate_ramp_choice(args.ramp)
    cfg.font_path = args.font_path or cfg.font_path
    cfg.font_size = validators.validate_int(args.font_size, "font-size", 6, 96)
    cfg.animation_mode = validators.validate_mode(args.mode)
    cfg.animation_speed = validators.validate_float(args.speed, "speed", 0.05, 16.0)
    cfg.target_fps = validators.validate_int(args.fps, "fps", 15, 240)
    cfg.color_mode = args.color
    cfg.theme = args.theme

    fg, bg = resolve_theme(args.theme)
    cfg.foreground_color = fg
    cfg.background_color = bg
    if args.fg:
        cfg.foreground_color = _parse_color(args.fg)
    if args.bg:
        cfg.background_color = _parse_color(args.bg)

    cfg.brightness = validators.validate_float(args.brightness, "brightness", 0.0, 4.0)
    cfg.contrast = validators.validate_float(args.contrast, "contrast", 0.0, 4.0)
    cfg.gamma = validators.validate_float(args.gamma, "gamma", 0.1, 4.0)
    cfg.invert = args.invert
    cfg.edge_enhance = args.edges

    cfg.window_width, cfg.window_height = _parse_window(args.window)
    cfg.show_info_panel = not args.no_info
    cfg.glow = args.glow
    cfg.title = args.title
    cfg.record_fps = validators.validate_int(args.record_fps, "record-fps", 15, 120)
    if args.record is not None:
        # -1.0 (the bare-flag const) means "until the animation finishes".
        if args.record <= 0.0 and args.record != -1.0:
            raise ValidationError(
                "--record duration must be a positive number of seconds "
                "(or use '--record' alone to record until finished)."
            )
        cfg.record_seconds = float(args.record)
    else:
        cfg.record_seconds = 0.0
    cfg.max_width = validators.validate_int(args.max_width, "max-width", 16, 2048)
    cfg.max_height = validators.validate_int(args.max_height, "max-height", 16, 2048)
    return cfg.clamp()


# ---------------------------------------------------------------------------
# Dimension computation (needs the measured font aspect ratio)
# ---------------------------------------------------------------------------
def _load_font_for_measure(cfg: AppConfig):
    """Load the font early so the character aspect ratio is exact."""
    import os
    path = cfg.font_path
    if path and os.path.isfile(path):
        try:
            return pygame.font.Font(path, cfg.font_size)
        except Exception:
            pass
    return pygame.font.SysFont(
        "dejavusansmono,consolas,couriernew,courier,monospace", cfg.font_size
    )


def _resolve_dimensions(cfg: AppConfig, img_w: int, img_h: int,
                        cell_w: int, cell_h: int) -> tuple[int, int]:
    """Decide the final (cols, rows) grid honouring user overrides + aspect.

    Priority: explicit ``--width``/``--height`` > ``--window`` (fit the window
    at native character size) > a detail-friendly default of 180 columns.
    """
    char_aspect = (cell_w / cell_h) if cell_h else 0.55
    source_aspect = img_w / img_h if img_h else 1.0

    if cfg.output_width > 0 and cfg.output_height > 0:
        cols, rows = cfg.output_width, cfg.output_height
    elif cfg.output_width > 0:
        cols = cfg.output_width
        rows = max(1, round(cols / source_aspect * char_aspect))
    elif cfg.output_height > 0:
        rows = cfg.output_height
        cols = max(1, round(rows * source_aspect / char_aspect))
    elif cfg.window_width > 0:
        # Fit the requested window at native character size.
        cols = max(40, round(cfg.window_width / max(cell_w, 1)))
        rows = max(20, round(cols / source_aspect * char_aspect))
    else:
        # Fully automatic: 180 columns gives enough detail for photographic
        # subjects to remain recognisable on typical displays.
        cols = 180
        rows = max(20, round(cols / source_aspect * char_aspect))

    cols = max(1, min(cols, cfg.max_width))
    rows = max(1, min(rows, cfg.max_height))
    return cols, rows


def _auto_window_size(art_w: int, art_h: int) -> tuple[int, int]:
    """Pick a screen-friendly default window that preserves the art aspect.

    The larger art dimension is capped at 1100 px so the window fits on a
    1080-line display; the other dimension follows the aspect ratio.  The
    artwork is then centred and (if needed) scaled down by the renderer.
    """
    MAX_DIM = 1100
    MIN_DIM = 640
    if art_w <= 0 or art_h <= 0:
        return (MAX_DIM, MAX_DIM)
    if art_w >= art_h:
        win_w = max(MIN_DIM, min(art_w, MAX_DIM))
        win_h = max(MIN_DIM, round(win_w * art_h / art_w))
    else:
        win_h = max(MIN_DIM, min(art_h, MAX_DIM))
        win_w = max(MIN_DIM, round(win_h * art_w / art_h))
    return (win_w, win_h)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    if args.list_modes:
        for k, v in MODE_NAMES.items():
            print(f"  {k}: {v}")
        return 0

    try:
        cfg = build_config(args)

        # Load and validate the image first so file errors surface early.
        image, filename = image_loader.load_image(cfg.image_path)
        # Default the video title to the source filename when not given.
        if not cfg.title:
            cfg.title = filename

        # Initialise pygame enough to measure the font's true aspect ratio.
        pygame.init()
        pygame.font.init()
        measure_font = _load_font_for_measure(cfg)
        cell_w, cell_h = measure_font.size("M")

        cols, rows = _resolve_dimensions(cfg, image.size[0], image.size[1],
                                         cell_w, cell_h)
        cfg.output_width = cols
        cfg.output_height = rows

        # Choose a screen-friendly default window when the user did not set one.
        if cfg.window_width == 0 and cfg.window_height == 0:
            cfg.window_width, cfg.window_height = _auto_window_size(
                cols * cell_w, rows * cell_h
            )

        # Convert once, before animation begins (performance requirement).
        art = ascii_converter.convert(image, cfg)

        engine = AnimationEngine(art, cfg)

        # Import lazily so importing this module never requires a display.
        from renderer.pygame_renderer import PygameRenderer

        renderer = PygameRenderer(art, engine, cfg, image, filename)
        renderer.run()
        return 0

    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        try:
            pygame.quit()
        except Exception:
            pass
        return 130
    except pygame.error as exc:
        print(f"pygame error: {exc}", file=sys.stderr)
        print("hint: if you are on a headless machine, set "
              "SDL_VIDEODRIVER=dummy for testing.", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
