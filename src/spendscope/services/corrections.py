"""Apply receipt corrections and optionally remember future rules."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from spendscope.categorization.memory import CorrectionMemory
from spendscope.categorization.normalization import normalize_item, normalize_merchant
from spendscope.database.schema import CategoryRecord, LineItemRecord, ReceiptRecord
from spendscope.database.service_repositories import AuditRepository
from spendscope.domain.enums import LineItemKind, ReconciliationStatus, ReviewStatus
from spendscope.domain.models import ReceiptCorrectionDraft
from spendscope.processing.duplicate_detector import build_receipt_fingerprint
from spendscope.services.sync_queue import SyncQueueService


class CorrectionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.memory = CorrectionMemory(session)
        self.audit = AuditRepository(session)
        self.sync = SyncQueueService(session)

    def correct_item(
        self,
        item: LineItemRecord,
        *,
        description: str,
        category_internal_name: str,
        remember: bool = False,
    ) -> None:
        category = self.session.scalar(
            select(CategoryRecord).where(
                CategoryRecord.internal_name == category_internal_name,
                CategoryRecord.active.is_(True),
            )
        )
        if category is None:
            raise ValueError(f"unknown or inactive category: {category_internal_name}")
        original = item.description_original
        item.description_normalized = normalize_item(description)
        item.category = category
        item.classification_confidence = 1.0
        item.review_status = ReviewStatus.RESOLVED.value
        item.manually_corrected = True
        if remember:
            self.memory.remember_item(original, description, category_internal_name)
        self.sync.enqueue("receipt", item.receipt.receipt_uuid, "upsert")
        self.audit.record("line_item", item.id, "corrected", {"remembered": remember})
        self.session.flush()

    def correct_merchant(
        self,
        receipt: ReceiptRecord,
        merchant: str,
        *,
        remember: bool = False,
    ) -> None:
        original = receipt.merchant_original
        receipt.merchant_normalized = normalize_merchant(merchant)
        if remember:
            self.memory.remember_merchant(original, merchant)
        self.sync.enqueue("receipt", receipt.receipt_uuid, "upsert")
        self.audit.record("receipt", receipt.id, "merchant_corrected", {"remembered": remember})
        self.session.flush()

    def correct_receipt(
        self, receipt: ReceiptRecord, draft: ReceiptCorrectionDraft
    ) -> ReceiptRecord:
        if receipt.id != draft.receipt_id:
            raise ValueError("receipt correction targets the wrong receipt")
        categories = {
            record.internal_name: record
            for record in self.session.scalars(
                select(CategoryRecord).where(CategoryRecord.active.is_(True))
            )
        }
        missing = {item.category_internal_name for item in draft.items} - categories.keys()
        if missing:
            raise ValueError(f"unknown or inactive categories: {', '.join(sorted(missing))}")
        existing = {item.id: item for item in receipt.line_items}
        requested_ids = {item.id for item in draft.items if item.id is not None}
        unknown_ids = requested_ids - existing.keys()
        if unknown_ids:
            raise ValueError("one or more receipt items no longer exist")

        original_merchant = receipt.merchant_original
        receipt.merchant_original = draft.merchant.strip()
        receipt.merchant_normalized = normalize_merchant(draft.merchant)
        receipt.transaction_date = draft.transaction_date
        receipt.subtotal_minor = draft.subtotal_minor
        receipt.tax_minor = draft.tax_minor
        receipt.tip_minor = draft.tip_minor
        receipt.discount_total_minor = draft.discount_minor
        receipt.final_total_minor = draft.final_total_minor
        receipt.calculated_total_minor = draft.final_total_minor
        receipt.reconciliation_difference_minor = 0
        receipt.reconciliation_status = ReconciliationStatus.BALANCED.value
        fingerprint = build_receipt_fingerprint(
            draft.merchant,
            draft.transaction_date,
            draft.final_total_minor,
            receipt.currency,
        )
        duplicate = self.session.scalar(
            select(ReceiptRecord).where(
                ReceiptRecord.transaction_fingerprint == fingerprint,
                ReceiptRecord.id != receipt.id,
            )
        )
        if duplicate is not None:
            raise ValueError("another receipt already has this merchant, date, and total")
        receipt.transaction_fingerprint = fingerprint

        for item in tuple(receipt.line_items):
            if item.id not in requested_ids:
                receipt.line_items.remove(item)
        for correction in draft.items:
            category = categories[correction.category_internal_name]
            if correction.id is None:
                receipt.line_items.append(
                    LineItemRecord(
                        item_uuid=str(uuid4()),
                        description_original=correction.description.strip(),
                        description_normalized=normalize_item(correction.description),
                        quantity=1,
                        unit_price_minor=None,
                        line_total_minor=correction.line_total_minor,
                        category=category,
                        classification_confidence=1.0,
                        review_status=ReviewStatus.RESOLVED.value,
                        manually_corrected=True,
                        kind=LineItemKind.PURCHASE.value,
                    )
                )
                continue
            item = existing[correction.id]
            original_description = item.description_original
            item.description_original = correction.description.strip()
            item.description_normalized = normalize_item(correction.description)
            item.line_total_minor = correction.line_total_minor
            item.category = category
            item.classification_confidence = 1.0
            item.review_status = ReviewStatus.RESOLVED.value
            item.manually_corrected = True
            if correction.remember:
                self.memory.remember_item(
                    original_description,
                    correction.description,
                    correction.category_internal_name,
                )
        self.audit.record(
            "receipt",
            receipt.id,
            "receipt_corrected",
            {"merchant_changed": original_merchant != receipt.merchant_original},
        )
        self.sync.enqueue("receipt", receipt.receipt_uuid, "upsert")
        self.session.flush()
        return receipt
