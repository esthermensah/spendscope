"""Conservative local receipt-image preparation."""

from __future__ import annotations

from PIL import Image, ImageOps


def prepare_image(image: Image.Image, *, max_dimension: int = 3000) -> Image.Image:
    prepared = ImageOps.exif_transpose(image)
    if prepared.mode not in {"L", "RGB"}:
        prepared = prepared.convert("RGB")
    prepared.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    grayscale = ImageOps.grayscale(prepared)
    return ImageOps.autocontrast(grayscale, cutoff=1)
