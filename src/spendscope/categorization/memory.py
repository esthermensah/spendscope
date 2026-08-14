"""Persistent user-confirmed correction rules."""

from __future__ import annotations

from sqlalchemy.orm import Session

from spendscope.categorization.engine import RuleBasedCategorizer
from spendscope.categorization.normalization import normalize_item, normalize_merchant
from spendscope.database.repositories import ItemRuleRepository, MerchantRuleRepository


class CorrectionMemory:
    def __init__(self, session: Session) -> None:
        self.items = ItemRuleRepository(session)
        self.merchants = MerchantRuleRepository(session)

    def remember_item(self, original: str, corrected: str, category_internal_name: str) -> None:
        self.items.upsert(
            item_pattern=normalize_item(original),
            normalized_item=normalize_item(corrected),
            category_internal_name=category_internal_name,
        )

    def forget_item(self, original: str) -> bool:
        return self.items.delete(normalize_item(original))

    def remember_merchant(
        self,
        original: str,
        corrected: str,
        preferred_category_internal_name: str | None = None,
    ) -> None:
        self.merchants.upsert(
            merchant_pattern=normalize_merchant(original),
            normalized_merchant=normalize_merchant(corrected),
            preferred_category_internal_name=preferred_category_internal_name,
        )

    def forget_merchant(self, original: str) -> bool:
        return self.merchants.delete(normalize_merchant(original))

    def normalize_merchant_name(self, original: str) -> str:
        normalized = normalize_merchant(original)
        return self.merchants.resolve_normalized(normalized) or normalized

    def categorizer(self) -> RuleBasedCategorizer:
        return RuleBasedCategorizer(
            item_rules=self.items.list_for_categorizer(),
            merchant_category_rules=self.merchants.list_category_fallbacks(),
        )
