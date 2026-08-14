from datetime import date

import pytest
from sqlalchemy import Engine

from spendscope.config import ConfidenceThresholds
from spendscope.database.connection import session_scope
from spendscope.database.repositories import CategoryRepository, ReceiptRepository
from spendscope.domain.enums import ConfidenceLevel, ReconciliationStatus, ReviewStatus
from spendscope.domain.models import ReceiptDraft
from spendscope.processing.confidence import ConfidencePolicy
from spendscope.processing.duplicate_detector import (
    build_receipt_fingerprint,
    check_likely_receipt_duplicate,
)
from spendscope.processing.reconciliation import reconcile_amounts


@pytest.mark.parametrize(
    ("printed", "tolerance", "status"),
    [
        (1175, 2, ReconciliationStatus.BALANCED),
        (1176, 2, ReconciliationStatus.BALANCED_WITH_ROUNDING),
        (1200, 2, ReconciliationStatus.NEEDS_REVIEW),
    ],
)
def test_reconciliation_statuses(
    printed: int, tolerance: int, status: ReconciliationStatus
) -> None:
    outcome = reconcile_amounts(
        item_totals_minor=(600, 400),
        subtotal_minor=1000,
        tax_minor=100,
        tip_minor=100,
        discount_minor=25,
        printed_total_minor=printed,
        tolerance_minor=tolerance,
    )
    assert outcome.calculated_total_minor == 1175
    assert outcome.status is status


def test_missing_or_incomplete_amounts_do_not_silently_balance() -> None:
    unresolved = reconcile_amounts(
        item_totals_minor=(), subtotal_minor=100, printed_total_minor=None
    )
    incomplete = reconcile_amounts(
        item_totals_minor=(500,), subtotal_minor=1000, printed_total_minor=1000
    )

    assert unresolved.status is ReconciliationStatus.UNRESOLVED
    assert incomplete.status is ReconciliationStatus.INCOMPLETE_ITEMS
    assert incomplete.unallocated_minor == 0


def test_unallocated_difference_requires_explicit_confirmation() -> None:
    review = reconcile_amounts(
        item_totals_minor=(900,), subtotal_minor=900, printed_total_minor=1000
    )
    confirmed = reconcile_amounts(
        item_totals_minor=(900,),
        subtotal_minor=900,
        printed_total_minor=1000,
        confirm_unallocated=True,
    )

    assert review.status is ReconciliationStatus.NEEDS_REVIEW
    assert review.unallocated_minor == 0
    assert confirmed.status is ReconciliationStatus.BALANCED
    assert confirmed.unallocated_minor == 100
    assert confirmed.calculated_total_minor == 1000


def test_confirmation_cannot_hide_an_incomplete_subtotal_without_a_difference() -> None:
    outcome = reconcile_amounts(
        item_totals_minor=(500,),
        subtotal_minor=1000,
        printed_total_minor=500,
        confirm_unallocated=True,
    )

    assert outcome.status is ReconciliationStatus.INCOMPLETE_ITEMS
    assert outcome.unallocated_minor == 0


def test_confidence_policy_routes_high_medium_and_low_records() -> None:
    policy = ConfidencePolicy(ConfidenceThresholds(high=0.85, medium=0.60))
    high = policy.decide(
        extraction_confidence=0.95,
        categorization_confidence=0.90,
        reconciliation_status=ReconciliationStatus.BALANCED,
    )
    medium = policy.decide(
        extraction_confidence=0.80,
        categorization_confidence=0.75,
        reconciliation_status=ReconciliationStatus.INCOMPLETE_ITEMS,
    )
    low = policy.decide(
        extraction_confidence=0.99,
        categorization_confidence=0.99,
        reconciliation_status=ReconciliationStatus.NEEDS_REVIEW,
    )

    assert high.level is ConfidenceLevel.HIGH and high.archive_ready and high.reporting_ready
    assert medium.level is ConfidenceLevel.MEDIUM and medium.reporting_ready
    assert medium.review_status is ReviewStatus.FLAGGED
    assert low.level is ConfidenceLevel.LOW and not low.reporting_ready
    assert low.review_status is ReviewStatus.REQUIRED


def test_receipt_fingerprint_is_normalized_and_currency_sensitive() -> None:
    day = date(2026, 8, 6)
    first = build_receipt_fingerprint("Shop Inc. Store #1", day, 1200, "usd")
    second = build_receipt_fingerprint("SHOP", day, 1200, "USD")
    other_currency = build_receipt_fingerprint("SHOP", day, 1200, "CAD")

    assert first == second
    assert first != other_currency
    assert len(first) == 64


def test_likely_duplicate_uses_fingerprint_then_receipt_number(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        CategoryRepository(session).seed_defaults()
        repository = ReceiptRepository(session)
        record = repository.create(
            ReceiptDraft(
                merchant_original="Local Shop",
                merchant_normalized="local shop",
                transaction_date=date(2026, 8, 6),
                currency="USD",
                subtotal_minor=1200,
                final_total_minor=1200,
            )
        )
        record.transaction_fingerprint = build_receipt_fingerprint(
            "Local Shop", date(2026, 8, 6), 1200, "USD"
        )
        record.receipt_number = "R-10"
        session.flush()

        fingerprint_match = check_likely_receipt_duplicate(
            session,
            merchant="LOCAL SHOP LLC",
            transaction_date=date(2026, 8, 6),
            final_total_minor=1200,
            currency="usd",
        )
        number_match = check_likely_receipt_duplicate(
            session,
            merchant="Local Shop",
            transaction_date=date(2026, 8, 7),
            final_total_minor=1300,
            currency="USD",
            receipt_number="R-10",
        )
        screenshot_match = check_likely_receipt_duplicate(
            session,
            merchant="Paid Items Preparing",
            transaction_date=date(2026, 8, 7),
            final_total_minor=1200,
            currency="USD",
            receipt_number="R-10",
        )

        assert fingerprint_match.likely_duplicate
        assert fingerprint_match.reason == "matching receipt fingerprint"
        assert number_match.likely_duplicate
        assert number_match.reason == "matching merchant and receipt number"
        assert screenshot_match.likely_duplicate
        assert screenshot_match.reason == "matching order number, amount, and currency"
