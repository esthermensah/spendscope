"""Thin desktop controller that coordinates local application services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from spendscope.config import AppConfig, save_config
from spendscope.database.connection import create_sqlite_engine, session_scope
from spendscope.database.repositories import CategoryRepository, ProcessedFileRepository
from spendscope.database.schema import (
    CategoryRecord,
    LineItemRecord,
    ProcessedFileRecord,
    ReceiptRecord,
    ReviewCaseRecord,
    SyncQueueRecord,
)
from spendscope.domain.enums import ReceiptStatus, ReviewStatus
from spendscope.domain.models import (
    BudgetDraft,
    CategoryDraft,
    ManualExpenseDraft,
    ReceiptCorrectionDraft,
    RefundDraft,
)
from spendscope.processing.file_manager import ReceiptFileManager
from spendscope.reporting.models import SyncResult
from spendscope.reporting.sync_service import ReportSyncService
from spendscope.services.budgets import BudgetService, BudgetSummary
from spendscope.services.corrections import CorrectionService
from spendscope.services.expenses import ManualExpenseService, RefundService
from spendscope.services.review import ReviewService
from spendscope.storage.usage import StorageReport, calculate_storage_usage


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    inbox_count: int
    review_count: int
    pending_sync: int
    month_spending_minor: int
    budget_minor: int | None
    storage_bytes: int
    disk_capacity_bytes: int
    disk_free_bytes: int
    recent_receipts: tuple[tuple[int, str, str, int, str], ...]
    category_spending: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ReviewItem:
    id: int
    description: str
    line_total_minor: int
    category_internal_name: str


@dataclass(frozen=True, slots=True)
class ReviewReceipt:
    id: int
    transaction_date: date
    merchant: str
    currency: str
    subtotal_minor: int
    tax_minor: int
    tip_minor: int
    discount_minor: int
    final_total_minor: int
    source_path: str | None
    review_reason: str | None
    items: tuple[ReviewItem, ...]


class DesktopController:
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        self.config = config
        self.config_path = config_path
        self.engine = create_sqlite_engine(config.database_path)

    def close(self) -> None:
        self.engine.dispose()

    def dashboard(self, today: date | None = None) -> DashboardSnapshot:
        today = today or date.today()
        inbox = self.config.directory_paths()["inbox"]
        with session_scope(self.engine) as session:
            inbox_files = (
                [item for item in inbox.iterdir() if item.is_file()] if inbox.exists() else []
            )
            inbox_paths = {str(item.resolve()) for item in inbox_files}
            completed_paths = {
                path
                for path in session.scalars(
                    select(ProcessedFileRecord.original_path).where(
                        ProcessedFileRecord.original_path.in_(inbox_paths),
                        ProcessedFileRecord.processing_status.in_(
                            ("archived", "needs_review", "rejected", "failed")
                        ),
                    )
                )
            }
            # Google Drive can leave a cloud-synced copy in Inbox after SpendScope
            # has already moved the original to Needs Review or Archive. Do not
            # show that terminal duplicate as a new receipt.
            inbox_count = sum(
                1 for item in inbox_files if str(item.resolve()) not in completed_paths
            )
            review_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(ReceiptRecord)
                    .where(
                        ReceiptRecord.review_status.in_(
                            (ReviewStatus.FLAGGED.value, ReviewStatus.REQUIRED.value)
                        )
                    )
                )
                or 0
            )
            pending_sync = int(
                session.scalar(
                    select(func.count())
                    .select_from(SyncQueueRecord)
                    .where(SyncQueueRecord.status.in_(("pending", "retry")))
                )
                or 0
            )
            receipts = list(
                session.scalars(
                    select(ReceiptRecord)
                    .where(
                        ReceiptRecord.processing_status == ReceiptStatus.CONFIRMED.value,
                        func.strftime("%Y", ReceiptRecord.transaction_date) == str(today.year),
                        func.strftime("%m", ReceiptRecord.transaction_date) == f"{today.month:02d}",
                        ReceiptRecord.currency == self.config.default_currency,
                    )
                    .order_by(ReceiptRecord.transaction_date.desc(), ReceiptRecord.id.desc())
                )
            )
            spent = sum(receipt.final_total_minor for receipt in receipts)
            budgets = BudgetService(session).summaries(
                today.year, today.month, self.config.default_currency
            )
            overall = next(
                (item.budget_minor for item in budgets if item.category_internal_name is None),
                None,
            )
            recent = tuple(
                (
                    receipt.id,
                    receipt.transaction_date.isoformat(),
                    receipt.merchant_original,
                    receipt.final_total_minor,
                    receipt.currency,
                )
                for receipt in receipts[:8]
            )
            category_spending = (
                tuple(
                    (name, int(total or 0))
                    for name, total in session.execute(
                        select(
                            CategoryRecord.display_name, func.sum(LineItemRecord.line_total_minor)
                        )
                        .join(LineItemRecord, LineItemRecord.category_id == CategoryRecord.id)
                        .where(LineItemRecord.receipt_id.in_([receipt.id for receipt in receipts]))
                        .group_by(CategoryRecord.display_name)
                        .order_by(func.sum(LineItemRecord.line_total_minor).desc())
                    )
                )
                if receipts
                else ()
            )
        storage = calculate_storage_usage(self.config)
        return DashboardSnapshot(
            inbox_count,
            review_count,
            pending_sync,
            spent,
            overall,
            storage.total_bytes,
            storage.disk_capacity_bytes,
            storage.disk_free_bytes,
            recent,
            category_spending,
        )

    def categories(self) -> list[tuple[str, str]]:
        with session_scope(self.engine) as session:
            return [
                (record.internal_name, record.display_name)
                for record in CategoryRepository(session).list_active()
            ]

    def add_category(self, display_name: str) -> tuple[str, str]:
        """Create a user category and return its stable key and visible name."""
        normalized = " ".join(display_name.split())
        if not normalized or len(normalized) > 80:
            raise ValueError("category name must contain 1 to 80 characters")
        base = re.sub(r"[^a-z0-9]+", "_", normalized.casefold()).strip("_")
        if not base or not base[0].isalpha():
            base = f"category_{base}" if base else "category"
        with session_scope(self.engine) as session:
            repository = CategoryRepository(session)
            if any(
                record.display_name.casefold() == normalized.casefold()
                for record in repository.list_active()
            ):
                raise ValueError("a category with that name already exists")
            internal_name = base
            suffix = 2
            while repository.get_by_internal_name(internal_name) is not None:
                internal_name = f"{base}_{suffix}"
                suffix += 1
            record = repository.create(
                CategoryDraft(internal_name=internal_name, display_name=normalized)
            )
            return record.internal_name, record.display_name

    def rename_category(self, internal_name: str, display_name: str) -> tuple[str, str]:
        """Rename a category without changing its links to existing expenses."""
        normalized = " ".join(display_name.split())
        with session_scope(self.engine) as session:
            repository = CategoryRepository(session)
            record = repository.get_by_internal_name(internal_name)
            if record is None or not record.active:
                raise LookupError("category no longer exists")
            if any(
                other.id != record.id and other.display_name.casefold() == normalized.casefold()
                for other in repository.list_active()
            ):
                raise ValueError("a category with that name already exists")
            renamed = repository.rename(record, normalized)
            return renamed.internal_name, renamed.display_name

    def pending_receipts(self) -> list[ReviewReceipt]:
        with session_scope(self.engine) as session:
            rows: list[ReviewReceipt] = []
            files = ProcessedFileRepository(session)
            for receipt in ReviewService(session).pending_receipts():
                self._ensure_line_item(session, receipt)
                source = receipt.source_file_archive_path or receipt.source_file_original_path
                if (not source or not Path(source).exists()) and receipt.source_file_hash:
                    file_record = files.get_by_hash(receipt.source_file_hash)
                    if file_record is not None:
                        source = file_record.archive_path or file_record.original_path
                reason = session.scalar(
                    select(ReviewCaseRecord.reason)
                    .where(
                        ReviewCaseRecord.receipt_id == receipt.id,
                        ReviewCaseRecord.status == "open",
                    )
                    .order_by(ReviewCaseRecord.created_at.desc())
                )
                rows.append(
                    ReviewReceipt(
                        id=receipt.id,
                        transaction_date=receipt.transaction_date,
                        merchant=receipt.merchant_original,
                        currency=receipt.currency,
                        subtotal_minor=receipt.subtotal_minor,
                        tax_minor=receipt.tax_minor,
                        tip_minor=receipt.tip_minor,
                        discount_minor=receipt.discount_total_minor,
                        final_total_minor=receipt.final_total_minor,
                        source_path=source,
                        review_reason=reason,
                        items=tuple(
                            ReviewItem(
                                item.id,
                                item.description_original,
                                item.line_total_minor,
                                item.category.internal_name,
                            )
                            for item in receipt.line_items
                        ),
                    )
                )
            return rows

    def confirmed_receipt(self, receipt_id: int) -> ReviewReceipt:
        with session_scope(self.engine) as session:
            receipt = session.scalar(
                select(ReceiptRecord)
                .options(
                    selectinload(ReceiptRecord.line_items).selectinload(LineItemRecord.category)
                )
                .where(
                    ReceiptRecord.id == receipt_id,
                    ReceiptRecord.processing_status == ReceiptStatus.CONFIRMED.value,
                )
            )
            if receipt is None:
                raise LookupError("Confirmed expense no longer exists")
            self._ensure_line_item(session, receipt)
            source = receipt.source_file_archive_path or receipt.source_file_original_path
            return ReviewReceipt(
                id=receipt.id,
                transaction_date=receipt.transaction_date,
                merchant=receipt.merchant_original,
                currency=receipt.currency,
                subtotal_minor=receipt.subtotal_minor,
                tax_minor=receipt.tax_minor,
                tip_minor=receipt.tip_minor,
                discount_minor=receipt.discount_total_minor,
                final_total_minor=receipt.final_total_minor,
                source_path=source,
                review_reason=None,
                items=tuple(
                    ReviewItem(
                        item.id,
                        item.description_original,
                        item.line_total_minor,
                        item.category.internal_name,
                    )
                    for item in receipt.line_items
                ),
            )

    @staticmethod
    def _ensure_line_item(session: Session, receipt: ReceiptRecord) -> None:
        """Give legacy single-total receipts one editable, unallocated item."""
        if receipt.line_items:
            return
        category = CategoryRepository(session).seed_defaults()
        unallocated = next(record for record in category if record.internal_name == "unallocated")
        receipt.line_items.append(
            LineItemRecord(
                item_uuid=f"legacy-{receipt.id}",
                description_original="Unitemized purchase",
                description_normalized="unitemized purchase",
                quantity=1,
                unit_price_minor=None,
                line_total_minor=receipt.final_total_minor,
                category=unallocated,
                classification_confidence=0,
                review_status=ReviewStatus.REQUIRED.value,
                manually_corrected=False,
            )
        )
        session.flush()

    def update_confirmed_receipt(self, draft: ReceiptCorrectionDraft) -> None:
        with session_scope(self.engine) as session:
            receipt = session.scalar(
                select(ReceiptRecord)
                .options(selectinload(ReceiptRecord.line_items))
                .where(
                    ReceiptRecord.id == draft.receipt_id,
                    ReceiptRecord.processing_status == ReceiptStatus.CONFIRMED.value,
                )
            )
            if receipt is None:
                raise LookupError("Confirmed expense no longer exists")
            CorrectionService(session).correct_receipt(receipt, draft)

    def delete_receipt(self, receipt_id: int) -> None:
        with session_scope(self.engine) as session:
            receipt = session.scalar(
                select(ReceiptRecord).where(
                    ReceiptRecord.id == receipt_id,
                    ReceiptRecord.processing_status == ReceiptStatus.CONFIRMED.value,
                )
            )
            if receipt is None:
                raise LookupError("Confirmed expense no longer exists")
            CorrectionService(session).delete_receipt(receipt)

    def import_receipts(self, sources: list[Path]) -> tuple[list[Path], list[str]]:
        return ReceiptFileManager(self.config).import_to_inbox(sources)

    def correct_and_confirm_receipt(self, draft: ReceiptCorrectionDraft) -> None:
        with session_scope(self.engine) as session:
            receipt = session.scalar(
                select(ReceiptRecord)
                .options(selectinload(ReceiptRecord.line_items))
                .where(ReceiptRecord.id == draft.receipt_id)
            )
            if receipt is None:
                raise LookupError("Receipt no longer exists")
            CorrectionService(session).correct_receipt(receipt, draft)
            self._archive_review_source(session, receipt)
            ReviewService(session).confirm(receipt)

    def resolve_receipt(self, receipt_id: int, *, confirm: bool) -> None:
        with session_scope(self.engine) as session:
            receipt = session.get(ReceiptRecord, receipt_id)
            if receipt is None:
                raise LookupError("Receipt no longer exists")
            service = ReviewService(session)
            if confirm:
                self._archive_review_source(session, receipt)
                service.confirm(receipt)
            else:
                service.reject(receipt)

    def _archive_review_source(self, session: Session, receipt: ReceiptRecord) -> None:
        if not receipt.source_file_hash:
            return
        repository = ProcessedFileRepository(session)
        record = repository.get_by_hash(receipt.source_file_hash)
        if record is None or not record.archive_path:
            return
        source = Path(record.archive_path)
        if not source.exists():
            return
        result = ReceiptFileManager(self.config).archive_confirmed(source, receipt.transaction_date)
        repository.update_lifecycle(
            record,
            status="archived",
            destination=result.destination,
            archived_size=result.archived_size,
        )
        receipt.source_file_archive_path = (
            None if result.destination is None else str(result.destination)
        )

    def create_manual(self, draft: ManualExpenseDraft | RefundDraft) -> None:
        with session_scope(self.engine) as session:
            if isinstance(draft, RefundDraft):
                RefundService(session).create(draft)
            else:
                ManualExpenseService(session).create(draft)

    def budgets(self, year: int, month: int) -> list[BudgetSummary]:
        with session_scope(self.engine) as session:
            return BudgetService(session).summaries(year, month, self.config.default_currency)

    def set_budget(self, draft: BudgetDraft) -> None:
        with session_scope(self.engine) as session:
            BudgetService(session).set_budget(draft)

    def storage(self) -> StorageReport:
        return calculate_storage_usage(self.config)

    def sync_report(self) -> SyncResult:
        with session_scope(self.engine) as session:
            return ReportSyncService(session, self.config).sync_pending()

    def report_url(self) -> str | None:
        with session_scope(self.engine) as session:
            return ReportSyncService(session, self.config).spreadsheet_url

    def connect_google(self, client_secrets: Path) -> SyncResult:
        with session_scope(self.engine) as session:
            service = ReportSyncService(session, self.config)
            connected = service.connect_account(client_secrets)
            if connected.error:
                return connected
            if service.spreadsheet_id:
                return service.rebuild_report()
            return service.create_report()

    def disconnect_google(self) -> SyncResult:
        with session_scope(self.engine) as session:
            return ReportSyncService(session, self.config).disconnect_account()

    def save_settings(self, config: AppConfig) -> None:
        save_config(config, self.config_path)
        self.config = config
