"""Local Tesseract OCR adapter and diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytesseract  # type: ignore[import-untyped]
from PIL import Image

from spendscope.extraction.base import OcrDiagnostic


class OcrUnavailableError(RuntimeError):
    pass


class TesseractOcrEngine:
    def __init__(self, executable: Path | None = None) -> None:
        self.executable = executable

    def _configure(self) -> None:
        if self.executable is not None:
            pytesseract.pytesseract.tesseract_cmd = str(self.executable)

    def diagnostic(self) -> OcrDiagnostic:
        self._configure()
        try:
            version = str(pytesseract.get_tesseract_version())
        except (pytesseract.TesseractNotFoundError, OSError) as error:
            return OcrDiagnostic(False, "tesseract", message=str(error))
        return OcrDiagnostic(True, "tesseract", version=version)

    def extract(self, image: Image.Image, *, language: str = "eng") -> str:
        diagnostic = self.diagnostic()
        if not diagnostic.available:
            raise OcrUnavailableError(diagnostic.message or "Tesseract is unavailable")
        try:
            return str(pytesseract.image_to_string(image, lang=language)).strip()
        except pytesseract.TesseractError as error:
            raise OcrUnavailableError(f"Tesseract failed: {error}") from error

    def extract_with_config(
        self, image: Image.Image, *, language: str = "eng", config: str = ""
    ) -> str:
        """Run an alternate layout pass for documents with separated columns.

        Invoices frequently place the description and amount in separate visual
        columns. Tesseract's default block mode can merge those columns and lose
        the amounts. Sparse-text mode preserves the visual order and is used by
        the image extractor only when an invoice layout is detected.
        """
        diagnostic = self.diagnostic()
        if not diagnostic.available:
            raise OcrUnavailableError(diagnostic.message or "Tesseract is unavailable")
        try:
            return str(pytesseract.image_to_string(image, lang=language, config=config)).strip()
        except pytesseract.TesseractError as error:
            raise OcrUnavailableError(f"Tesseract failed: {error}") from error
