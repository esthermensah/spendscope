"""Direct PDF text extraction with local rendered-page OCR fallback."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from spendscope.extraction.base import ExtractionMethod, ExtractionResult, OcrEngine
from spendscope.extraction.preprocessing import prepare_image


class PdfExtractionError(ValueError):
    pass


class PdfTextExtractor:
    def __init__(
        self,
        ocr: OcrEngine,
        *,
        language: str = "eng",
        minimum_text_characters: int = 40,
        max_pages: int = 10,
    ) -> None:
        self.ocr = ocr
        self.language = language
        self.minimum_text_characters = minimum_text_characters
        self.max_pages = max_pages

    def extract(self, path: Path) -> ExtractionResult:
        direct_text, page_count = self._direct_text(path)
        if len(direct_text.strip()) >= self.minimum_text_characters:
            return ExtractionResult(
                direct_text.strip(),
                ExtractionMethod.PDF_TEXT,
                confidence=0.95,
                page_count=page_count,
                source_path=path,
            )
        rendered_text, rendered_pages = self._rendered_ocr(path)
        warnings = ["PDF direct text was insufficient; local OCR fallback was used"]
        if page_count > self.max_pages:
            warnings.append(f"Only the first {self.max_pages} pages were processed")
        return ExtractionResult(
            rendered_text.strip(),
            ExtractionMethod.PDF_OCR,
            confidence=min(0.85, 0.4 + len(rendered_text) / 1200) if rendered_text else 0.0,
            page_count=rendered_pages,
            warnings=tuple(warnings),
            source_path=path,
        )

    def _direct_text(self, path: Path) -> tuple[str, int]:
        try:
            reader = PdfReader(path, strict=False)
            pages = reader.pages[: self.max_pages]
            text = "\n".join(page.extract_text() or "" for page in pages)
            return text, len(reader.pages)
        except (OSError, PdfReadError, ValueError) as error:
            raise PdfExtractionError(f"PDF direct extraction failed: {error}") from error

    def _rendered_ocr(self, path: Path) -> tuple[str, int]:
        try:
            document = pymupdf.open(path)  # type: ignore[no-untyped-call]
        except (OSError, pymupdf.FileDataError) as error:
            raise PdfExtractionError(f"PDF rendering failed: {error}") from error
        texts = []
        pages_to_process = min(document.page_count, self.max_pages)
        try:
            for page_number in range(pages_to_process):
                page = document.load_page(page_number)  # type: ignore[no-untyped-call]
                matrix = pymupdf.Matrix(2, 2)  # type: ignore[no-untyped-call]
                pixmap = page.get_pixmap(matrix=matrix)
                with Image.open(BytesIO(pixmap.tobytes("png"))) as image:
                    prepared = prepare_image(image)
                texts.append(self.ocr.extract(prepared, language=self.language))
        finally:
            document.close()  # type: ignore[no-untyped-call]
        return "\n".join(texts), pages_to_process
