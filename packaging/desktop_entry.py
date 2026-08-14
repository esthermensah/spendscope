"""Stable PyInstaller entry point for the desktop application."""

from spendscope.ui.application import main

if __name__ == "__main__":
    raise SystemExit(main())
