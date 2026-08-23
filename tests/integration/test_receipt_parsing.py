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


def test_missing_total_is_inferred_from_extracted_amounts() -> None:
    parsed = ReceiptParser(default_currency="USD").parse(
        "Store\n2026-08-19\nMilk 4.00\nBread 3.00\nSubtotal 7.00\nTax 0.70"
    )
    assert parsed.final_total.value == Decimal("7.70")
    assert "final total inferred" in parsed.final_total.warnings[0]


def test_columnar_invoice_sparse_ocr_layout_is_parsed() -> None:
    parsed = ReceiptParser(default_currency="USD").parse(
        """Example Apparel Store
Sales Invoice
Invoice Date:
2026-08-06
Invoice Detail
1/5/10/20/40pcs Galvanized Pants Clips
1
8.71
pc Non-Slip Bathroom Mat
7.04
3pcs Waffle Kitchen Dish Cloths
5.70
Minimalist Retractable Carabiner Key Chain
2.00
1 Pack Checkered PEVA Shower Curtain
4.66
1pc Heavy Duty Tailor Scissors
2.18
Item(s) Subtotal
30.29
Shipping Fee:
0.00
Handling Fee:
0.00
Sales Tax:
1.90
Grand Total
32.19""",
        imported_at=datetime(2026, 8, 23),
    )
    assert parsed.merchant.value == "Example Apparel Store"
    assert str(parsed.transaction_date.value) == "2026-08-06"
    assert parsed.subtotal.value == Decimal("30.29")
    assert parsed.tax.value == Decimal("1.90")
    assert parsed.final_total.value == Decimal("32.19")
    assert [item.line_total for item in parsed.items] == [
        Decimal("8.71"),
        Decimal("7.04"),
        Decimal("5.70"),
        Decimal("2.00"),
        Decimal("4.66"),
        Decimal("2.18"),
    ]
    assert parsed.reconciliation.status == "balanced"


def test_product_slash_sequence_is_not_read_as_a_date() -> None:
    parsed = ReceiptParser(default_currency="USD").parse(
        "Store\n2026-08-06\n1/5/10/20/40pcs storage clips\n8.71\nGrand Total\n8.71"
    )
    assert str(parsed.transaction_date.value) == "2026-08-06"
