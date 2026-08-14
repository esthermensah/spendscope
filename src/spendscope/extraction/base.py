"""Extraction contracts independent of a specific OCR engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from PIL import Image


class ExtractionMethod(StrEnum):
    IMAGE_OCR = "image_ocr"
    PDF_TEXT = "pdf_text"
    PDF_OCR = "pdf_ocr"


@dataclass(frozen=True, slots=True)
class OcrDiagnostic:
    available: bool
    engine: str
    version: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    text: str
    method: ExtractionMethod
    confidence: float
    page_count: int = 1
    warnings: tuple[str, ...] = field(default_factory=tuple)
    source_path: Path | None = None


class OcrEngine(Protocol):
    def diagnostic(self) -> OcrDiagnostic: ...

    def extract(self, image: Image.Image, *, language: str = "eng") -> str: ...
