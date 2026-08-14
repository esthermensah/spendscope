"""Safe local path operations."""

from __future__ import annotations

import re
from pathlib import Path

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def is_path_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def safe_filename(name: str) -> str:
    candidate = _UNSAFE_FILENAME.sub("_", Path(name).name).strip(" .")
    return candidate or "receipt"


def collision_safe_path(directory: Path, filename: str) -> Path:
    sanitized = safe_filename(filename)
    candidate = directory / sanitized
    if not candidate.exists():
        return candidate
    stem = Path(sanitized).stem
    suffix = Path(sanitized).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
