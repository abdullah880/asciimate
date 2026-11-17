"""Image loading and validation built on Pillow.

The public entry point is :func:`load_image`, which returns an RGB
:class:`PIL.Image.Image` together with the source filename.  All failure
modes (missing file, unsupported format, truncated/corrupted data) are
translated into :class:`ValidationError` so the caller can present a clean
message instead of a raw Pillow traceback.
"""

from __future__ import annotations

import os

from PIL import Image, UnidentifiedImageError

from utils.validators import SUPPORTED_EXTENSIONS, ValidationError

# Pillow format names for the extensions we accept.
_PIL_FORMATS = {"PNG", "JPEG", "BMP", "WEBP"}


def load_image(path: str):
    """Load *path* as an RGB image.

    Returns
    -------
    tuple
        ``(image, filename)`` where *image* is an ``RGB`` PIL image and
        *filename* is the bare basename of the source file.

    Raises
    ------
    ValidationError
        If the file is missing, unsupported, or corrupted.
    """
    if not path:
        raise ValidationError("No image path was provided.")

    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        raise ValidationError(f"Image file not found: {path}")
    if not os.path.isfile(expanded):
        raise ValidationError(f"Path is not a regular file: {path}")

    ext = os.path.splitext(expanded)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported image format '{ext or '<none>'}'. "
            f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}."
        )

    try:
        with Image.open(expanded) as opened:
            fmt = (opened.format or "").upper()
            if fmt not in _PIL_FORMATS:
                raise ValidationError(
                    f"File extension says '{ext}' but Pillow read it as "
                    f"'{fmt or 'unknown'}'. Refusing to render."
                )
            # Force the data to be decoded now so corruption is caught here.
            opened.load()
            # Flatten anything with transparency onto an opaque RGB canvas so
            # the rest of the pipeline can assume a plain 3-channel image.
            image = opened.convert("RGB")
    except UnidentifiedImageError:
        raise ValidationError(
            f"Could not identify the image file (corrupted or unsupported): {path}"
        )
    except OSError as exc:
        raise ValidationError(f"Failed to read image '{path}': {exc}")
    except ValueError as exc:
        raise ValidationError(f"Image data is malformed '{path}': {exc}")

    # Guard against degenerate sizes that would break downstream math.
    w, h = image.size
    if w <= 0 or h <= 0:
        raise ValidationError(f"Image has invalid dimensions {w}x{h}: {path}")

    return image, os.path.basename(path)
