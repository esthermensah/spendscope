from decimal import Decimal

from spendscope.parsing.line_item_parser import (
    parse_amazon_tabular_items,
    parse_amazon_tabular_summary,
    parse_line_items,
)
from spendscope.parsing.validators import reconcile_receipt


def test_line_item_parser_extracts_simple_and_quantity_lines() -> None:
    items = parse_line_items(
        [
            "Rice 12.00",
            "Chicken 2 x 7.50 15.00",
            "Subtotal 27.00",
            "TOTAL 28.00",
        ]
    )
    assert [item.description for item in items] == ["Rice", "Chicken"]
    assert items[1].quantity == Decimal("2")
    assert items[1].unit_price == Decimal("7.50")
    assert items[1].line_total == Decimal("15.00")


def test_line_item_parser_ignores_mobile_order_status_and_address_numbers() -> None:
    items = parse_line_items(
        [
            "Delivery Aug 10-18",
            "125 Example Avenue Apt 4",
            "Sample City EXAMPLE 00000",
            "Jamie Rivera 5550100",
            "Products (11 items)",
            "Order Number ORDER-ABC-100",
            "Total $64.20 >",
        ]
    )

    assert items == ()


def test_amazon_tabular_parser_extracts_rows_and_total_column() -> None:
    items = parse_amazon_tabular_items(
        [
            "Currency Product Name Shipment Item Total Amount Website",
            "Clorox Corner Toilet Bowl Brush, White",
            "USD 1 Visa - 4116 White 38.43 2.49 Shipped 9.57 0 8.99 0.58 Amazon.com",
            (
                "USD 1 Discover - 6794 Gain Laundry Detergent 38.43 2.49 Shipped "
                "26.59 0 24.97 1.62 Amazon.com"
            ),
        ]
    )
    assert [item.line_total for item in items] == [Decimal("9.57"), Decimal("26.59")]
    assert items[0].description.endswith("White")


def test_amazon_columnar_parser_keeps_wrapped_product_names_aligned() -> None:
    summary = parse_amazon_tabular_summary(
        [
            "USD",
            "Product Name",
            "PAPAISON Roller Skates for Women and Girls, Deluxe 2 Layer-",
            "Classic Roller Skates for Men, Professional Outdoor",
            "38.43",
            "Shipment Item Subtotal Tax Status",
            "2.00 Shipped",
            "Total Amount",
            "64.95",
            "41.51",
            "Total Discounts Unit Price",
            "60.99",
            "38.98",
            "Unit Price Tax Website",
            "3.96 Amazon.com",
            "2.53 Amazon.com",
        ]
    )
    assert summary.items[0].description == (
        "PAPAISON Roller Skates for Women and Girls, Deluxe 2 Layer- "
        "Classic Roller Skates for Men, Professional Outdoor"
    )
    assert len(summary.items) == 2
    assert summary.total == Decimal("106.46")


def test_reconciliation_balanced_rounding_review_and_missing() -> None:
    items = parse_line_items(["Rice 12.00", "Chicken 15.00"])
    balanced = reconcile_receipt(
        items=items,
        subtotal=Decimal("27"),
        tax=Decimal("1"),
        tip=None,
        discount=None,
        final_total=Decimal("28"),
    )
    assert balanced.status == "balanced"
    rounding = reconcile_receipt(
        items=items,
        subtotal=Decimal("27"),
        tax=Decimal("1"),
        tip=None,
        discount=None,
        final_total=Decimal("28.01"),
    )
    assert rounding.status == "balanced_with_rounding"
    review = reconcile_receipt(
        items=items,
        subtotal=Decimal("27"),
        tax=None,
        tip=None,
        discount=None,
        final_total=Decimal("30"),
    )
    assert review.status == "needs_review"
    assert (
        reconcile_receipt(
            items=(), subtotal=None, tax=None, tip=None, discount=None, final_total=Decimal("5")
        ).status
        == "incomplete_items"
    )
    assert (
        reconcile_receipt(
            items=items, subtotal=None, tax=None, tip=None, discount=None, final_total=None
        ).status
        == "unresolved"
    )
