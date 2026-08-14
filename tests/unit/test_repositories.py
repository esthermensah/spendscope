from datetime import date

import pytest
from sqlalchemy import Engine

from spendscope.database.connection import session_scope
from spendscope.database.repositories import (
    CategoryRepository,
    ReceiptRepository,
    SettingsRepository,
)
from spendscope.domain.models import LineItemDraft, ReceiptDraft


def test_default_categories_are_seeded_idempotently(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        repository = CategoryRepository(session)
        first = repository.seed_defaults()
        second = repository.seed_defaults()

        assert len(first) == 18
        assert len(second) == 18
        assert repository.get_by_internal_name("tax").system_category is True  # type: ignore[union-attr]
        assert [category.display_name for category in repository.list_active()] == sorted(
            category.display_name for category in first
        )


def test_settings_round_trip_json_values(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        repository = SettingsRepository(session)
        repository.set_many((("currency", "USD"), ("options", {"offline": True})))
        assert repository.get("currency") == "USD"
        assert repository.get("options") == {"offline": True}
        assert repository.get("missing", 42) == 42


def test_receipt_and_item_are_persisted(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        CategoryRepository(session).seed_defaults()
        receipt_repository = ReceiptRepository(session)
        draft = ReceiptDraft(
            merchant_original="Local Market",
            merchant_normalized="local market",
            transaction_date=date(2026, 8, 6),
            currency="USD",
            subtotal_minor=1200,
            tax_minor=60,
            final_total_minor=1260,
            items=[
                LineItemDraft(
                    description_original="Rice",
                    description_normalized="rice",
                    line_total_minor=1200,
                    category_internal_name="groceries",
                    classification_confidence=0.92,
                )
            ],
        )
        record = receipt_repository.create(draft)
        receipt_uuid = record.receipt_uuid

    with session_scope(database_engine) as session:
        repository = ReceiptRepository(session)
        persisted = repository.get_by_uuid(receipt_uuid)
        assert persisted is not None
        assert persisted.currency == "USD"
        assert persisted.processing_status == "needs_review"
        assert persisted.line_items[0].description_normalized == "rice"
        assert repository.list_by_currency("usd") == [persisted]


def test_receipt_rejects_unknown_category(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        draft = ReceiptDraft(
            merchant_original="Store",
            merchant_normalized="store",
            transaction_date=date.today(),
            currency="USD",
            subtotal_minor=100,
            final_total_minor=100,
            items=[
                LineItemDraft(
                    description_original="Item",
                    description_normalized="item",
                    line_total_minor=100,
                    category_internal_name="missing",
                )
            ],
        )
        with pytest.raises(ValueError, match="unknown categories"):
            ReceiptRepository(session).create(draft)


def test_session_scope_rolls_back_on_error(database_engine: Engine) -> None:
    with pytest.raises(RuntimeError), session_scope(database_engine) as session:
        SettingsRepository(session).set("temporary", True)
        raise RuntimeError("stop")
    with session_scope(database_engine) as session:
        assert SettingsRepository(session).get("temporary") is None
