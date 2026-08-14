"""Phase 2 file-intake orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session

from spendscope.config import AppConfig
from spendscope.database.repositories import ProcessedFileRepository
from spendscope.database.schema import ProcessedFileRecord
from spendscope.processing.duplicate_detector import check_exact_duplicate
from spendscope.processing.file_manager import ReceiptFileManager
from spendscope.processing.inbox import InboxScanner

logger = logging.getLogger(__name__)


class IntakeStatus(StrEnum):
    ACCEPTED = "accepted"
    RESUMED = "resumed"
    DUPLICATE = "duplicate"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class IntakeResult:
    path: Path
    status: IntakeStatus
    reason: str | None = None
    file_hash: str | None = None
    record_id: int | None = None


class StoragePipeline:
    def __init__(self, config: AppConfig, session: Session) -> None:
        self.config = config
        self.session = session
        self.repository = ProcessedFileRepository(session)
        self.file_manager = ReceiptFileManager(config)

    def scan_and_register(self) -> list[IntakeResult]:
        self.file_manager.create_workspace()
        scanner = InboxScanner(
            self.config.directory_paths()["inbox"],
            max_size_bytes=self.config.max_import_size_mb * 1024 * 1024,
        )
        results = []
        for entry in scanner.scan():
            if not entry.validation.valid:
                logger.warning("Rejected Inbox file: %s", entry.validation.reason)
                results.append(
                    IntakeResult(entry.path, IntakeStatus.INVALID, reason=entry.validation.reason)
                )
                continue
            duplicate = check_exact_duplicate(self.session, entry.path)
            if duplicate.duplicate:
                existing = self.repository.get(duplicate.existing_file_id or 0)
                if (
                    existing is not None
                    and existing.processing_status in {"discovered", "processing"}
                    and Path(existing.original_path).resolve() == entry.path.resolve()
                ):
                    logger.info("Resuming previously discovered Inbox file")
                    results.append(
                        IntakeResult(
                            entry.path,
                            IntakeStatus.RESUMED,
                            file_hash=duplicate.file_hash,
                            record_id=existing.id,
                        )
                    )
                    continue
                logger.info("Exact duplicate file detected")
                results.append(
                    IntakeResult(
                        entry.path,
                        IntakeStatus.DUPLICATE,
                        reason="exact file hash already processed",
                        file_hash=duplicate.file_hash,
                        record_id=duplicate.existing_file_id,
                    )
                )
                continue
            record = self.repository.create_discovered(entry.path, duplicate.file_hash)
            results.append(
                IntakeResult(
                    entry.path,
                    IntakeStatus.ACCEPTED,
                    file_hash=duplicate.file_hash,
                    record_id=record.id,
                )
            )
        return results

    def archive_confirmed(self, record_id: int, transaction_date: date) -> Path | None:
        record = self._record(record_id)
        result = self.file_manager.archive_confirmed(Path(record.original_path), transaction_date)
        self.repository.update_lifecycle(
            record,
            status="archived",
            destination=result.destination,
            archived_size=result.archived_size,
        )
        logger.info("Confirmed receipt file lifecycle action: %s", result.action)
        return result.destination

    def require_review(self, record_id: int) -> Path:
        record = self._record(record_id)
        result = self.file_manager.move_to_review(Path(record.original_path))
        assert result.destination is not None
        self.repository.update_lifecycle(
            record,
            status="needs_review",
            destination=result.destination,
            archived_size=result.archived_size,
        )
        logger.info("Receipt file moved to review")
        return result.destination

    def _record(self, record_id: int) -> ProcessedFileRecord:
        record = self.repository.get(record_id)
        if record is None:
            raise LookupError(f"processed file {record_id} does not exist")
        return record
