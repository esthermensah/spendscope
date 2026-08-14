"""Safe, single-pass archival image compression."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


class ImageCompressionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CompressionResult:
    destination: Path
    original_size: int
    archived_size: int
    dimensions: tuple[int, int]

    @property
    def ratio(self) -> float:
        return self.archived_size / self.original_size if self.original_size else 1.0


def compress_image(
    source: Path,
    destination: Path,
    *,
    quality: int = 85,
    max_dimension: int = 2400,
) -> CompressionResult:
    if source.resolve() == destination.resolve():
        raise ImageCompressionError("source and destination must differ")
    destination.parent.mkdir(parents=True, exist_ok=True)
    original_size = source.stat().st_size
    temporary_path: Path | None = None
    try:
        with Image.open(source) as opened_image:
            opened_image.load()
            image: Image.Image = ImageOps.exif_transpose(opened_image)
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            suffix = destination.suffix.casefold()
            output_format = "PNG" if suffix == ".png" else "JPEG"
            if output_format == "JPEG" and image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.stem}-",
                suffix=destination.suffix,
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            save_options: dict[str, object] = {"optimize": True}
            if output_format == "JPEG":
                save_options["quality"] = quality
                save_options["progressive"] = True
            image.save(temporary_path, format=output_format, **save_options)
            dimensions = image.size
        os.replace(temporary_path, destination)
        temporary_path = None
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ImageCompressionError(f"image compression failed: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return CompressionResult(
        destination=destination,
        original_size=original_size,
        archived_size=destination.stat().st_size,
        dimensions=dimensions,
    )
