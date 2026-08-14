"""Translate confidence and validation signals into review decisions."""

from __future__ import annotations

from dataclasses import dataclass

from spendscope.config import ConfidenceThresholds
from spendscope.domain.enums import (
    ConfidenceLevel,
    ReceiptStatus,
    ReconciliationStatus,
    ReviewStatus,
)


@dataclass(frozen=True, slots=True)
class ConfidenceDecision:
    score: float
    level: ConfidenceLevel
    receipt_status: ReceiptStatus
    review_status: ReviewStatus
    archive_ready: bool
    reporting_ready: bool
    reasons: tuple[str, ...]


class ConfidencePolicy:
    def __init__(self, thresholds: ConfidenceThresholds | None = None) -> None:
        self.thresholds = thresholds or ConfidenceThresholds()

    def decide(
        self,
        *,
        extraction_confidence: float,
        categorization_confidence: float,
        reconciliation_status: ReconciliationStatus,
        validation_errors: tuple[str, ...] = (),
    ) -> ConfidenceDecision:
        score = min(extraction_confidence, categorization_confidence)
        reasons = list(validation_errors)
        invalid_reconciliation = reconciliation_status in {
            ReconciliationStatus.NEEDS_REVIEW,
            ReconciliationStatus.UNRESOLVED,
        }
        if invalid_reconciliation:
            reasons.append(f"reconciliation status is {reconciliation_status.value}")
        if validation_errors or invalid_reconciliation or score < self.thresholds.medium:
            if score < self.thresholds.medium:
                reasons.append("confidence is below the review threshold")
            return ConfidenceDecision(
                score,
                ConfidenceLevel.LOW,
                ReceiptStatus.NEEDS_REVIEW,
                ReviewStatus.REQUIRED,
                False,
                False,
                tuple(dict.fromkeys(reasons)),
            )
        minimum_valid = reconciliation_status in {
            ReconciliationStatus.BALANCED,
            ReconciliationStatus.BALANCED_WITH_ROUNDING,
            ReconciliationStatus.INCOMPLETE_ITEMS,
        }
        if score >= self.thresholds.high and reconciliation_status in {
            ReconciliationStatus.BALANCED,
            ReconciliationStatus.BALANCED_WITH_ROUNDING,
        }:
            return ConfidenceDecision(
                score,
                ConfidenceLevel.HIGH,
                ReceiptStatus.CONFIRMED,
                ReviewStatus.NOT_REQUIRED,
                True,
                True,
                (),
            )
        reasons.append("record should be reviewed when convenient")
        return ConfidenceDecision(
            score,
            ConfidenceLevel.MEDIUM,
            ReceiptStatus.NEEDS_REVIEW,
            ReviewStatus.FLAGGED,
            False,
            minimum_valid,
            tuple(dict.fromkeys(reasons)),
        )
