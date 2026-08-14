"""Transaction-aware repositories for Phase 1 entities."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from spendscope.config import DEFAULT_CATEGORIES
from spendscope.database.schema import (
    CategoryRecord,
    ItemRuleRecord,
    LineItemRecord,
    MerchantRuleRecord,
    ProcessedFileRecord,
    ReceiptRecord,
    SettingRecord,
)
from spendscope.domain.enums import ReceiptStatus
from spendscope.domain.models import CategoryDraft, ReceiptDraft


class CategoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, draft: CategoryDraft) -> CategoryRecord:
        record = CategoryRecord(**draft.model_dump())
        self.session.add(record)
        self.session.flush()
        return record

    def get_by_internal_name(self, internal_name: str) -> CategoryRecord | None:
        return self.session.scalar(
            select(CategoryRecord).where(CategoryRecord.internal_name == internal_name)
        )

    def list_active(self) -> list[CategoryRecord]:
        return list(
            self.session.scalars(
                select(CategoryRecord)
                .where(CategoryRecord.active.is_(True))
                .order_by(CategoryRecord.display_name)
            )
        )

    def seed_defaults(self) -> list[CategoryRecord]:
        records = []
        for internal_name, display_name in DEFAULT_CATEGORIES:
            existing = self.get_by_internal_name(internal_name)
            if existing is None:
                existing = self.create(
                    CategoryDraft(
                        internal_name=internal_name,
                        display_name=display_name,
                        system_category=internal_name in {"tax", "tips", "unallocated"},
                    )
                )
            records.append(existing)
        return records

    def rename(self, record: CategoryRecord, display_name: str) -> CategoryRecord:
        if record.internal_name in {"tax", "tips"}:
            raise ValueError("Tax and Tips category names are fixed")
        normalized = display_name.strip()
        if not normalized or len(normalized) > 80:
            raise ValueError("category display name must contain 1 to 80 characters")
        record.display_name = normalized
        self.session.flush()
        return record

    def set_active(self, record: CategoryRecord, *, active: bool) -> CategoryRecord:
        if not active and record.system_category:
            raise ValueError("system categories cannot be disabled")
        record.active = active
        self.session.flush()
        return record

    def restore_defaults(self) -> list[CategoryRecord]:
        records = self.seed_defaults()
        names = dict(DEFAULT_CATEGORIES)
        for record in records:
            record.display_name = names[record.internal_name]
            record.active = True
        self.session.flush()
        return records


class ReceiptRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, draft: ReceiptDraft) -> ReceiptRecord:
        categories = {
            record.internal_name: record
            for record in self.session.scalars(select(CategoryRecord)).all()
        }
        missing = {item.category_internal_name for item in draft.items} - categories.keys()
        if missing:
            raise ValueError(f"unknown categories: {', '.join(sorted(missing))}")

        record = ReceiptRecord(
            receipt_uuid=str(draft.receipt_uuid),
            merchant_original=draft.merchant_original,
            merchant_normalized=draft.merchant_normalized,
            transaction_date=draft.transaction_date,
            subtotal_minor=draft.subtotal_minor,
            tax_minor=draft.tax_minor,
            tip_minor=draft.tip_minor,
            discount_total_minor=draft.discount_minor,
            final_total_minor=draft.final_total_minor,
            calculated_total_minor=draft.calculated_total_minor,
            reconciliation_difference_minor=draft.reconciliation_difference_minor,
            currency=draft.currency,
            date_source=draft.date_source,
            receipt_number=draft.receipt_number,
            source_file_name=draft.source_file_name,
            source_file_original_path=draft.source_file_original_path,
            source_file_hash=draft.source_file_hash,
            transaction_fingerprint=draft.transaction_fingerprint,
            raw_extracted_text_path=draft.raw_extracted_text_path,
            extraction_confidence=draft.extraction_confidence,
            processing_status=draft.status.value,
            reconciliation_status=draft.reconciliation_status.value,
            review_status=draft.review_status.value,
            sync_status="local_only",
            source_type=draft.source_type.value,
            confirmed_at=(datetime.now() if draft.status is ReceiptStatus.CONFIRMED else None),
        )
        for item in draft.items:
            record.line_items.append(
                LineItemRecord(
                    item_uuid=str(item.id),
                    description_original=item.description_original,
                    description_normalized=item.description_normalized,
                    quantity=item.quantity,
                    unit_price_minor=item.unit_price_minor,
                    line_total_minor=item.line_total_minor,
                    category=categories[item.category_internal_name],
                    classification_confidence=item.classification_confidence,
                    review_status=item.review_status.value,
                    manually_corrected=item.manually_corrected,
                    kind=item.kind.value,
                )
            )
        self.session.add(record)
        self.session.flush()
        return record

    def get_by_uuid(self, receipt_uuid: str) -> ReceiptRecord | None:
        return self.session.scalar(
            select(ReceiptRecord)
            .options(selectinload(ReceiptRecord.line_items))
            .where(ReceiptRecord.receipt_uuid == receipt_uuid)
        )

    def list_by_currency(self, currency: str) -> list[ReceiptRecord]:
        return list(
            self.session.scalars(
                select(ReceiptRecord)
                .where(ReceiptRecord.currency == currency.upper())
                .order_by(ReceiptRecord.transaction_date.desc())
            )
        )

    def get_by_fingerprint(self, fingerprint: str) -> ReceiptRecord | None:
        return self.session.scalar(
            select(ReceiptRecord).where(ReceiptRecord.transaction_fingerprint == fingerprint)
        )

    def find_by_receipt_number(
        self, receipt_number: str, merchant_normalized: str
    ) -> ReceiptRecord | None:
        return self.session.scalar(
            select(ReceiptRecord).where(
                ReceiptRecord.receipt_number == receipt_number,
                ReceiptRecord.merchant_normalized == merchant_normalized,
            )
        )

    def find_by_receipt_number_and_amount(
        self, receipt_number: str, final_total_minor: int, currency: str
    ) -> ReceiptRecord | None:
        return self.session.scalar(
            select(ReceiptRecord).where(
                ReceiptRecord.receipt_number == receipt_number,
                ReceiptRecord.final_total_minor == final_total_minor,
                ReceiptRecord.currency == currency.upper(),
            )
        )


class ItemRuleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        item_pattern: str,
        normalized_item: str,
        category_internal_name: str,
    ) -> ItemRuleRecord:
        category = self.session.scalar(
            select(CategoryRecord).where(
                CategoryRecord.internal_name == category_internal_name,
                CategoryRecord.active.is_(True),
            )
        )
        if category is None:
            raise ValueError(f"unknown or inactive category: {category_internal_name}")
        record = self.session.scalar(
            select(ItemRuleRecord).where(ItemRuleRecord.item_pattern == item_pattern)
        )
        if record is None:
            record = ItemRuleRecord(
                item_pattern=item_pattern,
                normalized_item=normalized_item,
                preferred_category_id=category.id,
            )
            self.session.add(record)
        else:
            record.normalized_item = normalized_item
            record.preferred_category_id = category.id
        self.session.flush()
        return record

    def list_for_categorizer(self) -> dict[str, tuple[str, str]]:
        rows = self.session.execute(
            select(ItemRuleRecord, CategoryRecord)
            .join(CategoryRecord, ItemRuleRecord.preferred_category_id == CategoryRecord.id)
            .where(CategoryRecord.active.is_(True))
        ).all()
        return {
            rule.item_pattern: (rule.normalized_item, category.internal_name)
            for rule, category in rows
        }

    def delete(self, item_pattern: str) -> bool:
        record = self.session.scalar(
            select(ItemRuleRecord).where(ItemRuleRecord.item_pattern == item_pattern)
        )
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True


class MerchantRuleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        merchant_pattern: str,
        normalized_merchant: str,
        preferred_category_internal_name: str | None = None,
    ) -> MerchantRuleRecord:
        category_id = None
        if preferred_category_internal_name is not None:
            category = self.session.scalar(
                select(CategoryRecord).where(
                    CategoryRecord.internal_name == preferred_category_internal_name,
                    CategoryRecord.active.is_(True),
                )
            )
            if category is None:
                raise ValueError(
                    f"unknown or inactive category: {preferred_category_internal_name}"
                )
            category_id = category.id
        record = self.session.scalar(
            select(MerchantRuleRecord).where(
                MerchantRuleRecord.merchant_pattern == merchant_pattern
            )
        )
        if record is None:
            record = MerchantRuleRecord(
                merchant_pattern=merchant_pattern,
                normalized_merchant=normalized_merchant,
                preferred_category_id=category_id,
            )
            self.session.add(record)
        else:
            record.normalized_merchant = normalized_merchant
            record.preferred_category_id = category_id
        self.session.flush()
        return record

    def list_category_fallbacks(self) -> dict[str, str]:
        rows = self.session.execute(
            select(MerchantRuleRecord, CategoryRecord).join(
                CategoryRecord,
                MerchantRuleRecord.preferred_category_id == CategoryRecord.id,
            )
        ).all()
        fallbacks: dict[str, str] = {}
        for rule, category in rows:
            fallbacks[rule.merchant_pattern] = category.internal_name
            fallbacks[rule.normalized_merchant] = category.internal_name
        return fallbacks

    def resolve_normalized(self, merchant_pattern: str) -> str | None:
        record = self.session.scalar(
            select(MerchantRuleRecord).where(
                MerchantRuleRecord.merchant_pattern == merchant_pattern
            )
        )
        return None if record is None else record.normalized_merchant

    def delete(self, merchant_pattern: str) -> bool:
        record = self.session.scalar(
            select(MerchantRuleRecord).where(
                MerchantRuleRecord.merchant_pattern == merchant_pattern
            )
        )
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True


class SettingsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def set(self, key: str, value: object) -> SettingRecord:
        record = self.session.get(SettingRecord, key)
        serialized = json.dumps(value, sort_keys=True)
        if record is None:
            record = SettingRecord(key=key, value=serialized)
            self.session.add(record)
        else:
            record.value = serialized
        self.session.flush()
        return record

    def get(self, key: str, default: object | None = None) -> object | None:
        record = self.session.get(SettingRecord, key)
        return default if record is None else json.loads(record.value)

    def set_many(self, entries: Iterable[tuple[str, object]]) -> None:
        for key, value in entries:
            self.set(key, value)


class ProcessedFileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_hash(self, file_hash: str) -> ProcessedFileRecord | None:
        return self.session.scalar(
            select(ProcessedFileRecord).where(ProcessedFileRecord.file_hash == file_hash)
        )

    def get(self, record_id: int) -> ProcessedFileRecord | None:
        return self.session.get(ProcessedFileRecord, record_id)

    def create_discovered(self, path: Path, file_hash: str) -> ProcessedFileRecord:
        record = ProcessedFileRecord(
            file_name=path.name,
            original_path=str(path.resolve()),
            file_hash=file_hash,
            processing_status="discovered",
            original_file_size=path.stat().st_size,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def update_lifecycle(
        self,
        record: ProcessedFileRecord,
        *,
        status: str,
        destination: Path | None = None,
        archived_size: int | None = None,
        error_message: str | None = None,
    ) -> None:
        record.processing_status = status
        record.archive_path = None if destination is None else str(destination.resolve())
        record.archived_file_size = archived_size
        if archived_size is not None and record.original_file_size:
            record.compression_ratio = archived_size / record.original_file_size
        record.error_message = error_message
        self.session.flush()
