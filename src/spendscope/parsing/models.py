"""Parser results with confidence, alternatives, and warnings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ParsedValue(Generic[T]):
    value: T | None
    confidence: float
    candidates: tuple[T, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ParsedLineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal | None
    line_total: Decimal
    confidence: float
    source_line: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    calculated_total: Decimal | None
    difference: Decimal | None
    status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ParsedReceipt:
    merchant: ParsedValue[str]
    transaction_date: ParsedValue[date]
    date_source: str
    receipt_number: ParsedValue[str]
    currency: ParsedValue[str]
    items: tuple[ParsedLineItem, ...]
    subtotal: ParsedValue[Decimal]
    tax: ParsedValue[Decimal]
    tip: ParsedValue[Decimal]
    discount: ParsedValue[Decimal]
    final_total: ParsedValue[Decimal]
    amount_paid: ParsedValue[Decimal]
    change: ParsedValue[Decimal]
    reconciliation: ReconciliationResult
    confidence: float
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
