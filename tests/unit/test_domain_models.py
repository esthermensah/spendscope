from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from spendscope.domain.enums import LineItemKind
from spendscope.domain.models import BudgetDraft, LineItemDraft, Money, ReceiptDraft


def test_money_rounds_to_minor_units_without_float() -> None:
    money = Money.from_decimal(Decimal("12.345"), "usd")

    assert money.minor_units == 1234
    assert money.currency == "USD"
    assert money.as_decimal() == Decimal("12.34")


def test_refund_money_remains_negative() -> None:
    money = Money.from_decimal(Decimal("-8.50"), "EUR")
    assert money.minor_units == -850


def test_receipt_reconciles_line_items_and_totals() -> None:
    items = [
        LineItemDraft(
            description_original="Rice",
            description_normalized="rice",
            line_total_minor=1200,
            category_internal_name="groceries",
        ),
        LineItemDraft(
            description_original="Notebook",
            description_normalized="notebook",
            line_total_minor=500,
            category_internal_name="education",
        ),
    ]

    receipt = ReceiptDraft(
        merchant_original="Store",
        merchant_normalized="store",
        transaction_date=date(2026, 1, 2),
        currency="usd",
        subtotal_minor=1700,
        tax_minor=100,
        discount_minor=50,
        final_total_minor=1750,
        items=items,
    )

    assert receipt.currency == "USD"
    assert receipt.final_total_minor == 1750


def test_receipt_rejects_total_mismatch() -> None:
    with pytest.raises(ValidationError, match="totals do not reconcile"):
        ReceiptDraft(
            merchant_original="Store",
            merchant_normalized="store",
            transaction_date=date.today(),
            currency="USD",
            subtotal_minor=100,
            final_total_minor=99,
        )


def test_receipt_rejects_item_subtotal_mismatch() -> None:
    item = LineItemDraft(
        description_original="Return",
        description_normalized="return",
        line_total_minor=-500,
        category_internal_name="shopping",
        kind=LineItemKind.REFUND,
    )
    with pytest.raises(ValidationError, match="line items"):
        ReceiptDraft(
            merchant_original="Store",
            merchant_normalized="store",
            transaction_date=date.today(),
            currency="USD",
            subtotal_minor=-400,
            final_total_minor=-400,
            items=[item],
        )


def test_budget_validates_month_and_threshold() -> None:
    budget = BudgetDraft(year=2026, month=8, currency="cad", amount_minor=50000)
    assert budget.currency == "CAD"
    with pytest.raises(ValidationError):
        BudgetDraft(year=2026, month=13, currency="CAD", amount_minor=50000)
