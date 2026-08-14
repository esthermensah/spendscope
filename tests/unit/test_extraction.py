from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from spendscope.config import AppConfig
from spendscope.extraction.base import ExtractionMethod, OcrDiagnostic
from spendscope.extraction.image_extractor import ImageExtractionError, ImageTextExtractor
from spendscope.extraction.pdf_extractor import PdfExtractionError, PdfTextExtractor
from spendscope.extraction.preprocessing import prepare_image
from spendscope.extraction.receipt_extractor import ReceiptTextExtractor


class FakeOcr:
    def __init__(self, text: str = "SCANNED RECEIPT\nTOTAL $10.00") -> None:
        self.text = text
        self.calls = 0

    def diagnostic(self) -> OcrDiagnostic:
        return OcrDiagnostic(True, "fake", "1.0")

    def extract(self, image: Image.Image, *, language: str = "eng") -> str:
        self.calls += 1
        assert image.mode == "L"
        assert language == "eng"
        return self.text


def create_pdf(path: Path, text: str | None = None, pages: int = 1) -> None:
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page(width=400, height=600)
        if text:
            page.insert_text((40, 60), text)
    document.save(path)
    document.close()


def test_image_preprocessing_corrects_mode_and_size() -> None:
    source = Image.new("RGBA", (4000, 2000), (255, 255, 255, 255))
    prepared = prepare_image(source, max_dimension=1000)
    assert prepared.mode == "L"
    assert prepared.size == (1000, 500)


def test_image_extractor_uses_local_ocr(tmp_path: Path) -> None:
    path = tmp_path / "receipt.png"
    Image.new("RGB", (400, 600), "white").save(path)
    ocr = FakeOcr("Market\nRice 12.00")
    result = ImageTextExtractor(ocr).extract(path)
    assert result.method is ExtractionMethod.IMAGE_OCR
    assert result.text == "Market\nRice 12.00"
    assert result.confidence > 0
    assert ocr.calls == 1


def test_image_extractor_rejects_malformed_image(tmp_path: Path) -> None:
    path = tmp_path / "bad.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ImageExtractionError):
        ImageTextExtractor(FakeOcr()).extract(path)


def test_pdf_extractor_prefers_embedded_text(tmp_path: Path) -> None:
    path = tmp_path / "digital.pdf"
    receipt_text = "Market receipt with embedded text and a total of USD 12.00"
    create_pdf(path, receipt_text)
    ocr = FakeOcr()
    result = PdfTextExtractor(ocr, minimum_text_characters=20).extract(path)
    assert result.method is ExtractionMethod.PDF_TEXT
    assert "embedded text" in result.text
    assert result.confidence == 0.95
    assert ocr.calls == 0


def test_pdf_extractor_renders_scanned_pages_for_ocr(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    create_pdf(path, pages=2)
    ocr = FakeOcr()
    result = PdfTextExtractor(ocr, minimum_text_characters=20, max_pages=1).extract(path)
    assert result.method is ExtractionMethod.PDF_OCR
    assert result.page_count == 1
    assert ocr.calls == 1
    assert "first 1 pages" in " ".join(result.warnings)


def test_pdf_extractor_rejects_malformed_pdf(tmp_path: Path) -> None:
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-not-valid")
    with pytest.raises(PdfExtractionError):
        PdfTextExtractor(FakeOcr()).extract(path)


def test_receipt_extractor_dispatches_and_rejects_unknown_type(tmp_path: Path) -> None:
    config = AppConfig(root_folder=tmp_path)
    extractor = ReceiptTextExtractor(config, FakeOcr())
    image_path = tmp_path / "receipt.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    assert extractor.extract(image_path).method is ExtractionMethod.IMAGE_OCR
    with pytest.raises(ValueError, match="unsupported"):
        extractor.extract(tmp_path / "receipt.txt")
