from pathlib import Path

import pytest
from PIL import Image

from spendscope.extraction import ocr as ocr_module
from spendscope.extraction.ocr import OcrUnavailableError, TesseractOcrEngine


def test_tesseract_diagnostic_and_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr_module.pytesseract, "get_tesseract_version", lambda: "5.4.0")
    monkeypatch.setattr(
        ocr_module.pytesseract,
        "image_to_string",
        lambda image, lang: "  Local receipt text  ",
    )
    executable = Path("/custom/tesseract")
    engine = TesseractOcrEngine(executable)
    diagnostic = engine.diagnostic()
    assert diagnostic.available and diagnostic.version == "5.4.0"
    assert engine.extract(Image.new("L", (20, 20))) == "Local receipt text"
    assert ocr_module.pytesseract.pytesseract.tesseract_cmd == str(executable)


def test_tesseract_unavailable_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> None:
        raise ocr_module.pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr_module.pytesseract, "get_tesseract_version", missing)
    engine = TesseractOcrEngine()
    assert not engine.diagnostic().available
    with pytest.raises(OcrUnavailableError):
        engine.extract(Image.new("L", (20, 20)))


def test_tesseract_processing_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr_module.pytesseract, "get_tesseract_version", lambda: "5.4.0")

    def fail(*args: object, **kwargs: object) -> str:
        raise ocr_module.pytesseract.TesseractError(1, "failed")

    monkeypatch.setattr(ocr_module.pytesseract, "image_to_string", fail)
    with pytest.raises(OcrUnavailableError, match="failed"):
        TesseractOcrEngine().extract(Image.new("L", (20, 20)))
