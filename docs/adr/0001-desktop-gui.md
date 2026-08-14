# ADR 0001: Use PySide6 for the desktop interface

**Status:** Accepted

SpendScope needs a cross-platform, native desktop GUI with a Python application core. PySide6 is proposed because it supports Windows and macOS, accessible widgets, background-worker integration, and packaging tools. Tkinter is smaller but less suitable for the intended review-heavy workflow. Validate the final choice in a first packaging spike.

Phase 7 validated the choice with an offscreen widget test suite and a background-worker based receipt-processing flow. The application uses the official PySide6 Essentials distribution because the MVP needs Qt Core, GUI, and Widgets but does not require the larger optional Qt modules.
