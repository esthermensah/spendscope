"""File-type dispatch for receipt text extraction."""

from __future__ import annotations

from pathlib import Path

from spendscope.config import AppConfig
from spendscope.extraction.base import ExtractionResult, OcrEngine
from spendscope.extraction.image_extractor import ImageTextExtractor
from spendscope.extraction.pdf_extractor import PdfTextExtractor


class ReceiptTextExtractor:
    def __init__(self, config: AppConfig, ocr: OcrEngine) -> None:
        self.image = ImageTextExtractor(
            ocr,
            language=config.ocr_language,
            max_dimension=config.max_image_dimension,
        )
        self.pdf = PdfTextExtractor(
            ocr,
            language=config.ocr_language,
            minimum_text_characters=config.minimum_pdf_text_characters,
            max_pages=config.max_pdf_pages,
        )

    def extract(self, path: Path) -> ExtractionResult:
        suffix = path.suffix.casefold()
        if suffix == ".pdf":
            return self.pdf.extract(path)
        if suffix in {".jpg", ".jpeg", ".png"}:
            return self.image.extract(path)
        raise ValueError(f"unsupported receipt file type: {suffix or 'none'}")
