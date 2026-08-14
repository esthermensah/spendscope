"""Receipt reconciliation in integer minor currency units."""

from __future__ import annotations

from dataclasses import dataclass, field

from spendscope.domain.enums import ReconciliationStatus


@dataclass(frozen=True, slots=True)
class ReconciliationOutcome:
    item_total_minor: int
    calculated_total_minor: int | None
    difference_minor: int | None
    status: ReconciliationStatus
    unallocated_minor: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)


def reconcile_amounts(
    *,
    item_totals_minor: tuple[int, ...],
    subtotal_minor: int | None,
    tax_minor: int = 0,
    tip_minor: int = 0,
    discount_minor: int = 0,
    printed_total_minor: int | None,
    tolerance_minor: int = 2,
    confirm_unallocated: bool = False,
) -> ReconciliationOutcome:
    if tolerance_minor < 0:
        raise ValueError("reconciliation tolerance cannot be negative")
    item_total = sum(item_totals_minor)
    if printed_total_minor is None:
        return ReconciliationOutcome(
            item_total,
            None,
            None,
            ReconciliationStatus.UNRESOLVED,
            warnings=("printed final total is missing",),
        )
    if not item_totals_minor and subtotal_minor is None:
        return ReconciliationOutcome(
            item_total,
            None,
            None,
            ReconciliationStatus.INCOMPLETE_ITEMS,
            warnings=("line items and subtotal are missing",),
        )

    base_minor = item_total if item_totals_minor else subtotal_minor or 0
    items_incomplete = (
        bool(item_totals_minor)
        and subtotal_minor is not None
        and abs(subtotal_minor - item_total) > tolerance_minor
    )
    calculated = base_minor + tax_minor + tip_minor - abs(discount_minor)
    difference = printed_total_minor - calculated
    if difference == 0 and not items_incomplete:
        return ReconciliationOutcome(
            item_total, calculated, difference, ReconciliationStatus.BALANCED
        )
    if abs(difference) <= tolerance_minor and not items_incomplete:
        return ReconciliationOutcome(
            item_total,
            calculated,
            difference,
            ReconciliationStatus.BALANCED_WITH_ROUNDING,
            warnings=("difference is within the configured rounding tolerance",),
        )
    if items_incomplete and (not confirm_unallocated or difference == 0):
        return ReconciliationOutcome(
            item_total,
            calculated,
            difference,
            ReconciliationStatus.INCOMPLETE_ITEMS,
            warnings=("line items do not match the printed subtotal",),
        )
    if confirm_unallocated:
        return ReconciliationOutcome(
            item_total,
            printed_total_minor,
            0,
            ReconciliationStatus.BALANCED,
            unallocated_minor=difference,
            warnings=("user confirmed the unexplained difference as Unallocated",),
        )
    return ReconciliationOutcome(
        item_total,
        calculated,
        difference,
        ReconciliationStatus.NEEDS_REVIEW,
        warnings=("printed and calculated totals do not reconcile",),
    )
