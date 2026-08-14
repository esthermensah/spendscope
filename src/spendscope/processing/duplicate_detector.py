"""Exact source-file duplicate detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

from sqlalchemy.orm import Session

from spendscope.categorization.normalization import normalize_merchant
from spendscope.database.repositories import ProcessedFileRepository, ReceiptRepository
from spendscope.utilities.hashing import sha256_file


@dataclass(frozen=True, slots=True)
class DuplicateCheck:
    file_hash: str
    duplicate: bool
    existing_file_id: int | None


@dataclass(frozen=True, slots=True)
class ReceiptDuplicateCheck:
    fingerprint: str
    likely_duplicate: bool
    existing_receipt_id: int | None
    reason: str | None


def check_exact_duplicate(session: Session, path: Path) -> DuplicateCheck:
    file_hash = sha256_file(path)
    existing = ProcessedFileRepository(session).get_by_hash(file_hash)
    return DuplicateCheck(
        file_hash=file_hash,
        duplicate=existing is not None,
        existing_file_id=None if existing is None else existing.id,
    )


def build_receipt_fingerprint(
    merchant: str, transaction_date: date, final_total_minor: int, currency: str
) -> str:
    components = (
        normalize_merchant(merchant),
        transaction_date.isoformat(),
        str(final_total_minor),
        currency.strip().upper(),
    )
    return sha256("\x1f".join(components).encode()).hexdigest()


def check_likely_receipt_duplicate(
    session: Session,
    *,
    merchant: str,
    transaction_date: date,
    final_total_minor: int,
    currency: str,
    receipt_number: str | None = None,
) -> ReceiptDuplicateCheck:
    normalized_merchant = normalize_merchant(merchant)
    fingerprint = build_receipt_fingerprint(
        normalized_merchant, transaction_date, final_total_minor, currency
    )
    repository = ReceiptRepository(session)
    existing = repository.get_by_fingerprint(fingerprint)
    reason = "matching receipt fingerprint" if existing is not None else None
    if existing is None and receipt_number:
        existing = repository.find_by_receipt_number(receipt_number.strip(), normalized_merchant)
        reason = "matching merchant and receipt number" if existing is not None else None
    if existing is None and receipt_number:
        existing = repository.find_by_receipt_number_and_amount(
            receipt_number.strip(), final_total_minor, currency
        )
        reason = "matching order number, amount, and currency" if existing is not None else None
    return ReceiptDuplicateCheck(
        fingerprint,
        existing is not None,
        None if existing is None else existing.id,
        reason,
    )
