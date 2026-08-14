"""Read-only storage usage calculations."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from spendscope.config import AppConfig


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


@dataclass(frozen=True, slots=True)
class StorageReport:
    inbox_bytes: int
    archive_bytes: int
    needs_review_bytes: int
    database_bytes: int
    logs_bytes: int
    exports_bytes: int
    total_bytes: int
    disk_capacity_bytes: int
    disk_free_bytes: int

    @property
    def disk_usage_percent(self) -> float:
        if self.disk_capacity_bytes <= 0:
            return 0.0
        return self.total_bytes / self.disk_capacity_bytes * 100

    def as_dict(self) -> dict[str, int]:
        return {
            "inbox": self.inbox_bytes,
            "archive": self.archive_bytes,
            "needs_review": self.needs_review_bytes,
            "database": self.database_bytes,
            "logs": self.logs_bytes,
            "exports": self.exports_bytes,
            "total": self.total_bytes,
        }


def calculate_storage_usage(config: AppConfig) -> StorageReport:
    paths = config.directory_paths()
    disk_path = config.root_folder
    while not disk_path.exists() and disk_path != disk_path.parent:
        disk_path = disk_path.parent
    disk = shutil.disk_usage(disk_path)
    return StorageReport(
        inbox_bytes=path_size(paths["inbox"]),
        archive_bytes=path_size(paths["archive"]),
        needs_review_bytes=path_size(paths["needs_review"]),
        database_bytes=path_size(config.database_path),
        logs_bytes=path_size(paths["logs"]),
        exports_bytes=path_size(paths["exports"]),
        total_bytes=path_size(config.root_folder),
        disk_capacity_bytes=disk.total,
        disk_free_bytes=disk.free,
    )
