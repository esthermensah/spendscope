"""End-to-end local receipt processing orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from spendscope.categorization.memory import CorrectionMemory
from spendscope.categorization.models import CategorizedReceipt, ReceiptContext
from spendscope.categorization.normalization import normalize_merchant
from spendscope.config import AppConfig
from spendscope.database.repositories import (
    CategoryRepository,
    ProcessedFileRepository,
    ReceiptRepository,
)
from spendscope.database.schema import ReceiptRecord
from spendscope.database.service_repositories import AuditRepository
from spendscope.domain.enums import ReviewSeverity, SourceType
from spendscope.domain.models import LineItemDraft, Money, ReceiptDraft
from spendscope.extraction.receipt_extractor import ReceiptTextExtractor
from spendscope.parsing.models import ParsedReceipt
from spendscope.parsing.receipt_parser import ReceiptParser
from spendscope.processing.confidence import ConfidenceDecision, ConfidencePolicy
from spendscope.processing.duplicate_detector import check_likely_receipt_duplicate
from spendscope.processing.pipeline import StoragePipeline
from spendscope.processing.reconciliation import ReconciliationOutcome, reconcile_amounts
from spendscope.services.review import ReviewService
from spendscope.services.sync_queue import SyncQueueService


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    processed_file_id: int
    receipt_id: int | None
    status: str
    confidence: ConfidenceDecision | None = None
    reason: str | None = None


class ReceiptProcessingService:
    def __init__(
        self,
        config: AppConfig,
        session: Session,
        extractor: ReceiptTextExtractor,
    ) -> None:
        self.config = config
        self.session = session
        self.extractor = extractor
        self.files = ProcessedFileRepository(session)
        self.storage = StoragePipeline(config, session)
        self.audit = AuditRepository(session)
        self.sync = SyncQueueService(session)

    def process(self, path: Path, processed_file_id: int) -> ProcessingResult:
        file_record = self.files.get(processed_file_id)
        if file_record is None:
            raise LookupError(f"processed file {processed_file_id} does not exist")
        self.files.update_lifecycle(file_record, status="processing")
        try:
            extraction = self.extractor.extract(path)
            parsed = ReceiptParser(
                default_currency=self.config.default_currency,
                date_locale=self.config.date_locale,
                reconciliation_tolerance_minor=self.config.reconciliation_tolerance_minor,
            ).parse(
                extraction.text,
                file_modified=datetime.fromtimestamp(path.stat().st_mtime),
                imported_at=datetime.now(),
            )
            if parsed.merchant.value is None or parsed.transaction_date.value is None:
                return self._fail_to_review(
                    file_record.id, "merchant or transaction date could not be determined"
                )
            if parsed.final_total.value is None or parsed.currency.value is None:
                return self._fail_to_review(
                    file_record.id, "currency or final total could not be determined"
                )

            merchant_normalized = CorrectionMemory(self.session).normalize_merchant_name(
                parsed.merchant.value
            )
            context = ReceiptContext(parsed.merchant.value, merchant_normalized)
            categorized = (
                CorrectionMemory(self.session)
                .categorizer()
                .categorize_receipt(parsed.items, context)
            )
            currency = parsed.currency.value
            item_totals = tuple(
                Money.from_decimal(entry.item.line_total, currency).minor_units
                for entry in categorized.items
            )
            subtotal_minor = self._minor(parsed.subtotal.value, currency)
            tax_minor = self._minor(parsed.tax.value, currency) or 0
            tip_minor = self._minor(parsed.tip.value, currency) or 0
            discount_minor = self._minor(parsed.discount.value, currency) or 0
            printed_total_minor = self._minor(parsed.final_total.value, currency)
            assert printed_total_minor is not None
            reconciliation = reconcile_amounts(
                item_totals_minor=item_totals,
                subtotal_minor=subtotal_minor,
                tax_minor=tax_minor,
                tip_minor=tip_minor,
                discount_minor=discount_minor,
                printed_total_minor=printed_total_minor,
                tolerance_minor=self.config.reconciliation_tolerance_minor,
            )
            decision = ConfidencePolicy(self.config.confidence).decide(
                extraction_confidence=min(extraction.confidence, parsed.confidence),
                categorization_confidence=categorized.confidence,
                reconciliation_status=reconciliation.status,
                validation_errors=parsed.errors,
            )
            duplicate = check_likely_receipt_duplicate(
                self.session,
                merchant=merchant_normalized,
                transaction_date=parsed.transaction_date.value,
                final_total_minor=printed_total_minor,
                currency=currency,
                receipt_number=parsed.receipt_number.value,
            )
            if duplicate.likely_duplicate:
                self.storage.require_review(file_record.id)
                self.files.update_lifecycle(
                    file_record,
                    status="duplicate",
                    destination=Path(file_record.archive_path or path),
                )
                self.audit.record(
                    "processed_file",
                    file_record.id,
                    "likely_duplicate",
                    {"reason": duplicate.reason or "matching receipt"},
                )
                return ProcessingResult(
                    file_record.id, None, "duplicate", decision, duplicate.reason
                )

            receipt = self._save_receipt(
                path=path,
                file_hash=file_record.file_hash,
                parsed=parsed,
                categorized=categorized,
                reconciliation=reconciliation,
                decision=decision,
                transaction_fingerprint=duplicate.fingerprint,
            )
            if decision.archive_ready:
                self.storage.archive_confirmed(file_record.id, receipt.transaction_date)
                self.sync.enqueue("receipt", receipt.receipt_uuid, "upsert")
            else:
                self.storage.require_review(file_record.id)
                ReviewService(self.session).flag(
                    receipt,
                    "; ".join(decision.reasons) or "receipt requires review",
                    severity=(
                        ReviewSeverity.HIGH
                        if decision.review_status.value == "required"
                        else ReviewSeverity.MEDIUM
                    ),
                )
                if decision.reporting_ready:
                    self.sync.enqueue("receipt", receipt.receipt_uuid, "upsert")
            self.audit.record("receipt", receipt.id, "processed", {"status": decision.level.value})
            return ProcessingResult(file_record.id, receipt.id, decision.level.value, decision)
        except Exception as exc:
            return self._fail_to_review(file_record.id, str(exc))

    def _save_receipt(
        self,
        *,
        path: Path,
        file_hash: str,
        parsed: ParsedReceipt,
        categorized: CategorizedReceipt,
        reconciliation: ReconciliationOutcome,
        decision: ConfidenceDecision,
        transaction_fingerprint: str,
    ) -> ReceiptRecord:
        currency = parsed.currency.value
        printed_total = parsed.final_total.value
        transaction_date = parsed.transaction_date.value
        merchant = parsed.merchant.value
        if (
            currency is None
            or printed_total is None
            or transaction_date is None
            or merchant is None
        ):
            raise ValueError("required receipt fields are missing")
        CategoryRepository(self.session).seed_defaults()
        item_drafts = [
            LineItemDraft(
                description_original=entry.item.description,
                description_normalized=entry.categorization.normalized_description,
                quantity=entry.item.quantity,
                unit_price_minor=self._minor(entry.item.unit_price, currency),
                line_total_minor=Money.from_decimal(entry.item.line_total, currency).minor_units,
                category_internal_name=entry.categorization.category_internal_name,
                classification_confidence=entry.categorization.confidence,
                review_status=decision.review_status,
            )
            for entry in categorized.items
        ]
        if not item_drafts:
            item_drafts.append(
                LineItemDraft(
                    description_original="Unitemized purchase",
                    description_normalized="unitemized purchase",
                    line_total_minor=Money.from_decimal(printed_total, currency).minor_units,
                    category_internal_name="unallocated",
                    classification_confidence=0,
                    review_status=decision.review_status,
                )
            )
        subtotal_minor = self._minor(parsed.subtotal.value, currency)
        if subtotal_minor is None:
            subtotal_minor = sum(item.line_total_minor for item in item_drafts)
        receipt = ReceiptRepository(self.session).create(
            ReceiptDraft(
                merchant_original=merchant,
                merchant_normalized=normalize_merchant(merchant),
                transaction_date=transaction_date,
                currency=currency,
                subtotal_minor=subtotal_minor,
                tax_minor=self._minor(parsed.tax.value, currency) or 0,
                tip_minor=self._minor(parsed.tip.value, currency) or 0,
                discount_minor=self._minor(parsed.discount.value, currency) or 0,
                final_total_minor=Money.from_decimal(printed_total, currency).minor_units,
                calculated_total_minor=reconciliation.calculated_total_minor,
                reconciliation_difference_minor=reconciliation.difference_minor,
                reconciliation_status=reconciliation.status,
                status=decision.receipt_status,
                review_status=decision.review_status,
                source_type=SourceType.PDF
                if path.suffix.casefold() == ".pdf"
                else SourceType.IMAGE,
                date_source=parsed.date_source,
                receipt_number=parsed.receipt_number.value,
                source_file_name=path.name,
                source_file_original_path=str(path.resolve()),
                source_file_hash=file_hash,
                transaction_fingerprint=transaction_fingerprint,
                extraction_confidence=decision.score,
                items=item_drafts,
            )
        )
        return receipt

    def _fail_to_review(self, processed_file_id: int, reason: str) -> ProcessingResult:
        record = self.files.get(processed_file_id)
        if record is None:
            raise LookupError(f"processed file {processed_file_id} does not exist")
        source = Path(record.original_path)
        destination = None
        if source.exists() and source.parent.resolve() == self.config.directory_paths()["inbox"]:
            destination = self.storage.require_review(processed_file_id)
        elif record.archive_path is not None:
            destination = Path(record.archive_path)
        self.files.update_lifecycle(
            record, status="failed", destination=destination, error_message=reason
        )
        self.audit.record("processed_file", processed_file_id, "failed")
        return ProcessingResult(processed_file_id, None, "failed", reason=reason)

    @staticmethod
    def _minor(value: Decimal | None, currency: str) -> int | None:
        return None if value is None else Money.from_decimal(value, currency).minor_units
