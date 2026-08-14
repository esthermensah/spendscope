from datetime import datetime
from decimal import Decimal

from spendscope.parsing.receipt_parser import ReceiptParser

MIXED_RECEIPT = """THE CORNER MARKET
Receipt # AB-123
Date: 2026-08-05
Currency: USD
Rice 12.00
Chicken 2 x 7.50 15.00
Shampoo 8.00
Laundry detergent 10.00
Notebook 5.00
Subtotal 50.00
Discount 2.00
Tax 3.00
Tip 1.00
TOTAL USD 52.00
Amount paid 60.00
Change 8.00
"""


def test_complete_receipt_is_parsed_and_reconciled() -> None:
    parsed = ReceiptParser(default_currency="USD").parse(
        MIXED_RECEIPT, imported_at=datetime(2026, 8, 6)
    )
    assert parsed.merchant.value == "THE CORNER MARKET"
    assert str(parsed.transaction_date.value) == "2026-08-05"
    assert parsed.receipt_number.value == "AB-123"
    assert parsed.currency.value == "USD"
    assert len(parsed.items) == 5
    assert parsed.subtotal.value == Decimal("50.00")
    assert parsed.discount.value == Decimal("2.00")
    assert parsed.tax.value == Decimal("3.00")
    assert parsed.tip.value == Decimal("1.00")
    assert parsed.final_total.value == Decimal("52.00")
    assert parsed.amount_paid.value == Decimal("60.00")
    assert parsed.change.value == Decimal("8.00")
    assert parsed.reconciliation.status == "balanced"
    assert parsed.errors == ()
    assert parsed.confidence > 0.8


def test_incomplete_receipt_returns_visible_errors_and_warnings() -> None:
    parsed = ReceiptParser(default_currency="GHS").parse(
        "Receipt\nDate unreadable", imported_at=datetime(2026, 8, 6)
    )
    assert "merchant is required" in parsed.errors
    assert "final total is required" in parsed.errors
    assert parsed.reconciliation.status == "unresolved"
    assert parsed.warnings
