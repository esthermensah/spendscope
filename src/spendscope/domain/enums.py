"""Stable values persisted by the application."""

from enum import StrEnum


class ReceiptStatus(StrEnum):
    DISCOVERED = "discovered"
    PROCESSING = "processing"
    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    FLAGGED = "flagged"
    REQUIRED = "required"
    RESOLVED = "resolved"


class SyncStatus(StrEnum):
    LOCAL_ONLY = "local_only"
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    FAILED = "failed"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReconciliationStatus(StrEnum):
    BALANCED = "balanced"
    BALANCED_WITH_ROUNDING = "balanced_with_rounding"
    INCOMPLETE_ITEMS = "incomplete_items"
    NEEDS_REVIEW = "needs_review"
    UNRESOLVED = "unresolved"


class BudgetStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    OVER_BUDGET = "over_budget"


class ReviewCaseStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReviewSeverity(StrEnum):
    MEDIUM = "medium"
    HIGH = "high"


class SourceType(StrEnum):
    IMAGE = "image"
    PDF = "pdf"
    MANUAL = "manual"


class LineItemKind(StrEnum):
    PURCHASE = "purchase"
    REFUND = "refund"
    TAX = "tax"
    TIP = "tip"
    DISCOUNT = "discount"
    ADJUSTMENT = "adjustment"
    UNALLOCATED = "unallocated"
