"""Defensive receipt source-file validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spendscope.utilities.paths import is_path_within

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".pdf"})
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".pdf": (b"%PDF-",),
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    reason: str | None = None


class ReceiptFileValidator:
    def __init__(self, inbox: Path, *, max_size_bytes: int) -> None:
        if max_size_bytes <= 0:
            raise ValueError("maximum size must be positive")
        self.inbox = inbox.resolve()
        self.max_size_bytes = max_size_bytes

    def validate(self, path: Path) -> ValidationResult:
        if path.is_symlink():
            return ValidationResult(False, "symbolic links are not accepted")
        if not is_path_within(path, self.inbox):
            return ValidationResult(False, "file is outside the Inbox")
        return self.validate_source(path)

    def validate_source(self, path: Path) -> ValidationResult:
        """Validate receipt content before an external file is copied into Inbox."""
        if path.is_symlink():
            return ValidationResult(False, "symbolic links are not accepted")
        if not path.is_file():
            return ValidationResult(False, "path is not a regular file")
        suffix = path.suffix.casefold()
        if suffix not in SUPPORTED_EXTENSIONS:
            return ValidationResult(False, "unsupported file type")
        try:
            size = path.stat().st_size
            if size == 0:
                return ValidationResult(False, "file is empty")
            if size > self.max_size_bytes:
                return ValidationResult(False, "file exceeds the configured size limit")
            with path.open("rb") as source:
                header = source.read(8)
        except OSError:
            return ValidationResult(False, "file could not be read")
        if not any(header.startswith(signature) for signature in _SIGNATURES[suffix]):
            return ValidationResult(False, "file content does not match its extension")
        return ValidationResult(True)
