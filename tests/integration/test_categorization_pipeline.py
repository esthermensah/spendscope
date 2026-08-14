from decimal import Decimal

from sqlalchemy import Engine

from spendscope.categorization.memory import CorrectionMemory
from spendscope.categorization.models import ReceiptContext
from spendscope.database.connection import session_scope
from spendscope.database.repositories import CategoryRepository
from spendscope.domain.enums import ConfidenceLevel, ReconciliationStatus
from spendscope.parsing.models import ParsedLineItem
from spendscope.processing.confidence import ConfidencePolicy
from spendscope.processing.reconciliation import reconcile_amounts


def test_corrections_categorize_reconcile_and_confirm_mixed_receipt(
    database_engine: Engine,
) -> None:
    items = (
        ParsedLineItem(
            "LQ DTRG", Decimal("1"), Decimal("10"), Decimal("10"), 0.95, "LQ DTRG 10.00"
        ),
        ParsedLineItem(
            "RST CHKN", Decimal("1"), Decimal("15"), Decimal("15"), 0.95, "RST CHKN 15.00"
        ),
    )
    with session_scope(database_engine) as session:
        CategoryRepository(session).seed_defaults()
        memory = CorrectionMemory(session)
        memory.remember_item("LQ DTRG", "Laundry Detergent", "household")
        memory.remember_item("RST CHKN", "Roast Chicken", "groceries")
        categorized = memory.categorizer().categorize_receipt(
            items, ReceiptContext("Walmart", "walmart")
        )

    reconciliation = reconcile_amounts(
        item_totals_minor=(1000, 1500),
        subtotal_minor=2500,
        tax_minor=200,
        tip_minor=100,
        discount_minor=50,
        printed_total_minor=2750,
    )
    decision = ConfidencePolicy().decide(
        extraction_confidence=0.95,
        categorization_confidence=categorized.confidence,
        reconciliation_status=reconciliation.status,
    )

    assert {
        allocation.category_internal_name: allocation.amount
        for allocation in categorized.allocations
    } == {
        "groceries": Decimal("15"),
        "household": Decimal("10"),
    }
    assert reconciliation.status is ReconciliationStatus.BALANCED
    assert reconciliation.calculated_total_minor == 2750
    assert decision.level is ConfidenceLevel.HIGH
    assert decision.archive_ready and decision.reporting_ready
