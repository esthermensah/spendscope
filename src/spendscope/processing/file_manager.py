"""Collision-safe receipt file lifecycle operations."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from spendscope.config import AppConfig, RetentionPolicy
from spendscope.processing.file_validator import ReceiptFileValidator
from spendscope.storage.compression import compress_image
from spendscope.utilities.paths import collision_safe_path, is_path_within


@dataclass(frozen=True, slots=True)
class FileLifecycleResult:
    destination: Path | None
    original_size: int
    archived_size: int | None
    action: str


class ReceiptFileManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.paths = config.directory_paths()

    def create_workspace(self) -> dict[str, Path]:
        for path in self.paths.values():
            path.mkdir(parents=True, exist_ok=True)
        return dict(self.paths)

    def import_to_inbox(self, sources: list[Path]) -> tuple[list[Path], list[str]]:
        """Copy user-selected receipt files into Inbox after defensive validation."""
        self.create_workspace()
        inbox = self.paths["inbox"].resolve()
        validator = ReceiptFileValidator(
            inbox, max_size_bytes=self.config.max_import_size_mb * 1024 * 1024
        )
        imported: list[Path] = []
        rejected: list[str] = []
        for source in sources:
            validation = validator.validate_source(source)
            if not validation.valid:
                rejected.append(f"{source.name}: {validation.reason}")
                continue
            resolved = source.resolve()
            if resolved.parent == inbox:
                imported.append(resolved)
                continue
            destination = collision_safe_path(inbox, source.name)
            try:
                shutil.copy2(resolved, destination)
            except OSError as error:
                rejected.append(f"{source.name}: {error}")
            else:
                imported.append(destination)
        return imported, rejected

    def archive_confirmed(
        self,
        source: Path,
        transaction_date: date,
        *,
        destructive_confirmed: bool = False,
    ) -> FileLifecycleResult:
        source = self._validated_pending_source(source)
        original_size = source.stat().st_size
        policy = self.config.retention_policy
        if policy == RetentionPolicy.DELETE_AFTER_CONFIRMATION and not destructive_confirmed:
            raise PermissionError("deletion requires explicit confirmation")
        if policy == RetentionPolicy.DELETE_AFTER_CONFIRMATION:
            source.unlink()
            return FileLifecycleResult(None, original_size, None, "deleted")

        archive_directory = (
            self.paths["archive"] / str(transaction_date.year) / f"{transaction_date.month:02d}"
        )
        archive_directory.mkdir(parents=True, exist_ok=True)
        destination = collision_safe_path(archive_directory, source.name)
        if policy == RetentionPolicy.COMPRESS_CONFIRMED and source.suffix.casefold() in {
            ".jpg",
            ".jpeg",
            ".png",
        }:
            compressed = compress_image(
                source,
                destination,
                quality=self.config.compression_quality,
                max_dimension=self.config.max_image_dimension,
            )
            source.unlink()
            return FileLifecycleResult(
                destination,
                original_size,
                compressed.archived_size,
                "compressed",
            )

        shutil.move(str(source), destination)
        return FileLifecycleResult(
            destination, original_size, destination.stat().st_size, "archived"
        )

    def move_to_review(self, source: Path) -> FileLifecycleResult:
        source = self._validated_inbox_source(source)
        original_size = source.stat().st_size
        destination = collision_safe_path(self.paths["needs_review"], source.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), destination)
        return FileLifecycleResult(
            destination, original_size, destination.stat().st_size, "needs_review"
        )

    def _validated_inbox_source(self, source: Path) -> Path:
        if source.is_symlink():
            raise ValueError("receipt source must not be a symbolic link")
        source = source.resolve()
        if not is_path_within(source, self.paths["inbox"]):
            raise ValueError("receipt source must be inside the configured Inbox")
        if not source.is_file():
            raise ValueError("receipt source must be a regular file")
        return source

    def _validated_pending_source(self, source: Path) -> Path:
        if source.is_symlink():
            raise ValueError("receipt source must not be a symbolic link")
        source = source.resolve()
        allowed = (self.paths["inbox"], self.paths["needs_review"])
        if not any(is_path_within(source, directory) for directory in allowed):
            raise ValueError("receipt source must be inside Inbox or Needs Review")
        if not source.is_file():
            raise ValueError("receipt source must be a regular file")
        return source
