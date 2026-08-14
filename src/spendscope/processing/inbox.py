"""Deterministic Inbox scanning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spendscope.processing.file_validator import ReceiptFileValidator, ValidationResult


@dataclass(frozen=True, slots=True)
class InboxEntry:
    path: Path
    validation: ValidationResult


class InboxScanner:
    def __init__(self, inbox: Path, *, max_size_bytes: int) -> None:
        self.inbox = inbox.resolve()
        self.validator = ReceiptFileValidator(self.inbox, max_size_bytes=max_size_bytes)

    def scan(self) -> list[InboxEntry]:
        if not self.inbox.exists():
            return []
        entries = []
        for path in sorted(self.inbox.iterdir(), key=lambda item: item.name.casefold()):
            if path.name.startswith(".") or path.is_dir():
                continue
            entries.append(InboxEntry(path=path, validation=self.validator.validate(path)))
        return entries
