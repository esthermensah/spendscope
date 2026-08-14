"""Orchestration of focused receipt-field parsers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from spendscope.parsing.amount_parser import parse_labeled_amount
from spendscope.parsing.currency_parser import parse_currency
from spendscope.parsing.date_parser import parse_date
from spendscope.parsing.line_item_parser import parse_line_items
from spendscope.parsing.merchant_parser import parse_merchant, parse_receipt_number
from spendscope.parsing.models import ParsedReceipt
from spendscope.parsing.validators import reconcile_receipt


class ReceiptParser:
    def __init__(
        self,
        *,
        default_currency: str = "USD",
        date_locale: str = "en_US",
        reconciliation_tolerance_minor: int = 2,
    ) -> None:
        self.default_currency = default_currency
        self.date_locale = date_locale
        self.tolerance = Decimal(reconciliation_tolerance_minor) / 100

    def parse(
        self,
        text: str,
        *,
        file_modified: datetime | None = None,
        imported_at: datetime | None = None,
    ) -> ParsedReceipt:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        merchant = parse_merchant(lines)
        transaction_date, date_source = parse_date(
            text,
            date_locale=self.date_locale,
            file_modified=file_modified,
            imported_at=imported_at,
        )
        receipt_number = parse_receipt_number(text)
        currency = parse_currency(text, default_currency=self.default_currency)
        items = parse_line_items(lines)
        subtotal = parse_labeled_amount(lines, (r"\bsub\s*total\b",))
        tax = parse_labeled_amount(
            lines,
            (
                r"\btax\b",
                r"\bvat\b",
            ),
        )
        tip = parse_labeled_amount(
            lines,
            (
                r"\btip\b",
                r"\bgratuity\b",
            ),
        )
        discount = parse_labeled_amount(lines, (r"\bdiscount\b", r"\bcoupon\b", r"\bsavings\b"))
        final_total = parse_labeled_amount(
            lines,
            (r"(?<!sub)\btotal\b", r"\bamount\s+due\b", r"\bgrand\s+total\b"),
        )
        amount_paid = parse_labeled_amount(
            lines, (r"\bamount\s+paid\b", r"\bcash\s+tendered\b", r"\btendered\b")
        )
        change = parse_labeled_amount(lines, (r"\bchange\b", r"\bchange\s+due\b"))
        reconciliation = reconcile_receipt(
            items=items,
            subtotal=subtotal.value,
            tax=tax.value,
            tip=tip.value,
            discount=discount.value,
            final_total=final_total.value,
            tolerance=self.tolerance,
        )
        values = [
            merchant.confidence,
            transaction_date.confidence,
            currency.confidence,
            subtotal.confidence,
            final_total.confidence,
            (reconciliation.status in {"balanced", "balanced_with_rounding"} and 1.0) or 0.2,
        ]
        warnings = (
            tuple(
                dict.fromkeys(
                    warning
                    for parsed in (
                        merchant,
                        transaction_date,
                        receipt_number,
                        currency,
                        subtotal,
                        tax,
                        tip,
                        discount,
                        final_total,
                        amount_paid,
                        change,
                    )
                    for warning in parsed.warnings
                )
            )
            + reconciliation.warnings
        )
        errors = tuple(
            error
            for condition, error in (
                (merchant.value is None, "merchant is required"),
                (transaction_date.value is None, "transaction date is required"),
                (final_total.value is None, "final total is required"),
            )
            if condition
        )
        confidence = max(0.0, min(1.0, sum(float(value) for value in values) / len(values)))
        return ParsedReceipt(
            merchant=merchant,
            transaction_date=transaction_date,
            date_source=date_source,
            receipt_number=receipt_number,
            currency=currency,
            items=items,
            subtotal=subtotal,
            tax=tax,
            tip=tip,
            discount=discount,
            final_total=final_total,
            amount_paid=amount_paid,
            change=change,
            reconciliation=reconciliation,
            confidence=confidence,
            warnings=warnings,
            errors=errors,
        )
