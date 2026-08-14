"""Durable offline queue for later report synchronization."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from spendscope.database.schema import ReceiptRecord, SyncQueueRecord
from spendscope.database.service_repositories import AuditRepository, SyncQueueRepository
from spendscope.domain.enums import SyncStatus


class SyncQueueService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = SyncQueueRepository(session)
        self.audit = AuditRepository(session)

    def enqueue(self, entity_type: str, entity_id: str | int, operation: str) -> SyncQueueRecord:
        record = self.repository.enqueue(entity_type, entity_id, operation)
        self._update_receipt_status(record, SyncStatus.PENDING)
        self.audit.record("sync_queue", record.id, "queued")
        return record

    def pending(self, *, limit: int = 100) -> list[SyncQueueRecord]:
        return self.repository.list_pending(limit=limit)

    def mark_syncing(self, record: SyncQueueRecord) -> None:
        self.repository.set_status(record, SyncStatus.SYNCING)
        self._update_receipt_status(record, SyncStatus.SYNCING)

    def mark_synced(self, record: SyncQueueRecord) -> None:
        self.repository.set_status(record, SyncStatus.SYNCED)
        self._update_receipt_status(record, SyncStatus.SYNCED)
        self.audit.record("sync_queue", record.id, "synced")

    def mark_failed(self, record: SyncQueueRecord, error: str) -> None:
        self.repository.set_status(record, SyncStatus.FAILED, error)
        self._update_receipt_status(record, SyncStatus.FAILED)
        self.audit.record("sync_queue", record.id, "failed", {"retry_count": record.retry_count})

    def retry(self, record: SyncQueueRecord) -> None:
        self.repository.set_status(record, SyncStatus.PENDING)
        self._update_receipt_status(record, SyncStatus.PENDING)
        self.audit.record("sync_queue", record.id, "retry_queued")

    def _update_receipt_status(self, record: SyncQueueRecord, status: SyncStatus) -> None:
        if record.entity_type != "receipt":
            return
        receipt = self.session.scalar(
            select(ReceiptRecord).where(ReceiptRecord.receipt_uuid == record.entity_id)
        )
        if receipt is not None:
            receipt.sync_status = status.value
            self.session.flush()
