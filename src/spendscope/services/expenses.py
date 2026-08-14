"""Manual expense and refund creation services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from spendscope.categorization.normalization import normalize_item, normalize_merchant
from spendscope.database.repositories import CategoryRepository, ReceiptRepository
from spendscope.database.schema import LineItemRecord, ReceiptRecord
from spendscope.database.service_repositories import (
    AuditRepository,
    ManualExpenseDetailRepository,
    RefundLinkRepository,
)
from spendscope.domain.enums import (
    LineItemKind,
    ReceiptStatus,
    ReviewStatus,
    SourceType,
)
from spendscope.domain.models import LineItemDraft, ManualExpenseDraft, ReceiptDraft, RefundDraft
from spendscope.services.sync_queue import SyncQueueService


class ManualExpenseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.receipts = ReceiptRepository(session)
        self.details = ManualExpenseDetailRepository(session)
        self.audit = AuditRepository(session)
        self.sync = SyncQueueService(session)

    def create(self, draft: ManualExpenseDraft) -> ReceiptRecord:
        CategoryRepository(self.session).seed_defaults()
        receipt = self.receipts.create(self._receipt_draft(draft))
        self.details.upsert(receipt.id, draft.note)
        self.sync.enqueue("receipt", receipt.receipt_uuid, "upsert")
        self.audit.record("receipt", receipt.id, "manual_expense_created")
        return receipt

    def update(self, receipt: ReceiptRecord, draft: ManualExpenseDraft) -> ReceiptRecord:
        if receipt.source_type != SourceType.MANUAL.value:
            raise ValueError("only manual expenses can be edited by this service")
        replacement = self._receipt_draft(draft)
        category = CategoryRepository(self.session).get_by_internal_name(
            draft.category_internal_name
        )
        if category is None or not category.active:
            raise ValueError(f"unknown or inactive category: {draft.category_internal_name}")
        receipt.merchant_original = replacement.merchant_original
        receipt.merchant_normalized = replacement.merchant_normalized
        receipt.transaction_date = replacement.transaction_date
        receipt.currency = replacement.currency
        receipt.subtotal_minor = replacement.subtotal_minor
        receipt.tax_minor = replacement.tax_minor
        receipt.tip_minor = replacement.tip_minor
        receipt.final_total_minor = replacement.final_total_minor
        receipt.calculated_total_minor = replacement.final_total_minor
        receipt.reconciliation_difference_minor = 0
        item = receipt.line_items[0]
        item.description_original = draft.description
        item.description_normalized = normalize_item(draft.description)
        item.line_total_minor = draft.amount_minor
        item.unit_price_minor = draft.amount_minor
        item.category = category
        item.manually_corrected = True
        self.details.upsert(receipt.id, draft.note)
        self.sync.enqueue("receipt", receipt.receipt_uuid, "upsert")
        self.audit.record("receipt", receipt.id, "manual_expense_updated")
        self.session.flush()
        return receipt

    @staticmethod
    def _receipt_draft(draft: ManualExpenseDraft) -> ReceiptDraft:
        merchant = (draft.merchant or "Manual Expense").strip()
        return ReceiptDraft(
            merchant_original=merchant,
            merchant_normalized=normalize_merchant(merchant),
            transaction_date=draft.transaction_date,
            currency=draft.currency,
            subtotal_minor=draft.amount_minor,
            tax_minor=draft.tax_minor,
            tip_minor=draft.tip_minor,
            final_total_minor=draft.amount_minor + draft.tax_minor + draft.tip_minor,
            status=ReceiptStatus.CONFIRMED,
            review_status=ReviewStatus.NOT_REQUIRED,
            source_type=SourceType.MANUAL,
            extraction_confidence=1.0,
            items=[
                LineItemDraft(
                    description_original=draft.description,
                    description_normalized=normalize_item(draft.description),
                    unit_price_minor=draft.amount_minor,
                    line_total_minor=draft.amount_minor,
                    category_internal_name=draft.category_internal_name,
                    classification_confidence=1.0,
                    review_status=ReviewStatus.NOT_REQUIRED,
                    manually_corrected=True,
                )
            ],
        )


class RefundService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.receipts = ReceiptRepository(session)
        self.links = RefundLinkRepository(session)
        self.audit = AuditRepository(session)
        self.sync = SyncQueueService(session)

    def create(self, draft: RefundDraft) -> ReceiptRecord:
        CategoryRepository(self.session).seed_defaults()
        self._validate_references(draft)
        merchant = (draft.merchant or "Refund").strip()
        receipt = self.receipts.create(
            ReceiptDraft(
                merchant_original=merchant,
                merchant_normalized=normalize_merchant(merchant),
                transaction_date=draft.transaction_date,
                currency=draft.currency,
                subtotal_minor=-draft.amount_minor,
                final_total_minor=-draft.amount_minor,
                status=ReceiptStatus.CONFIRMED,
                review_status=ReviewStatus.NOT_REQUIRED,
                source_type=SourceType.MANUAL,
                extraction_confidence=1.0,
                items=[
                    LineItemDraft(
                        description_original=draft.description,
                        description_normalized=normalize_item(draft.description),
                        unit_price_minor=-draft.amount_minor,
                        line_total_minor=-draft.amount_minor,
                        category_internal_name=draft.category_internal_name,
                        classification_confidence=1.0,
                        review_status=ReviewStatus.NOT_REQUIRED,
                        manually_corrected=True,
                        kind=LineItemKind.REFUND,
                    )
                ],
            )
        )
        self.links.create(
            refund_receipt_id=receipt.id,
            refund_line_item_id=receipt.line_items[0].id,
            original_receipt_id=draft.original_receipt_id,
            original_line_item_id=draft.original_line_item_id,
        )
        self.sync.enqueue("receipt", receipt.receipt_uuid, "upsert")
        self.audit.record("receipt", receipt.id, "refund_created")
        return receipt

    def _validate_references(self, draft: RefundDraft) -> None:
        original_receipt = (
            None
            if draft.original_receipt_id is None
            else self.session.get(ReceiptRecord, draft.original_receipt_id)
        )
        if draft.original_receipt_id is not None and original_receipt is None:
            raise ValueError("original receipt does not exist")
        original_item = (
            None
            if draft.original_line_item_id is None
            else self.session.get(LineItemRecord, draft.original_line_item_id)
        )
        if draft.original_line_item_id is not None and original_item is None:
            raise ValueError("original line item does not exist")
        if (
            original_receipt is not None
            and original_item is not None
            and original_item.receipt_id != original_receipt.id
        ):
            raise ValueError("original line item does not belong to the original receipt")
