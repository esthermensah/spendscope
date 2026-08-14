"""Receipt image text extraction."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from spendscope.extraction.base import ExtractionMethod, ExtractionResult, OcrEngine
from spendscope.extraction.preprocessing import prepare_image


class ImageExtractionError(ValueError):
    pass


class ImageTextExtractor:
    def __init__(self, ocr: OcrEngine, *, language: str = "eng", max_dimension: int = 3000) -> None:
        self.ocr = ocr
        self.language = language
        self.max_dimension = max_dimension

    def extract(self, path: Path) -> ExtractionResult:
        try:
            with Image.open(path) as source:
                source.load()
                prepared = prepare_image(source, max_dimension=self.max_dimension)
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise ImageExtractionError(f"image could not be prepared: {error}") from error
        text = self.ocr.extract(prepared, language=self.language)
        warnings = () if text else ("OCR returned no text",)
        confidence = min(0.95, 0.45 + len(text) / 1000) if text else 0.0
        return ExtractionResult(
            text=text,
            method=ExtractionMethod.IMAGE_OCR,
            confidence=confidence,
            warnings=warnings,
            source_path=path,
        )
