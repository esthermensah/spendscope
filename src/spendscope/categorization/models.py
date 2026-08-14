"""Values exchanged by the categorization engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from spendscope.parsing.models import ParsedLineItem


@dataclass(frozen=True, slots=True)
class ReceiptContext:
    merchant_original: str
    merchant_normalized: str


@dataclass(frozen=True, slots=True)
class CategorizationResult:
    category_internal_name: str
    normalized_description: str
    confidence: float
    source: str
    matched_rule: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CategorizedLineItem:
    item: ParsedLineItem
    categorization: CategorizationResult


@dataclass(frozen=True, slots=True)
class CategoryAllocation:
    category_internal_name: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class CategorizedReceipt:
    items: tuple[CategorizedLineItem, ...]
    allocations: tuple[CategoryAllocation, ...]
    confidence: float
    warnings: tuple[str, ...] = field(default_factory=tuple)
