"""Receipt arithmetic validation."""

from __future__ import annotations

from decimal import Decimal

from spendscope.parsing.models import ParsedLineItem, ReconciliationResult


def reconcile_receipt(
    *,
    items: tuple[ParsedLineItem, ...],
    subtotal: Decimal | None,
    tax: Decimal | None,
    tip: Decimal | None,
    discount: Decimal | None,
    final_total: Decimal | None,
    tolerance: Decimal = Decimal("0.02"),
) -> ReconciliationResult:
    if final_total is None:
        return ReconciliationResult(None, None, "unresolved", ("final total is missing",))
    if subtotal is None:
        if not items:
            return ReconciliationResult(
                None, None, "incomplete_items", ("subtotal and line items are missing",)
            )
        subtotal = sum((item.line_total for item in items), Decimal("0"))
    calculated = (
        subtotal + (tax or Decimal("0")) + (tip or Decimal("0")) - abs(discount or Decimal("0"))
    )
    difference = final_total - calculated
    if difference == 0:
        return ReconciliationResult(calculated, difference, "balanced")
    if abs(difference) <= tolerance:
        return ReconciliationResult(
            calculated,
            difference,
            "balanced_with_rounding",
            ("total differs only within the configured rounding tolerance",),
        )
    return ReconciliationResult(
        calculated,
        difference,
        "needs_review",
        ("printed and calculated totals do not reconcile",),
    )
