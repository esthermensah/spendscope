"""Persistence helpers for local application services."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from spendscope.database.schema import (
    AuditEventRecord,
    BudgetRecord,
    CategoryRecord,
    ManualExpenseDetailRecord,
    RefundLinkRecord,
    ReviewCaseRecord,
    SyncQueueRecord,
)
from spendscope.domain.enums import ReviewCaseStatus, ReviewSeverity, SyncStatus
from spendscope.domain.models import BudgetDraft


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        entity_type: str,
        entity_id: str | int,
        action: str,
        details: dict[str, object] | None = None,
    ) -> AuditEventRecord:
        event = AuditEventRecord(
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            details_json=None if details is None else json.dumps(details, sort_keys=True),
        )
        self.session.add(event)
        self.session.flush()
        return event


class ReviewCaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, receipt_id: int, reason: str, severity: ReviewSeverity) -> ReviewCaseRecord:
        record = ReviewCaseRecord(
            receipt_id=receipt_id,
            reason=reason,
            severity=severity.value,
            status=ReviewCaseStatus.OPEN.value,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_open(self, receipt_id: int | None = None) -> list[ReviewCaseRecord]:
        statement = select(ReviewCaseRecord).where(
            ReviewCaseRecord.status == ReviewCaseStatus.OPEN.value
        )
        if receipt_id is not None:
            statement = statement.where(ReviewCaseRecord.receipt_id == receipt_id)
        return list(self.session.scalars(statement.order_by(ReviewCaseRecord.created_at)))

    def resolve_for_receipt(self, receipt_id: int) -> int:
        records = self.list_open(receipt_id)
        resolved_at = datetime.now()
        for record in records:
            record.status = ReviewCaseStatus.RESOLVED.value
            record.resolved_at = resolved_at
        self.session.flush()
        return len(records)


class ManualExpenseDetailRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, receipt_id: int, note: str | None) -> ManualExpenseDetailRecord:
        record = self.session.scalar(
            select(ManualExpenseDetailRecord).where(
                ManualExpenseDetailRecord.receipt_id == receipt_id
            )
        )
        if record is None:
            record = ManualExpenseDetailRecord(receipt_id=receipt_id, note=note)
            self.session.add(record)
        else:
            record.note = note
        self.session.flush()
        return record


class RefundLinkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        refund_receipt_id: int,
        refund_line_item_id: int,
        original_receipt_id: int | None,
        original_line_item_id: int | None,
    ) -> RefundLinkRecord:
        record = RefundLinkRecord(
            refund_receipt_id=refund_receipt_id,
            refund_line_item_id=refund_line_item_id,
            original_receipt_id=original_receipt_id,
            original_line_item_id=original_line_item_id,
        )
        self.session.add(record)
        self.session.flush()
        return record


class BudgetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, draft: BudgetDraft) -> BudgetRecord:
        category_id = None
        if draft.category_internal_name is not None:
            category = self.session.scalar(
                select(CategoryRecord).where(
                    CategoryRecord.internal_name == draft.category_internal_name,
                    CategoryRecord.active.is_(True),
                )
            )
            if category is None:
                raise ValueError(f"unknown or inactive category: {draft.category_internal_name}")
            category_id = category.id
        statement = select(BudgetRecord).where(
            BudgetRecord.year == draft.year,
            BudgetRecord.month == draft.month,
            BudgetRecord.currency == draft.currency,
        )
        statement = (
            statement.where(BudgetRecord.category_id.is_(None))
            if category_id is None
            else statement.where(BudgetRecord.category_id == category_id)
        )
        record = self.session.scalar(statement)
        if record is None:
            record = BudgetRecord(
                year=draft.year,
                month=draft.month,
                category_id=category_id,
                currency=draft.currency,
                budget_amount_minor=draft.amount_minor,
                warning_threshold=draft.warning_threshold,
            )
            self.session.add(record)
        else:
            record.budget_amount_minor = draft.amount_minor
            record.warning_threshold = draft.warning_threshold
        self.session.flush()
        return record

    def list_month(self, year: int, month: int, currency: str) -> list[BudgetRecord]:
        return list(
            self.session.scalars(
                select(BudgetRecord)
                .where(
                    BudgetRecord.year == year,
                    BudgetRecord.month == month,
                    BudgetRecord.currency == currency.upper(),
                )
                .order_by(BudgetRecord.category_id)
            )
        )


class SyncQueueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, entity_type: str, entity_id: str | int, operation: str) -> SyncQueueRecord:
        identifier = str(entity_id)
        existing = self.session.scalar(
            select(SyncQueueRecord).where(
                SyncQueueRecord.entity_type == entity_type,
                SyncQueueRecord.entity_id == identifier,
                SyncQueueRecord.operation == operation,
                SyncQueueRecord.status.in_((SyncStatus.PENDING.value, SyncStatus.SYNCING.value)),
            )
        )
        if existing is not None:
            return existing
        record = SyncQueueRecord(
            entity_type=entity_type,
            entity_id=identifier,
            operation=operation,
            status=SyncStatus.PENDING.value,
            retry_count=0,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_pending(self, *, limit: int = 100) -> list[SyncQueueRecord]:
        return list(
            self.session.scalars(
                select(SyncQueueRecord)
                .where(SyncQueueRecord.status == SyncStatus.PENDING.value)
                .order_by(SyncQueueRecord.created_at)
                .limit(limit)
            )
        )

    def set_status(
        self, record: SyncQueueRecord, status: SyncStatus, error: str | None = None
    ) -> None:
        record.status = status.value
        record.last_error = error
        if status is SyncStatus.FAILED:
            record.retry_count += 1
        self.session.flush()
