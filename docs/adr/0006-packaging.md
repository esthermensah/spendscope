# ADR 0006: Package with PyInstaller after an early platform spike

**Status:** Accepted

PyInstaller packages the initial Windows and macOS applications because it supports PySide6 and
must build separately on each target operating system. The Phase 8 spike validates the application
bundle with an isolated first-run smoke test that exercises Qt, database migrations, and the main
window. GitHub Actions retains zipped, checksummed artifacts and creates draft releases. Portfolio
beta releases may remain unsigned when they are labeled clearly and include platform-specific
security-warning instructions.

Tesseract remains an explicit local runtime dependency for OCR rather than being silently downloaded
or remotely invoked. Public releases require a documented Tesseract distribution decision, an
approved project license, checksum files, and prominent disclosure of signing status. Apple
notarization and Windows code signing are optional future distribution improvements rather than
requirements for this portfolio beta.
