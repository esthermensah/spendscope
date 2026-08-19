"""Deterministic, explainable item categorization."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal

from spendscope.categorization.models import (
    CategorizationResult,
    CategorizedLineItem,
    CategorizedReceipt,
    CategoryAllocation,
    ReceiptContext,
)
from spendscope.categorization.normalization import normalize_item, normalize_merchant
from spendscope.categorization.rules import DEFAULT_ITEM_KEYWORDS
from spendscope.parsing.models import ParsedLineItem


class RuleBasedCategorizer:
    """Categorize items locally with correction, keyword, then merchant fallback rules."""

    def __init__(
        self,
        *,
        item_rules: Mapping[str, tuple[str, str]] | None = None,
        merchant_category_rules: Mapping[str, str] | None = None,
        keyword_rules: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        self.item_rules = {
            normalize_item(pattern): (normalize_item(value[0]), value[1])
            for pattern, value in (item_rules or {}).items()
        }
        self.merchant_category_rules = {
            normalize_merchant(pattern): category
            for pattern, category in (merchant_category_rules or {}).items()
        }
        self.keyword_rules = dict(keyword_rules or DEFAULT_ITEM_KEYWORDS)

    def categorize_item(
        self, item: ParsedLineItem, context: ReceiptContext
    ) -> CategorizationResult:
        normalized = normalize_item(item.description)
        correction = self.item_rules.get(normalized)
        if correction is not None:
            corrected_description, category = correction
            return CategorizationResult(
                category,
                corrected_description,
                1.0,
                "correction_rule",
                matched_rule=normalized,
            )

        matches: list[tuple[str, str]] = []
        for category, keywords in self.keyword_rules.items():
            for keyword in keywords:
                if f" {keyword} " in f" {normalized} ":
                    matches.append((category, keyword))
        if matches:
            longest_length = max(len(keyword.split()) for _, keyword in matches)
            strongest = [
                (category, keyword)
                for category, keyword in matches
                if len(keyword.split()) == longest_length
            ]
            categories = {category for category, _ in strongest}
        else:
            strongest = []
            categories = set()
        if len(categories) == 1:
            category = next(iter(categories))
            longest_keyword = max(keyword for _, keyword in strongest)
            specificity = min(len(longest_keyword.split()) * 0.05, 0.1)
            return CategorizationResult(
                category,
                normalized,
                min(0.92, 0.82 + specificity),
                "keyword_rule",
                matched_rule=longest_keyword,
            )
        if len(categories) > 1:
            return CategorizationResult(
                "unallocated",
                normalized,
                0.45,
                "ambiguous_keywords",
                warnings=("item matched more than one category",),
            )

        merchant_category = self.merchant_category_rules.get(context.merchant_normalized)
        if merchant_category is not None:
            return CategorizationResult(
                merchant_category,
                normalized,
                0.60,
                "merchant_fallback",
                matched_rule=context.merchant_normalized,
                warnings=("category inferred from merchant because no item rule matched",),
            )
        return CategorizationResult(
            "unallocated",
            normalized,
            0.25,
            "no_match",
            warnings=("no categorization rule matched the item",),
        )

    def categorize_receipt(
        self, items: tuple[ParsedLineItem, ...], context: ReceiptContext
    ) -> CategorizedReceipt:
        categorized = tuple(
            CategorizedLineItem(item, self.categorize_item(item, context)) for item in items
        )
        totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        warnings: list[str] = []
        for entry in categorized:
            totals[entry.categorization.category_internal_name] += entry.item.line_total
            warnings.extend(entry.categorization.warnings)
        allocations = tuple(
            CategoryAllocation(category, amount) for category, amount in sorted(totals.items())
        )
        confidence = (
            min(entry.categorization.confidence for entry in categorized) if categorized else 0.0
        )
        return CategorizedReceipt(
            categorized, allocations, confidence, tuple(dict.fromkeys(warnings))
        )
