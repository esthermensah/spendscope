"""Local document text extraction adapters."""

from spendscope.extraction.base import ExtractionResult, OcrDiagnostic, OcrEngine
from spendscope.extraction.receipt_extractor import ReceiptTextExtractor

__all__ = ["ExtractionResult", "OcrDiagnostic", "OcrEngine", "ReceiptTextExtractor"]
