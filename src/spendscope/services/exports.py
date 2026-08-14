"""Local CSV exports and structured JSON backup."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from spendscope.database.schema import (
    BudgetRecord,
    CategoryRecord,
    ItemRuleRecord,
    LineItemRecord,
    MerchantRuleRecord,
    ReceiptRecord,
    ReviewCaseRecord,
    SettingRecord,
)
from spendscope.database.service_repositories import AuditRepository


@dataclass(frozen=True, slots=True)
class ExportBundle:
    receipts_csv: Path
    line_items_csv: Path
    budgets_csv: Path
    backup_json: Path


class LocalExportService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def export_all(self, destination: Path) -> ExportBundle:
        destination = destination.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        bundle = ExportBundle(
            destination / "receipts.csv",
            destination / "line_items.csv",
            destination / "budgets.csv",
            destination / "spendscope-backup.json",
        )
        self._write_csv(bundle.receipts_csv, self._receipt_rows())
        self._write_csv(bundle.line_items_csv, self._item_rows())
        self._write_csv(bundle.budgets_csv, self._budget_rows())
        self._write_json(bundle.backup_json, self._backup())
        self.audit.record("export", "local", "completed")
        return bundle

    def _receipt_rows(self) -> list[dict[str, object]]:
        records = self.session.scalars(
            select(ReceiptRecord).order_by(ReceiptRecord.transaction_date, ReceiptRecord.id)
        )
        return [
            {
                "receipt_uuid": record.receipt_uuid,
                "transaction_date": record.transaction_date.isoformat(),
                "merchant": record.merchant_normalized,
                "currency": record.currency,
                "subtotal_minor": record.subtotal_minor,
                "tax_minor": record.tax_minor,
                "tip_minor": record.tip_minor,
                "discount_minor": record.discount_total_minor,
                "final_total_minor": record.final_total_minor,
                "reconciliation_status": record.reconciliation_status,
                "review_status": record.review_status,
                "source_type": record.source_type,
            }
            for record in records
        ]

    def _item_rows(self) -> list[dict[str, object]]:
        rows = self.session.execute(
            select(LineItemRecord, ReceiptRecord, CategoryRecord)
            .join(ReceiptRecord, LineItemRecord.receipt_id == ReceiptRecord.id)
            .join(CategoryRecord, LineItemRecord.category_id == CategoryRecord.id)
            .order_by(ReceiptRecord.transaction_date, LineItemRecord.id)
        )
        return [
            {
                "item_uuid": item.item_uuid,
                "receipt_uuid": receipt.receipt_uuid,
                "transaction_date": receipt.transaction_date.isoformat(),
                "description": item.description_normalized,
                "quantity": str(item.quantity),
                "unit_price_minor": item.unit_price_minor,
                "line_total_minor": item.line_total_minor,
                "category": category.internal_name,
                "currency": receipt.currency,
                "kind": item.kind,
                "review_status": item.review_status,
            }
            for item, receipt, category in rows
        ]

    def _budget_rows(self) -> list[dict[str, object]]:
        rows = self.session.execute(
            select(BudgetRecord, CategoryRecord)
            .outerjoin(CategoryRecord, BudgetRecord.category_id == CategoryRecord.id)
            .order_by(BudgetRecord.year, BudgetRecord.month, BudgetRecord.id)
        )
        return [
            {
                "year": budget.year,
                "month": budget.month,
                "category": None if category is None else category.internal_name,
                "currency": budget.currency,
                "amount_minor": budget.budget_amount_minor,
                "warning_threshold": budget.warning_threshold,
            }
            for budget, category in rows
        ]

    def _backup(self) -> dict[str, Any]:
        receipts = self.session.scalars(
            select(ReceiptRecord)
            .options(selectinload(ReceiptRecord.line_items))
            .order_by(ReceiptRecord.id)
        )
        return {
            "format_version": 1,
            "categories": [
                {
                    "internal_name": record.internal_name,
                    "display_name": record.display_name,
                    "active": record.active,
                    "system_category": record.system_category,
                }
                for record in self.session.scalars(
                    select(CategoryRecord).order_by(CategoryRecord.id)
                )
            ],
            "receipts": [
                {
                    "receipt_uuid": receipt.receipt_uuid,
                    "merchant_original": receipt.merchant_original,
                    "merchant_normalized": receipt.merchant_normalized,
                    "transaction_date": receipt.transaction_date.isoformat(),
                    "currency": receipt.currency,
                    "subtotal_minor": receipt.subtotal_minor,
                    "tax_minor": receipt.tax_minor,
                    "tip_minor": receipt.tip_minor,
                    "discount_minor": receipt.discount_total_minor,
                    "final_total_minor": receipt.final_total_minor,
                    "processing_status": receipt.processing_status,
                    "review_status": receipt.review_status,
                    "source_type": receipt.source_type,
                    "items": [
                        {
                            "item_uuid": item.item_uuid,
                            "description_original": item.description_original,
                            "description_normalized": item.description_normalized,
                            "quantity": str(item.quantity),
                            "unit_price_minor": item.unit_price_minor,
                            "line_total_minor": item.line_total_minor,
                            "category_id": item.category_id,
                            "kind": item.kind,
                        }
                        for item in receipt.line_items
                    ],
                }
                for receipt in receipts
            ],
            "budgets": self._budget_rows(),
            "item_rules": [
                {
                    "item_pattern": rule.item_pattern,
                    "normalized_item": rule.normalized_item,
                    "preferred_category_id": rule.preferred_category_id,
                }
                for rule in self.session.scalars(select(ItemRuleRecord).order_by(ItemRuleRecord.id))
            ],
            "merchant_rules": [
                {
                    "merchant_pattern": rule.merchant_pattern,
                    "normalized_merchant": rule.normalized_merchant,
                    "preferred_category_id": rule.preferred_category_id,
                }
                for rule in self.session.scalars(
                    select(MerchantRuleRecord).order_by(MerchantRuleRecord.id)
                )
            ],
            "review_cases": [
                {
                    "receipt_id": case.receipt_id,
                    "reason": case.reason,
                    "severity": case.severity,
                    "status": case.status,
                }
                for case in self.session.scalars(
                    select(ReviewCaseRecord).order_by(ReviewCaseRecord.id)
                )
            ],
            "settings": {
                setting.key: json.loads(setting.value)
                for setting in self.session.scalars(
                    select(SettingRecord).order_by(SettingRecord.key)
                )
            },
        }

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        fieldnames = list(rows[0]) if rows else []
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            if fieldnames:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        os.replace(temporary, path)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
