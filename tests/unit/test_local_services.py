import csv
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, select

from spendscope.database.connection import session_scope
from spendscope.database.schema import (
    ManualExpenseDetailRecord,
    RefundLinkRecord,
    ReviewCaseRecord,
)
from spendscope.domain.enums import BudgetStatus, ReviewSeverity, SyncStatus
from spendscope.domain.models import BudgetDraft, ManualExpenseDraft, RefundDraft
from spendscope.services.budgets import BudgetService
from spendscope.services.corrections import CorrectionService
from spendscope.services.expenses import ManualExpenseService, RefundService
from spendscope.services.exports import LocalExportService
from spendscope.services.review import ReviewService
from spendscope.services.sync_queue import SyncQueueService


def manual_draft(**changes: object) -> ManualExpenseDraft:
    values: dict[str, object] = {
        "transaction_date": date(2026, 8, 6),
        "description": "Rice",
        "category_internal_name": "groceries",
        "amount_minor": 10_000,
        "currency": "USD",
        "merchant": "Local Market",
        "tax_minor": 500,
        "note": "Cash purchase",
    }
    values.update(changes)
    return ManualExpenseDraft.model_validate(values)


def test_manual_expense_create_and_update(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        service = ManualExpenseService(session)
        receipt = service.create(manual_draft())

        assert receipt.source_type == "manual"
        assert receipt.processing_status == "confirmed"
        assert receipt.confirmed_at is not None
        assert receipt.sync_status == "pending"
        assert receipt.final_total_minor == 10_500
        assert receipt.line_items[0].line_total_minor == 10_000
        detail = session.scalar(
            select(ManualExpenseDetailRecord).where(
                ManualExpenseDetailRecord.receipt_id == receipt.id
            )
        )
        assert detail is not None and detail.note == "Cash purchase"

        updated = service.update(
            receipt,
            manual_draft(
                description="Bus fare",
                category_internal_name="transportation",
                amount_minor=2500,
                tax_minor=0,
                note="",
            ),
        )
        assert updated.final_total_minor == 2500
        assert updated.line_items[0].description_normalized == "bus fare"
        assert updated.line_items[0].category.internal_name == "transportation"


def test_manual_service_rejects_non_manual_receipt(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        receipt = ManualExpenseService(session).create(manual_draft())
        receipt.source_type = "image"
        with pytest.raises(ValueError, match="only manual"):
            ManualExpenseService(session).update(receipt, manual_draft())


def test_refund_reduces_category_and_overall_budget_usage(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        expense = ManualExpenseService(session).create(
            manual_draft(tax_minor=0, amount_minor=10_000)
        )
        original_item = expense.line_items[0]
        refund = RefundService(session).create(
            RefundDraft(
                transaction_date=date(2026, 8, 7),
                description="Rice return",
                category_internal_name="groceries",
                amount_minor=2000,
                currency="USD",
                merchant="Local Market",
                original_receipt_id=expense.id,
                original_line_item_id=original_item.id,
            )
        )
        link = session.scalar(
            select(RefundLinkRecord).where(RefundLinkRecord.refund_receipt_id == refund.id)
        )
        assert refund.final_total_minor == -2000
        assert refund.line_items[0].kind == "refund"
        assert link is not None and link.original_line_item_id == original_item.id

        budgets = BudgetService(session)
        category = budgets.set_budget(
            BudgetDraft(
                year=2026,
                month=8,
                category_internal_name="groceries",
                currency="USD",
                amount_minor=9000,
                warning_threshold=80,
            )
        )
        overall = budgets.set_budget(
            BudgetDraft(year=2026, month=8, currency="USD", amount_minor=7000)
        )

        assert category.spent_minor == 8000
        assert category.status is BudgetStatus.WARNING
        assert overall.spent_minor == 8000
        assert overall.status is BudgetStatus.OVER_BUDGET
        assert overall.remaining_minor == -1000


def test_tax_and_tip_budgets_use_receipt_level_amounts(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        ManualExpenseService(session).create(manual_draft(tax_minor=500, tip_minor=200))
        budgets = BudgetService(session)
        tax = budgets.set_budget(
            BudgetDraft(
                year=2026,
                month=8,
                category_internal_name="tax",
                currency="USD",
                amount_minor=1000,
            )
        )
        tips = budgets.set_budget(
            BudgetDraft(
                year=2026,
                month=8,
                category_internal_name="tips",
                currency="USD",
                amount_minor=1000,
            )
        )

        assert tax.spent_minor == 500
        assert tips.spent_minor == 200


def test_refund_reference_validation(database_engine: Engine) -> None:
    with (
        session_scope(database_engine) as session,
        pytest.raises(ValueError, match="original receipt"),
    ):
        RefundService(session).create(
            RefundDraft(
                transaction_date=date.today(),
                description="Return",
                category_internal_name="shopping",
                amount_minor=500,
                currency="USD",
                original_receipt_id=999,
            )
        )


def test_review_and_correction_services_record_lifecycle(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        receipt = ManualExpenseService(session).create(manual_draft())
        reviews = ReviewService(session)
        reviews.flag(receipt, "category uncertain", severity=ReviewSeverity.MEDIUM)

        assert reviews.pending_receipts() == [receipt]
        assert receipt.review_status == "flagged"
        corrections = CorrectionService(session)
        corrections.correct_item(
            receipt.line_items[0],
            description="Rice flour",
            category_internal_name="groceries",
            remember=True,
        )
        corrections.correct_merchant(receipt, "Neighborhood Market", remember=True)
        assert receipt.line_items[0].manually_corrected
        assert receipt.merchant_normalized == "neighborhood market"

        reviews.confirm(receipt)
        case = session.scalar(
            select(ReviewCaseRecord).where(ReviewCaseRecord.receipt_id == receipt.id)
        )
        assert receipt.review_status == "resolved"
        assert case is not None and case.status == "resolved"

        reviews.retry(receipt)
        assert receipt.processing_status == "processing"
        reviews.reject(receipt)
        assert receipt.processing_status == "rejected"


def test_sync_queue_is_idempotent_and_retryable(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        service = SyncQueueService(session)
        first = service.enqueue("receipt", "abc", "upsert")
        second = service.enqueue("receipt", "abc", "upsert")
        assert first.id == second.id

        service.mark_syncing(first)
        service.mark_failed(first, "offline")
        assert first.status == SyncStatus.FAILED.value and first.retry_count == 1
        service.retry(first)
        assert service.pending() == [first]
        service.mark_synced(first)
        assert first.status == SyncStatus.SYNCED.value


def test_local_exports_include_receipts_items_budgets_and_backup(
    database_engine: Engine, tmp_path: Path
) -> None:
    destination = tmp_path / "exports"
    with session_scope(database_engine) as session:
        ManualExpenseService(session).create(manual_draft())
        BudgetService(session).set_budget(
            BudgetDraft(year=2026, month=8, currency="USD", amount_minor=20_000)
        )
        bundle = LocalExportService(session).export_all(destination)

        with bundle.receipts_csv.open(newline="", encoding="utf-8") as handle:
            receipts = list(csv.DictReader(handle))
        with bundle.backup_json.open(encoding="utf-8") as handle:
            backup = json.load(handle)

        assert receipts[0]["merchant"] == "local market"
        assert bundle.line_items_csv.exists() and bundle.budgets_csv.exists()
        assert backup["format_version"] == 1
        assert backup["receipts"][0]["items"][0]["description_normalized"] == "rice"
        assert backup["budgets"][0]["amount_minor"] == 20_000
