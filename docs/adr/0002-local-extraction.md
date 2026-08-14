# ADR 0002: Use local Tesseract OCR and local PDF extraction

**Status:** Proposed

Receipt content must not be sent to remote OCR services. Use pypdf for direct PDF text, PyMuPDF to render scanned pages, Pillow for conservative image preparation, and Tesseract through pytesseract for local OCR. Low-confidence results enter review.
