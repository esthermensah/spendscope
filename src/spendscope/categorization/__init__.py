"""Deterministic local item categorization and receipt allocation."""

from spendscope.categorization.engine import RuleBasedCategorizer
from spendscope.categorization.memory import CorrectionMemory
from spendscope.categorization.models import (
    CategorizationResult,
    CategorizedReceipt,
    CategoryAllocation,
    ReceiptContext,
)
from spendscope.categorization.normalization import normalize_item, normalize_merchant

__all__ = [
    "CategorizationResult",
    "CategorizedReceipt",
    "CategoryAllocation",
    "CorrectionMemory",
    "ReceiptContext",
    "RuleBasedCategorizer",
    "normalize_item",
    "normalize_merchant",
]
