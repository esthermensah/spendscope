"""SQLAlchemy schema for the local authoritative database."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class CategoryRecord(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    internal_name: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    system_category: Mapped[bool] = mapped_column(Boolean, default=False)

    line_items: Mapped[list[LineItemRecord]] = relationship(back_populates="category")
    budgets: Mapped[list[BudgetRecord]] = relationship(back_populates="category")


class ReceiptRecord(TimestampMixin, Base):
    __tablename__ = "receipts"
    __table_args__ = (
        Index("ix_receipts_date_currency_status", "transaction_date", "currency", "review_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_uuid: Mapped[str] = mapped_column(String(36), unique=True)
    merchant_original: Mapped[str] = mapped_column(String(300))
    merchant_normalized: Mapped[str] = mapped_column(String(300), index=True)
    transaction_date: Mapped[date] = mapped_column(Date)
    date_source: Mapped[str | None] = mapped_column(String(40))
    subtotal_minor: Mapped[int] = mapped_column(Integer)
    tax_minor: Mapped[int] = mapped_column(Integer, default=0)
    tip_minor: Mapped[int] = mapped_column(Integer, default=0)
    discount_total_minor: Mapped[int] = mapped_column(Integer, default=0)
    final_total_minor: Mapped[int] = mapped_column(Integer)
    calculated_total_minor: Mapped[int] = mapped_column(Integer)
    reconciliation_difference_minor: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3))
    receipt_number: Mapped[str | None] = mapped_column(String(120))
    payment_method: Mapped[str | None] = mapped_column(String(80))
    source_file_name: Mapped[str | None] = mapped_column(String(500))
    source_file_original_path: Mapped[str | None] = mapped_column(Text)
    source_file_archive_path: Mapped[str | None] = mapped_column(Text)
    source_file_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    transaction_fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    raw_extracted_text_path: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0)
    processing_status: Mapped[str] = mapped_column(String(40))
    reconciliation_status: Mapped[str] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(40))
    sync_status: Mapped[str] = mapped_column(String(40))
    source_type: Mapped[str] = mapped_column(String(20))
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)

    line_items: Mapped[list[LineItemRecord]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )


class LineItemRecord(TimestampMixin, Base):
    __tablename__ = "line_items"
    __table_args__ = (Index("ix_line_items_category_receipt", "category_id", "receipt_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_uuid: Mapped[str] = mapped_column(String(36), unique=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"))
    description_original: Mapped[str] = mapped_column(String(500))
    description_normalized: Mapped[str] = mapped_column(String(500), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=1)
    unit_price_minor: Mapped[int | None] = mapped_column(Integer)
    line_total_minor: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    subcategory: Mapped[str | None] = mapped_column(String(100))
    classification_confidence: Mapped[float] = mapped_column(Float, default=0)
    review_status: Mapped[str] = mapped_column(String(40))
    manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(30), default="purchase")

    receipt: Mapped[ReceiptRecord] = relationship(back_populates="line_items")
    category: Mapped[CategoryRecord] = relationship(back_populates="line_items")


class BudgetRecord(TimestampMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("year", "month", "category_id", "currency", name="uq_budget_scope"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_budget_month"),
        CheckConstraint("budget_amount_minor > 0", name="ck_budget_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    currency: Mapped[str] = mapped_column(String(3))
    budget_amount_minor: Mapped[int] = mapped_column(Integer)
    warning_threshold: Mapped[int] = mapped_column(Integer, default=80)

    category: Mapped[CategoryRecord | None] = relationship(back_populates="budgets")


class MerchantRuleRecord(TimestampMixin, Base):
    __tablename__ = "merchant_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_pattern: Mapped[str] = mapped_column(String(300), unique=True)
    normalized_merchant: Mapped[str] = mapped_column(String(300))
    preferred_category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))


class ItemRuleRecord(TimestampMixin, Base):
    __tablename__ = "item_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_pattern: Mapped[str] = mapped_column(String(500), unique=True)
    normalized_item: Mapped[str] = mapped_column(String(500))
    preferred_category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))


class ProcessedFileRecord(Base):
    __tablename__ = "processed_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(500))
    original_path: Mapped[str] = mapped_column(Text)
    archive_path: Mapped[str | None] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    processing_status: Mapped[str] = mapped_column(String(40))
    original_file_size: Mapped[int] = mapped_column(Integer)
    archived_file_size: Mapped[int | None] = mapped_column(Integer)
    compression_ratio: Mapped[float | None] = mapped_column(Float)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    error_message: Mapped[str | None] = mapped_column(Text)


class SyncQueueRecord(TimestampMixin, Base):
    __tablename__ = "sync_queue"
    __table_args__ = (Index("ix_sync_queue_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class ReviewCaseRecord(TimestampMixin, Base):
    __tablename__ = "review_cases"
    __table_args__ = (Index("ix_review_cases_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class ManualExpenseDetailRecord(Base):
    __tablename__ = "manual_expense_details"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), unique=True
    )
    note: Mapped[str | None] = mapped_column(Text)


class RefundLinkRecord(TimestampMixin, Base):
    __tablename__ = "refund_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    refund_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), unique=True
    )
    original_receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipts.id", ondelete="SET NULL")
    )
    refund_line_item_id: Mapped[int] = mapped_column(
        ForeignKey("line_items.id", ondelete="CASCADE")
    )
    original_line_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("line_items.id", ondelete="SET NULL")
    )


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_entity_created", "entity_type", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80))
    details_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class SettingRecord(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
