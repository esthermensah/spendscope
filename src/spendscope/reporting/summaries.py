"""Build deterministic report tables from the authoritative local database."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from spendscope.database.schema import (
    BudgetRecord,
    CategoryRecord,
    LineItemRecord,
    ReceiptRecord,
    ReviewCaseRecord,
)
from spendscope.domain.enums import ReceiptStatus
from spendscope.reporting.models import DashboardChart, ReportSnapshot, SheetTable
from spendscope.services.budgets import BudgetService

SHEET_NAMES: tuple[str, ...] = (
    "Dashboard",
    "Items",
    "Receipts",
    "Budgets",
    "Monthly Summary",
    "Annual Summary",
    "Category Summary",
    "Merchant Summary",
    "Review Log",
    "Metadata",
)


@dataclass(frozen=True, slots=True)
class _Item:
    item_id: str
    receipt_id: str
    transaction_date: date
    merchant: str
    description: str
    normalized: str
    category: str
    category_internal: str
    subcategory: str
    quantity: Decimal
    unit_price_minor: int | None
    total_minor: int
    currency: str
    confidence: float
    review_status: str
    corrected: bool
    source_type: str


def _major(value: int) -> float:
    return float(Decimal(value) / Decimal(100))


class ReportBuilder:
    """Calculate every reporting sheet locally, without fragile sheet formulas."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self.session = session
        self.now = now or datetime.now()

    def build(
        self,
        *,
        selected_month: str | None = None,
        selected_currency: str | None = None,
        last_successful_sync: str | None = None,
    ) -> ReportSnapshot:
        receipts = list(
            self.session.scalars(
                select(ReceiptRecord).order_by(ReceiptRecord.transaction_date, ReceiptRecord.id)
            )
        )
        spend_receipts = [
            receipt
            for receipt in receipts
            if receipt.processing_status == ReceiptStatus.CONFIRMED.value
        ]
        items = self._items(spend_receipts)
        currencies = sorted({receipt.currency for receipt in spend_receipts})
        currency = (selected_currency or (currencies[0] if currencies else "USD")).upper()
        available_months = sorted(
            {
                receipt.transaction_date.strftime("%Y-%m")
                for receipt in spend_receipts
                if receipt.currency == currency
            }
        )
        month = selected_month or (
            available_months[-1] if available_months else self.now.strftime("%Y-%m")
        )
        dashboard = self._dashboard(spend_receipts, items, month, currency, last_successful_sync)
        tables = (
            dashboard,
            self._items_table(items),
            self._receipts_table(receipts),
            self._budgets_table(),
            self._summary_table(items, annual=False),
            self._summary_table(items, annual=True),
            self._category_summary(items),
            self._merchant_summary(spend_receipts, items),
            self._review_log(),
            self._metadata(month, currency, currencies, last_successful_sync),
        )
        return ReportSnapshot(
            generated_at=self.now,
            selected_month=month,
            selected_currency=currency,
            tables=tables,
            dashboard_charts=(
                DashboardChart(
                    "Spending by Category", "PIE", 3, (4,), 0, len(dashboard.rows) + 1, 1, 13
                ),
                DashboardChart(
                    "Budget vs Actual", "COLUMN", 6, (7, 8), 0, len(dashboard.rows) + 1, 19, 13
                ),
                DashboardChart(
                    "Monthly Spending Trend", "LINE", 10, (11,), 0, len(dashboard.rows) + 1, 37, 13
                ),
            ),
        )

    def _items(self, receipts: list[ReceiptRecord]) -> list[_Item]:
        receipt_ids = {receipt.id for receipt in receipts}
        if not receipt_ids:
            return []
        rows = self.session.execute(
            select(LineItemRecord, ReceiptRecord, CategoryRecord)
            .join(ReceiptRecord, LineItemRecord.receipt_id == ReceiptRecord.id)
            .join(CategoryRecord, LineItemRecord.category_id == CategoryRecord.id)
            .where(LineItemRecord.receipt_id.in_(receipt_ids))
            .order_by(ReceiptRecord.transaction_date, LineItemRecord.id)
        )
        items = [
            _Item(
                item.item_uuid,
                receipt.receipt_uuid,
                receipt.transaction_date,
                receipt.merchant_normalized,
                item.description_original,
                item.description_normalized,
                category.display_name,
                category.internal_name,
                item.subcategory or "",
                item.quantity,
                item.unit_price_minor,
                item.line_total_minor,
                receipt.currency,
                item.classification_confidence,
                item.review_status,
                item.manually_corrected,
                receipt.source_type,
            )
            for item, receipt, category in rows
        ]
        categories = {
            record.internal_name: record.display_name
            for record in self.session.scalars(select(CategoryRecord))
        }
        for receipt in receipts:
            for key, amount, label, category_internal in (
                ("tax", receipt.tax_minor, categories.get("tax", "Tax"), "tax"),
                ("tips", receipt.tip_minor, categories.get("tips", "Tips"), "tips"),
                ("discount", -receipt.discount_total_minor, "Discount", "discount"),
            ):
                if amount:
                    items.append(
                        _Item(
                            f"{receipt.receipt_uuid}:{key}",
                            receipt.receipt_uuid,
                            receipt.transaction_date,
                            receipt.merchant_normalized,
                            label,
                            key,
                            label,
                            category_internal,
                            "",
                            Decimal("1"),
                            amount,
                            amount,
                            receipt.currency,
                            receipt.extraction_confidence,
                            receipt.review_status,
                            False,
                            receipt.source_type,
                        )
                    )
        return sorted(
            items, key=lambda item: (item.transaction_date, item.receipt_id, item.item_id)
        )

    @staticmethod
    def _items_table(items: Iterable[_Item]) -> SheetTable:
        headers = (
            "Item ID",
            "Receipt ID",
            "Date",
            "Year",
            "Month",
            "Merchant",
            "Item Description",
            "Normalized Item",
            "Category",
            "Subcategory",
            "Quantity",
            "Unit Price",
            "Item Total",
            "Currency",
            "Confidence",
            "Review Status",
            "Manually Corrected",
            "Source Type",
        )
        rows = tuple(
            (
                item.item_id,
                item.receipt_id,
                item.transaction_date.isoformat(),
                item.transaction_date.year,
                item.transaction_date.strftime("%Y-%m"),
                item.merchant,
                item.description,
                item.normalized,
                item.category,
                item.subcategory,
                float(item.quantity),
                None if item.unit_price_minor is None else _major(item.unit_price_minor),
                _major(item.total_minor),
                item.currency,
                item.confidence,
                item.review_status,
                item.corrected,
                item.source_type,
            )
            for item in items
        )
        return SheetTable("Items", headers, rows)

    @staticmethod
    def _receipts_table(receipts: Iterable[ReceiptRecord]) -> SheetTable:
        headers = (
            "Receipt ID",
            "Date",
            "Merchant",
            "Currency",
            "Subtotal",
            "Tax",
            "Tip",
            "Discount",
            "Final Total",
            "Calculated Total",
            "Difference",
            "Reconciliation Status",
            "Source File",
            "Date Source",
            "Review Status",
            "Imported At",
            "Confirmed At",
        )
        rows = tuple(
            (
                receipt.receipt_uuid,
                receipt.transaction_date.isoformat(),
                receipt.merchant_normalized,
                receipt.currency,
                _major(receipt.subtotal_minor),
                _major(receipt.tax_minor),
                _major(receipt.tip_minor),
                _major(receipt.discount_total_minor),
                _major(receipt.final_total_minor),
                _major(receipt.calculated_total_minor),
                _major(receipt.reconciliation_difference_minor),
                receipt.reconciliation_status,
                receipt.source_file_name or "",
                receipt.date_source or "",
                receipt.review_status,
                receipt.imported_at.isoformat(),
                "" if receipt.confirmed_at is None else receipt.confirmed_at.isoformat(),
            )
            for receipt in receipts
        )
        return SheetTable("Receipts", headers, rows)

    def _budgets_table(self) -> SheetTable:
        headers = (
            "Budget ID",
            "Year",
            "Month",
            "Currency",
            "Category",
            "Budget Amount",
            "Actual Spending",
            "Remaining",
            "Percentage Used",
            "Warning Threshold",
            "Status",
        )
        records = list(
            self.session.scalars(
                select(BudgetRecord).order_by(
                    BudgetRecord.year, BudgetRecord.month, BudgetRecord.currency, BudgetRecord.id
                )
            )
        )
        service = BudgetService(self.session)
        rows = []
        for record in records:
            summary = service._summary(record)
            category = "Overall" if record.category is None else record.category.display_name
            rows.append(
                (
                    record.id,
                    record.year,
                    record.month,
                    record.currency,
                    category,
                    _major(summary.budget_minor),
                    _major(summary.spent_minor),
                    _major(summary.remaining_minor),
                    round(summary.percentage_used, 2),
                    summary.warning_threshold,
                    summary.status.value,
                )
            )
        return SheetTable("Budgets", headers, tuple(rows))

    @staticmethod
    def _summary_table(items: list[_Item], *, annual: bool) -> SheetTable:
        grouped: dict[tuple[str, str, str], list[_Item]] = defaultdict(list)
        for item in items:
            period = (
                str(item.transaction_date.year)
                if annual
                else item.transaction_date.strftime("%Y-%m")
            )
            grouped[(period, item.currency, item.category)].append(item)
        first = "Year" if annual else "Month"
        headers = (
            first,
            "Currency",
            "Category",
            "Item Count",
            "Receipt Count",
            "Total Spending",
            "Average Item Amount",
            "Largest Item Amount",
        )
        rows = []
        for (period, currency, category), values in sorted(grouped.items()):
            totals = [item.total_minor for item in values]
            rows.append(
                (
                    period,
                    currency,
                    category,
                    len(values),
                    len({item.receipt_id for item in values}),
                    _major(sum(totals)),
                    _major(round(sum(totals) / len(totals))),
                    _major(max(totals)),
                )
            )
        name = "Annual Summary" if annual else "Monthly Summary"
        return SheetTable(name, headers, tuple(rows))

    @staticmethod
    def _category_summary(items: list[_Item]) -> SheetTable:
        grouped: dict[tuple[str, str], list[_Item]] = defaultdict(list)
        currency_totals: dict[str, int] = defaultdict(int)
        for item in items:
            grouped[(item.category, item.currency)].append(item)
            currency_totals[item.currency] += item.total_minor
        headers = (
            "Category",
            "Currency",
            "Item Count",
            "Receipt Count",
            "Total Spending",
            "Percentage of Spending Within Currency",
            "Average Item Amount",
            "Most Recent Purchase Date",
        )
        rows = []
        for (category, currency), values in sorted(grouped.items()):
            total = sum(item.total_minor for item in values)
            denominator = currency_totals[currency]
            percentage = 0.0 if denominator == 0 else total / denominator * 100
            rows.append(
                (
                    category,
                    currency,
                    len(values),
                    len({item.receipt_id for item in values}),
                    _major(total),
                    round(percentage, 2),
                    _major(round(total / len(values))),
                    max(item.transaction_date for item in values).isoformat(),
                )
            )
        return SheetTable("Category Summary", headers, tuple(rows))

    @staticmethod
    def _merchant_summary(receipts: list[ReceiptRecord], items: list[_Item]) -> SheetTable:
        receipt_groups: dict[tuple[str, str], list[ReceiptRecord]] = defaultdict(list)
        item_counts: dict[tuple[str, str], int] = defaultdict(int)
        for receipt in receipts:
            receipt_groups[(receipt.merchant_normalized, receipt.currency)].append(receipt)
        for item in items:
            item_counts[(item.merchant, item.currency)] += 1
        headers = (
            "Merchant",
            "Currency",
            "Receipt Count",
            "Item Count",
            "Total Spending",
            "Average Receipt",
            "Most Recent Purchase Date",
        )
        rows = []
        for key, values in sorted(receipt_groups.items()):
            total = sum(receipt.final_total_minor for receipt in values)
            rows.append(
                (
                    key[0],
                    key[1],
                    len(values),
                    item_counts[key],
                    _major(total),
                    _major(round(total / len(values))),
                    max(receipt.transaction_date for receipt in values).isoformat(),
                )
            )
        return SheetTable("Merchant Summary", headers, tuple(rows))

    def _review_log(self) -> SheetTable:
        rows = self.session.execute(
            select(ReviewCaseRecord, ReceiptRecord)
            .join(ReceiptRecord, ReviewCaseRecord.receipt_id == ReceiptRecord.id)
            .order_by(ReviewCaseRecord.created_at, ReviewCaseRecord.id)
        )
        return SheetTable(
            "Review Log",
            (
                "Review ID",
                "Receipt ID",
                "Date",
                "Merchant",
                "Reason",
                "Severity",
                "Status",
                "Created At",
                "Resolved At",
            ),
            tuple(
                (
                    case.id,
                    receipt.receipt_uuid,
                    receipt.transaction_date.isoformat(),
                    receipt.merchant_normalized,
                    case.reason,
                    case.severity,
                    case.status,
                    case.created_at.isoformat(),
                    "" if case.resolved_at is None else case.resolved_at.isoformat(),
                )
                for case, receipt in rows
            ),
        )

    def _dashboard(
        self,
        receipts: list[ReceiptRecord],
        items: list[_Item],
        month: str,
        currency: str,
        last_sync: str | None,
    ) -> SheetTable:
        month_receipts = [
            receipt
            for receipt in receipts
            if receipt.currency == currency and receipt.transaction_date.strftime("%Y-%m") == month
        ]
        month_items = [
            item
            for item in items
            if item.currency == currency and item.transaction_date.strftime("%Y-%m") == month
        ]
        purchased_items = [
            item
            for item in month_items
            if item.category_internal not in {"tax", "tips", "discount", "unallocated"}
        ]
        category_totals: dict[str, int] = defaultdict(int)
        for item in month_items:
            category_totals[item.category] += item.total_minor
        budget_summaries = []
        if month and len(month) == 7:
            year, month_number = (int(value) for value in month.split("-"))
            budget_summaries = BudgetService(self.session).summaries(year, month_number, currency)
        overall = next(
            (entry for entry in budget_summaries if entry.category_internal_name is None), None
        )
        total = sum(receipt.final_total_minor for receipt in month_receipts)
        largest_category = (
            max(category_totals, key=lambda category: category_totals[category])
            if category_totals
            else ""
        )
        largest_purchase = max((item.total_minor for item in purchased_items), default=0)
        review_count = sum(
            receipt.review_status in {"required", "flagged"} for receipt in month_receipts
        )
        metrics: list[tuple[str, Any]] = [
            ("Selected Month", month),
            ("Selected Currency", currency),
            ("Total Spending", _major(total)),
            ("Budget Amount", None if overall is None else _major(overall.budget_minor)),
            ("Budget Remaining", None if overall is None else _major(overall.remaining_minor)),
            (
                "Percentage of Budget Used",
                None if overall is None else round(overall.percentage_used, 2),
            ),
            (
                "Over-Budget Categories",
                sum(
                    entry.status.value == "over_budget"
                    for entry in budget_summaries
                    if entry.category_internal_name
                ),
            ),
            ("Receipt Count", len(month_receipts)),
            ("Purchased Item Count", len(purchased_items)),
            (
                "Average Receipt Value",
                _major(round(total / len(month_receipts))) if month_receipts else 0.0,
            ),
            ("Largest Category", largest_category),
            ("Largest Purchase", _major(largest_purchase)),
            (
                "Unallocated Amount",
                _major(
                    sum(
                        item.total_minor
                        for item in month_items
                        if item.category_internal == "unallocated"
                    )
                ),
            ),
            ("Receipts Needing Review", review_count),
            ("Last Successful Sync", last_sync or "Never"),
        ]
        trend: dict[str, int] = defaultdict(int)
        for receipt in receipts:
            if receipt.currency == currency:
                trend[receipt.transaction_date.strftime("%Y-%m")] += receipt.final_total_minor
        top_merchants: dict[str, int] = defaultdict(int)
        for receipt in month_receipts:
            top_merchants[receipt.merchant_normalized] += receipt.final_total_minor
        top_items: dict[str, int] = defaultdict(int)
        for item in purchased_items:
            top_items[item.normalized] += item.total_minor
        recent = sorted(month_receipts, key=lambda value: value.transaction_date, reverse=True)[:10]
        max_rows = max(
            len(metrics),
            len(category_totals),
            len(budget_summaries),
            len(trend),
            len(recent),
            len(top_merchants),
            len(top_items),
            1,
        )
        rows: list[tuple[Any, ...]] = []
        category_rows = [(key, _major(value)) for key, value in sorted(category_totals.items())]
        budget_rows = [
            (
                entry.category_internal_name or "Overall",
                _major(entry.budget_minor),
                _major(entry.spent_minor),
            )
            for entry in budget_summaries
        ]
        trend_rows = [(key, _major(value)) for key, value in sorted(trend.items())]
        merchant_rows = sorted(top_merchants.items(), key=lambda pair: pair[1], reverse=True)[:10]
        item_rows = sorted(top_items.items(), key=lambda pair: pair[1], reverse=True)[:10]
        for index in range(max_rows):
            metric = metrics[index] if index < len(metrics) else ("", "")
            category = category_rows[index] if index < len(category_rows) else ("", "")
            budget = budget_rows[index] if index < len(budget_rows) else ("", "", "")
            trend_row = trend_rows[index] if index < len(trend_rows) else ("", "")
            recent_row = (
                (
                    recent[index].transaction_date.isoformat(),
                    recent[index].merchant_normalized,
                    _major(recent[index].final_total_minor),
                )
                if index < len(recent)
                else ("", "", "")
            )
            merchant = (
                (merchant_rows[index][0], _major(merchant_rows[index][1]))
                if index < len(merchant_rows)
                else ("", "")
            )
            top_item = (
                (item_rows[index][0], _major(item_rows[index][1]))
                if index < len(item_rows)
                else ("", "")
            )
            rows.append(
                (
                    *metric,
                    "",
                    *category,
                    "",
                    *budget,
                    "",
                    *trend_row,
                    "",
                    *recent_row,
                    "",
                    *merchant,
                    "",
                    *top_item,
                )
            )
        return SheetTable(
            "Dashboard",
            (
                "Metric",
                "Value",
                "",
                "Category",
                "Spending",
                "",
                "Budget Category",
                "Budget",
                "Actual",
                "",
                "Month",
                "Spending",
                "",
                "Recent Date",
                "Recent Expense",
                "Amount",
                "",
                "Top Merchant",
                "Spending",
                "",
                "Top Item",
                "Spending",
            ),
            tuple(rows),
        )

    def _metadata(
        self, month: str, currency: str, currencies: list[str], last_sync: str | None
    ) -> SheetTable:
        return SheetTable(
            "Metadata",
            ("Key", "Value"),
            (
                ("Report Schema Version", 1),
                ("Generated At", self.now.isoformat()),
                ("Selected Month", month),
                ("Selected Currency", currency),
                ("Available Currencies", ", ".join(currencies)),
                ("Last Successful Sync", last_sync or "Never"),
                ("Authoritative Source", "Local SQLite database"),
            ),
        )
