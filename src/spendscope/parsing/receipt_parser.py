"""Orchestration of focused receipt-field parsers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from spendscope.parsing.amount_parser import parse_labeled_amount
from spendscope.parsing.currency_parser import parse_currency
from spendscope.parsing.date_parser import parse_date
from spendscope.parsing.line_item_parser import (
    parse_amazon_tabular_summary,
    parse_columnar_invoice_items,
    parse_line_items,
)
from spendscope.parsing.merchant_parser import parse_merchant, parse_receipt_number
from spendscope.parsing.models import ParsedReceipt, ParsedValue
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
        amazon_summary = parse_amazon_tabular_summary(lines)
        amazon_items = amazon_summary.items
        columnar_invoice_items = parse_columnar_invoice_items(lines)
        merchant = (
            ParsedValue("Amazon", 0.92, ("Amazon",))
            if amazon_items
            else parse_merchant(lines)
        )
        transaction_date, date_source = parse_date(
            text,
            date_locale=self.date_locale,
            file_modified=file_modified,
            imported_at=imported_at,
        )
        receipt_number = parse_receipt_number(text)
        currency = parse_currency(text, default_currency=self.default_currency)
        items = amazon_items or columnar_invoice_items or parse_line_items(lines)
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
        if amazon_items:
            amazon_inferred_total = amazon_summary.total
            final_total = ParsedValue(
                amazon_inferred_total,
                0.85,
                (amazon_inferred_total,),
                ("total aggregated from Amazon total-amount columns",),
            )
            subtotal = ParsedValue(
                amazon_summary.subtotal,
                0.85,
                (amazon_summary.subtotal,),
                ("subtotal aggregated from Amazon unit-price columns",),
            )
            tax = ParsedValue(
                amazon_summary.tax,
                0.85,
                (amazon_summary.tax,),
                ("tax aggregated from Amazon unit-tax columns",),
            )
            discount = ParsedValue(
                amazon_summary.discount,
                0.85,
                (amazon_summary.discount,),
                ("discount aggregated from Amazon discount columns",),
            )
        elif amazon_items and subtotal.value is None:
            inferred_subtotal = sum((item.line_total for item in amazon_items), Decimal("0"))
            subtotal = ParsedValue(
                inferred_subtotal,
                0.72,
                (inferred_subtotal,),
                ("subtotal inferred by summing Amazon line-item totals",),
            )
        # Some exports and screenshots omit the printed total label. Keep the
        # receipt usable by sending it to review with a transparent estimate
        # rather than rejecting the file outright.
        if final_total.value is None:
            inferred_total: Decimal | None = None
            inference_warning = "final total inferred from extracted receipt amounts"
            if subtotal.value is not None:
                inferred_total = subtotal.value + (tax.value or Decimal("0"))
                inferred_total += tip.value or Decimal("0")
                inferred_total -= discount.value or Decimal("0")
            elif items:
                inferred_total = sum((item.line_total for item in items), Decimal("0"))
                inference_warning = "final total inferred by summing extracted line items"
            if inferred_total is not None and inferred_total > 0:
                final_total = ParsedValue(
                    inferred_total,
                    0.45,
                    (inferred_total,),
                    (inference_warning,),
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
