"""Receipt review lifecycle independent of the desktop interface."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from spendscope.database.schema import ReceiptRecord
from spendscope.database.service_repositories import AuditRepository, ReviewCaseRepository
from spendscope.domain.enums import ReceiptStatus, ReviewSeverity, ReviewStatus
from spendscope.services.sync_queue import SyncQueueService


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.cases = ReviewCaseRepository(session)
        self.audit = AuditRepository(session)
        self.sync = SyncQueueService(session)

    def pending_receipts(self) -> list[ReceiptRecord]:
        return list(
            self.session.scalars(
                select(ReceiptRecord)
                .options(selectinload(ReceiptRecord.line_items))
                .where(
                    ReceiptRecord.review_status.in_(
                        (ReviewStatus.FLAGGED.value, ReviewStatus.REQUIRED.value)
                    )
                )
                .order_by(ReceiptRecord.imported_at)
            )
        )

    def flag(self, receipt: ReceiptRecord, reason: str, *, severity: ReviewSeverity) -> None:
        receipt.processing_status = ReceiptStatus.NEEDS_REVIEW.value
        receipt.review_status = (
            ReviewStatus.REQUIRED.value
            if severity is ReviewSeverity.HIGH
            else ReviewStatus.FLAGGED.value
        )
        case = self.cases.create(receipt.id, reason, severity)
        self.audit.record("receipt", receipt.id, "review_flagged", {"case_id": case.id})
        self.session.flush()

    def confirm(self, receipt: ReceiptRecord) -> None:
        receipt.processing_status = ReceiptStatus.CONFIRMED.value
        receipt.review_status = ReviewStatus.RESOLVED.value
        receipt.confirmed_at = datetime.now()
        self.cases.resolve_for_receipt(receipt.id)
        self.sync.enqueue("receipt", receipt.receipt_uuid, "upsert")
        self.audit.record("receipt", receipt.id, "confirmed")
        self.session.flush()

    def reject(self, receipt: ReceiptRecord) -> None:
        receipt.processing_status = ReceiptStatus.REJECTED.value
        receipt.review_status = ReviewStatus.RESOLVED.value
        self.cases.resolve_for_receipt(receipt.id)
        self.audit.record("receipt", receipt.id, "rejected")
        self.session.flush()

    def retry(self, receipt: ReceiptRecord) -> None:
        receipt.processing_status = ReceiptStatus.PROCESSING.value
        receipt.review_status = ReviewStatus.REQUIRED.value
        self.audit.record("receipt", receipt.id, "retry_requested")
        self.session.flush()
