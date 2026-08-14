from decimal import Decimal

from spendscope.parsing.line_item_parser import parse_line_items
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
