"""Input validation helpers.

These functions raise :class:`ValidationError` with a clear, human-readable
message whenever an input is unacceptable.  The application entry point
catches these and prints them instead of letting a raw traceback escape.
"""

from __future__ import annotations

import os
from typing import Tuple

import config  # top-level config module (ramps, modes, themes)


SUPPORTED_EXTENSIONS: Tuple[str, ...] = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


class ValidationError(Exception):
    """Raised when user-supplied input is invalid."""


def validate_image_path(path: str) -> str:
    """Validate that *path* points to a readable, supported image file.

    Returns the absolute path on success.  Raises :class:`ValidationError`
    with a meaningful message otherwise.
    """
    if not path or not isinstance(path, str):
        raise ValidationError("No image path was provided.")

    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise ValidationError(f"Image file not found: {path}")

    if not os.path.isfile(path):
        raise ValidationError(f"Path is not a regular file: {path}")

    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported image format '{ext or '<none>'}'. "
            f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}."
        )

    if os.path.getsize(path) == 0:
        raise ValidationError(f"Image file is empty: {path}")

    return os.path.abspath(path)


def validate_int(value, name: str, low: int = None, high: int = None) -> int:
    """Validate and coerce *value* to an int within optional bounds."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be an integer, got {value!r}.")
    if low is not None and result < low:
        raise ValidationError(f"{name} must be >= {low}, got {result}.")
    if high is not None and result > high:
        raise ValidationError(f"{name} must be <= {high}, got {result}.")
    return result


def validate_float(value, name: str, low: float = None, high: float = None) -> float:
    """Validate and coerce *value* to a float within optional bounds."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be a number, got {value!r}.")
    if low is not None and result < low:
        raise ValidationError(f"{name} must be >= {low}, got {result}.")
    if high is not None and result > high:
        raise ValidationError(f"{name} must be <= {high}, got {result}.")
    return result


def validate_mode(mode) -> int:
    """Validate an animation mode, returning the cleaned integer."""
    result = validate_int(mode, "animation mode")
    if result not in config.MODE_NAMES:
        raise ValidationError(
            f"Invalid animation mode {result}. "
            f"Valid modes: {', '.join(f'{k}={v}' for k, v in config.MODE_NAMES.items())}."
        )
    return result


def validate_ramp_choice(choice: str) -> str:
    """Resolve a ramp name (or raw ramp string) into a usable ramp string."""
    if not choice:
        return config.DEFAULT_RAMP
    if choice in config.RAMPS:
        return config.RAMPS[choice]
    # Treat as a literal ramp string supplied by the user.
    return choice
