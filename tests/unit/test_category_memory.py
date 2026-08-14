from decimal import Decimal

import pytest
from sqlalchemy import Engine

from spendscope.categorization.memory import CorrectionMemory
from spendscope.categorization.models import ReceiptContext
from spendscope.database.connection import session_scope
from spendscope.database.repositories import CategoryRepository
from spendscope.domain.models import CategoryDraft
from spendscope.parsing.models import ParsedLineItem


def item(description: str) -> ParsedLineItem:
    return ParsedLineItem(
        description=description,
        quantity=Decimal("1"),
        unit_price=Decimal("1"),
        line_total=Decimal("1"),
        confidence=0.9,
        source_line=description,
    )


def test_categories_can_be_managed_and_defaults_restored(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        repository = CategoryRepository(session)
        repository.seed_defaults()
        custom = repository.create(CategoryDraft(internal_name="pets", display_name="Pets"))
        repository.rename(custom, "Pet Care")
        repository.set_active(custom, active=False)
        groceries = repository.get_by_internal_name("groceries")
        assert groceries is not None
        repository.rename(groceries, "Food at Home")
        repository.set_active(groceries, active=False)
        restored = repository.restore_defaults()

        assert custom.display_name == "Pet Care" and not custom.active
        assert groceries.display_name == "Groceries" and groceries.active
        assert len(restored) == 18


def test_tax_tips_and_unallocated_are_protected_system_categories(
    database_engine: Engine,
) -> None:
    with session_scope(database_engine) as session:
        repository = CategoryRepository(session)
        repository.seed_defaults()
        tax = repository.get_by_internal_name("tax")
        tips = repository.get_by_internal_name("tips")
        unallocated = repository.get_by_internal_name("unallocated")
        assert tax is not None and tips is not None and unallocated is not None

        with pytest.raises(ValueError, match="fixed"):
            repository.rename(tax, "Fees")
        with pytest.raises(ValueError, match="system categories"):
            repository.set_active(tips, active=False)
        with pytest.raises(ValueError, match="system categories"):
            repository.set_active(unallocated, active=False)


def test_correction_memory_round_trips_item_and_merchant_rules(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        CategoryRepository(session).seed_defaults()
        memory = CorrectionMemory(session)
        memory.remember_item("LQ DTRG", "Laundry Detergent", "household")
        memory.remember_merchant("WMRT #44", "Walmart", "shopping")

        categorizer = memory.categorizer()
        context = ReceiptContext("WMRT #44", memory.normalize_merchant_name("WMRT #44"))
        corrected = categorizer.categorize_item(item("LQ DTRG"), context)
        merchant_fallback = categorizer.categorize_item(item("ZXQ 9000"), context)

        assert context.merchant_normalized == "walmart"
        assert corrected.normalized_description == "laundry detergent"
        assert corrected.category_internal_name == "household"
        assert merchant_fallback.category_internal_name == "shopping"
        assert memory.forget_item("LQ DTRG")
        assert not memory.forget_item("LQ DTRG")
        assert memory.forget_merchant("WMRT #44")


def test_correction_memory_rejects_inactive_category(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        repository = CategoryRepository(session)
        repository.seed_defaults()
        groceries = repository.get_by_internal_name("groceries")
        assert groceries is not None
        repository.set_active(groceries, active=False)

        with pytest.raises(ValueError, match="unknown or inactive"):
            CorrectionMemory(session).remember_item("Rice", "Rice", "groceries")
