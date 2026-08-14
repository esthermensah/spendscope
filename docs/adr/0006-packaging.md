# ADR 0006: Package with PyInstaller after an early platform spike

**Status:** Accepted

PyInstaller packages the initial Windows and macOS applications because it supports PySide6 and
must build separately on each target operating system. The Phase 8 spike validates the application
bundle with an isolated first-run smoke test that exercises Qt, database migrations, and the main
window. GitHub Actions retains zipped, checksummed artifacts and creates only draft releases until
the artifacts are signed.

Tesseract remains an explicit local runtime dependency for OCR rather than being silently downloaded
or remotely invoked. Public releases require a documented Tesseract distribution decision, an
approved project license, Apple Developer ID signing and notarization, and Windows code signing.
