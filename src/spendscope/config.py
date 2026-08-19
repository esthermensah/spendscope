"""Validated, non-secret local application settings."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from spendscope.branding import DEFAULT_REPORT_TITLE

DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("groceries", "Groceries"),
    ("eating_out", "Eating Out"),
    ("transportation", "Transportation"),
    ("housing", "Housing"),
    ("utilities", "Utilities"),
    ("household", "Household"),
    ("personal_care", "Personal Care"),
    ("healthcare", "Healthcare"),
    ("education", "Education"),
    ("shopping", "Shopping"),
    ("entertainment", "Entertainment"),
    ("travel", "Travel"),
    ("subscriptions", "Subscriptions"),
    ("gifts_donations", "Gifts and Donations"),
    ("tax", "Tax"),
    ("tips", "Tips"),
    ("unallocated", "Unallocated"),
    ("one_time_purchases", "One-time purchases"),
    ("other", "Other"),
)


class RetentionPolicy(StrEnum):
    KEEP_ORIGINALS = "keep_originals"
    COMPRESS_CONFIRMED = "compress_confirmed"
    DELETE_AFTER_30_DAYS = "delete_after_30_days"
    DELETE_AFTER_CONFIRMATION = "delete_after_confirmation"


class Appearance(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class FolderNames(BaseModel):
    inbox: str = "Inbox"
    archive: str = "Archive"
    needs_review: str = "Needs Review"
    data: str = "Data"
    exports: str = "Exports"
    config: str = "Config"

    @field_validator("inbox", "archive", "needs_review", "data", "exports", "config")
    @classmethod
    def safe_relative_name(cls, value: str) -> str:
        candidate = Path(value)
        if not value.strip() or candidate.is_absolute() or len(candidate.parts) != 1:
            raise ValueError("folder names must be non-empty single relative path components")
        if value in {".", ".."}:
            raise ValueError("folder names cannot traverse directories")
        return value

    @model_validator(mode="after")
    def unique_names(self) -> FolderNames:
        values = [self.inbox, self.archive, self.needs_review, self.data, self.exports, self.config]
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("folder names must be unique")
        return self


class ConfidenceThresholds(BaseModel):
    high: float = Field(default=0.85, ge=0, le=1)
    medium: float = Field(default=0.60, ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self) -> ConfidenceThresholds:
        if self.medium >= self.high:
            raise ValueError("medium confidence must be below high confidence")
        return self


class AppConfig(BaseModel):
    root_folder: Path
    local_database_path: Path | None = None
    default_currency: str = "USD"
    appearance: Appearance = Appearance.SYSTEM
    folders: FolderNames = Field(default_factory=FolderNames)
    retention_policy: RetentionPolicy = RetentionPolicy.COMPRESS_CONFIRMED
    compression_quality: int = Field(default=85, ge=40, le=95)
    max_import_size_mb: int = Field(default=25, ge=1, le=200)
    max_image_dimension: int = Field(default=2400, ge=800, le=8000)
    ocr_executable: Path | None = None
    ocr_language: str = "eng"
    max_pdf_pages: int = Field(default=10, ge=1, le=100)
    minimum_pdf_text_characters: int = Field(default=40, ge=1, le=1000)
    reconciliation_tolerance_minor: int = Field(default=2, ge=0, le=100)
    confidence: ConfidenceThresholds = Field(default_factory=ConfidenceThresholds)
    report_title: str = DEFAULT_REPORT_TITLE
    google_sheet_id: str | None = None
    sync_enabled: bool = False
    date_locale: str = "en_US"
    budget_warning_percent: int = Field(default=80, ge=1, le=100)

    @field_validator("root_folder", "local_database_path")
    @classmethod
    def normalize_path(cls, value: Path | None) -> Path | None:
        return None if value is None else value.expanduser().resolve()

    @field_validator("default_currency")
    @classmethod
    def currency_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return normalized

    @model_validator(mode="after")
    def sync_requires_sheet(self) -> AppConfig:
        if self.sync_enabled and not self.google_sheet_id:
            raise ValueError("sync requires a Google Sheet ID")
        return self

    @property
    def database_path(self) -> Path:
        return self.local_database_path or self.root_folder / self.folders.data / "expenses.db"

    def directory_paths(self) -> dict[str, Path]:
        receipt_root = self.root_folder / "Receipts"
        paths = {
            "inbox": receipt_root / self.folders.inbox,
            "archive": receipt_root / self.folders.archive,
            "needs_review": receipt_root / self.folders.needs_review,
            "data": self.root_folder / self.folders.data,
            "exports": self.root_folder / self.folders.exports,
            "config": self.root_folder / self.folders.config,
            "receipts": receipt_root,
        }
        data = paths["data"]
        paths.update(
            logs=data / "logs",
            backups=data / "backups",
        )
        return paths

    def public_dict(self) -> dict[str, Any]:
        """Return serializable non-secret settings."""
        return self.model_dump(mode="json")


def save_config(config: AppConfig, destination: Path) -> None:
    """Atomically save non-secret configuration as readable JSON."""
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.write_text(
        json.dumps(config.public_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def load_config(source: Path) -> AppConfig:
    """Load and validate local configuration."""
    return AppConfig.model_validate_json(source.expanduser().resolve().read_text(encoding="utf-8"))
