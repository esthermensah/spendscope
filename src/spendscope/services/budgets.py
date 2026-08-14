"""Offline monthly budget configuration and calculations."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from spendscope.database.schema import BudgetRecord, CategoryRecord, LineItemRecord, ReceiptRecord
from spendscope.database.service_repositories import AuditRepository, BudgetRepository
from spendscope.domain.enums import BudgetStatus, ReceiptStatus
from spendscope.domain.models import BudgetDraft
from spendscope.services.sync_queue import SyncQueueService


@dataclass(frozen=True, slots=True)
class BudgetSummary:
    budget_id: int
    category_internal_name: str | None
    currency: str
    budget_minor: int
    spent_minor: int
    remaining_minor: int
    percentage_used: float
    warning_threshold: int
    status: BudgetStatus


class BudgetService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = BudgetRepository(session)
        self.audit = AuditRepository(session)
        self.sync = SyncQueueService(session)

    def set_budget(self, draft: BudgetDraft) -> BudgetSummary:
        record = self.repository.upsert(draft)
        self.sync.enqueue("budget", record.id, "upsert")
        self.audit.record("budget", record.id, "configured")
        return self._summary(record)

    def summaries(self, year: int, month: int, currency: str) -> list[BudgetSummary]:
        return [
            self._summary(record) for record in self.repository.list_month(year, month, currency)
        ]

    def _summary(self, record: BudgetRecord) -> BudgetSummary:
        category = (
            None
            if record.category_id is None
            else self.session.get(CategoryRecord, record.category_id)
        )
        if category is None and record.category_id is not None:
            raise LookupError("budget category no longer exists")
        spent = self._spent_minor(
            record.year,
            record.month,
            record.currency,
            None if category is None else category.internal_name,
        )
        remaining = record.budget_amount_minor - spent
        percentage = spent / record.budget_amount_minor * 100
        if spent > record.budget_amount_minor:
            status = BudgetStatus.OVER_BUDGET
        elif percentage >= record.warning_threshold:
            status = BudgetStatus.WARNING
        else:
            status = BudgetStatus.OK
        return BudgetSummary(
            record.id,
            None if category is None else category.internal_name,
            record.currency,
            record.budget_amount_minor,
            spent,
            remaining,
            percentage,
            record.warning_threshold,
            status,
        )

    def _spent_minor(
        self, year: int, month: int, currency: str, category_internal_name: str | None
    ) -> int:
        date_filters = (
            extract("year", ReceiptRecord.transaction_date) == year,
            extract("month", ReceiptRecord.transaction_date) == month,
            ReceiptRecord.currency == currency,
            ReceiptRecord.processing_status == ReceiptStatus.CONFIRMED.value,
        )
        if category_internal_name is None:
            value = self.session.scalar(
                select(func.coalesce(func.sum(ReceiptRecord.final_total_minor), 0)).where(
                    *date_filters
                )
            )
        elif category_internal_name in {"tax", "tips"}:
            amount_column = (
                ReceiptRecord.tax_minor
                if category_internal_name == "tax"
                else ReceiptRecord.tip_minor
            )
            value = self.session.scalar(
                select(func.coalesce(func.sum(amount_column), 0)).where(*date_filters)
            )
        else:
            value = self.session.scalar(
                select(func.coalesce(func.sum(LineItemRecord.line_total_minor), 0))
                .select_from(LineItemRecord)
                .join(ReceiptRecord, LineItemRecord.receipt_id == ReceiptRecord.id)
                .join(CategoryRecord, LineItemRecord.category_id == CategoryRecord.id)
                .where(*date_filters, CategoryRecord.internal_name == category_internal_name)
            )
        return int(value or 0)
