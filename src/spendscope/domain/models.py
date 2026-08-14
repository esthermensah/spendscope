"""Validated domain input models independent of persistence."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from spendscope.domain.enums import (
    LineItemKind,
    ReceiptStatus,
    ReconciliationStatus,
    ReviewStatus,
    SourceType,
)


class Money(BaseModel):
    minor_units: int
    currency: str

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return value

    @classmethod
    def from_decimal(cls, amount: Decimal, currency: str, *, exponent: int = 2) -> Money:
        scale = Decimal(10) ** exponent
        minor_units = int((amount * scale).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
        return cls(minor_units=minor_units, currency=currency)

    def as_decimal(self, *, exponent: int = 2) -> Decimal:
        return Decimal(self.minor_units) / (Decimal(10) ** exponent)


class CategoryDraft(BaseModel):
    internal_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1, max_length=80)
    active: bool = True
    system_category: bool = False


class LineItemDraft(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    description_original: str = Field(min_length=1, max_length=500)
    description_normalized: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price_minor: int | None = None
    line_total_minor: int
    category_internal_name: str
    classification_confidence: float = Field(default=0, ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.REQUIRED
    manually_corrected: bool = False
    kind: LineItemKind = LineItemKind.PURCHASE


class ReceiptDraft(BaseModel):
    receipt_uuid: UUID = Field(default_factory=uuid4)
    merchant_original: str = Field(min_length=1, max_length=300)
    merchant_normalized: str = Field(min_length=1, max_length=300)
    transaction_date: date
    currency: str
    subtotal_minor: int
    tax_minor: int = 0
    tip_minor: int = 0
    discount_minor: int = 0
    final_total_minor: int
    calculated_total_minor: int | None = None
    reconciliation_difference_minor: int | None = None
    reconciliation_status: ReconciliationStatus = ReconciliationStatus.BALANCED
    status: ReceiptStatus = ReceiptStatus.NEEDS_REVIEW
    review_status: ReviewStatus = ReviewStatus.REQUIRED
    source_type: SourceType = SourceType.MANUAL
    date_source: str | None = None
    receipt_number: str | None = None
    source_file_name: str | None = None
    source_file_original_path: str | None = None
    source_file_hash: str | None = None
    transaction_fingerprint: str | None = None
    raw_extracted_text_path: str | None = None
    extraction_confidence: float = Field(default=0, ge=0, le=1)
    items: list[LineItemDraft] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return Money(minor_units=0, currency=value).currency

    @model_validator(mode="after")
    def currency_and_totals_are_coherent(self) -> ReceiptDraft:
        calculated = self.subtotal_minor + self.tax_minor + self.tip_minor - self.discount_minor
        if self.calculated_total_minor is None:
            self.calculated_total_minor = calculated
        if self.reconciliation_difference_minor is None:
            self.reconciliation_difference_minor = (
                self.final_total_minor - self.calculated_total_minor
            )
        if (
            self.reconciliation_status is ReconciliationStatus.BALANCED
            and self.reconciliation_difference_minor != 0
        ):
            raise ValueError("receipt totals do not reconcile")
        if (
            self.reconciliation_status is ReconciliationStatus.BALANCED
            and self.items
            and sum(item.line_total_minor for item in self.items) != self.subtotal_minor
        ):
            raise ValueError("line items must sum to the receipt subtotal")
        return self


class ReceiptItemCorrection(BaseModel):
    id: int | None = Field(default=None, gt=0)
    description: str = Field(min_length=1, max_length=500)
    line_total_minor: int = Field(ge=0)
    category_internal_name: str
    remember: bool = False


class ReceiptCorrectionDraft(BaseModel):
    receipt_id: int = Field(gt=0)
    merchant: str = Field(min_length=1, max_length=300)
    transaction_date: date
    subtotal_minor: int = Field(ge=0)
    tax_minor: int = Field(default=0, ge=0)
    tip_minor: int = Field(default=0, ge=0)
    discount_minor: int = Field(default=0, ge=0)
    final_total_minor: int = Field(ge=0)
    items: list[ReceiptItemCorrection]

    @model_validator(mode="after")
    def totals_reconcile(self) -> ReceiptCorrectionDraft:
        if self.items and sum(item.line_total_minor for item in self.items) != self.subtotal_minor:
            raise ValueError("line items must add up to the subtotal")
        calculated = self.subtotal_minor + self.tax_minor + self.tip_minor - self.discount_minor
        if calculated != self.final_total_minor:
            raise ValueError("subtotal, tax, tip, and discount must add up to the final total")
        item_ids = [item.id for item in self.items if item.id is not None]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("a receipt item cannot be included more than once")
        return self


class BudgetDraft(BaseModel):
    year: int = Field(ge=2000, le=9999)
    month: int = Field(ge=1, le=12)
    category_internal_name: str | None = None
    currency: str
    amount_minor: int = Field(gt=0)
    warning_threshold: int = Field(default=80, ge=1, le=100)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return Money(minor_units=0, currency=value).currency


class ManualExpenseDraft(BaseModel):
    transaction_date: date
    description: str = Field(min_length=1, max_length=500)
    category_internal_name: str
    amount_minor: int = Field(gt=0)
    currency: str
    merchant: str | None = Field(default=None, max_length=300)
    tax_minor: int = Field(default=0, ge=0)
    tip_minor: int = Field(default=0, ge=0)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return Money(minor_units=0, currency=value).currency


class RefundDraft(BaseModel):
    transaction_date: date
    description: str = Field(min_length=1, max_length=500)
    category_internal_name: str
    amount_minor: int = Field(gt=0)
    currency: str
    merchant: str | None = Field(default=None, max_length=300)
    original_receipt_id: int | None = Field(default=None, gt=0)
    original_line_item_id: int | None = Field(default=None, gt=0)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return Money(minor_units=0, currency=value).currency
