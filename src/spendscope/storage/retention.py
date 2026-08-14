"""Explicit-confirmation retention operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from spendscope.config import AppConfig
from spendscope.utilities.paths import is_path_within


@dataclass(frozen=True, slots=True)
class RetentionCandidate:
    path: Path
    size_bytes: int
    modified_at: datetime


class RetentionService:
    def __init__(self, config: AppConfig) -> None:
        self.archive = config.directory_paths()["archive"].resolve()

    def candidates_older_than(
        self, days: int, *, now: datetime | None = None
    ) -> list[RetentionCandidate]:
        if days < 1:
            raise ValueError("retention age must be at least one day")
        if not self.archive.exists():
            return []
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(days=days)
        candidates = []
        for path in self.archive.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if modified <= cutoff:
                candidates.append(RetentionCandidate(path, path.stat().st_size, modified))
        return sorted(candidates, key=lambda item: item.modified_at)

    def delete_candidates(
        self, candidates: list[RetentionCandidate], *, confirmed: bool = False
    ) -> int:
        if not confirmed:
            raise PermissionError("retention deletion requires explicit confirmation")
        deleted = 0
        for candidate in candidates:
            if not is_path_within(candidate.path, self.archive):
                raise ValueError("retention candidate is outside the Archive")
            if candidate.path.is_file() and not candidate.path.is_symlink():
                candidate.path.unlink()
                deleted += 1
        return deleted
