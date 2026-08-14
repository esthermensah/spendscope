"""Small, read-only GitHub Releases update check."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from spendscope.branding import SUPPORT_URL

LATEST_RELEASE_API = "https://api.github.com/repos/esthermensah/spendscope/releases/latest"


@dataclass(frozen=True, slots=True)
class UpdateResult:
    latest_version: str
    release_url: str
    update_available: bool


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", value.strip())
    if match is None:
        raise ValueError(f"Unsupported release version: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


def check_for_update(current_version: str) -> UpdateResult:
    """Read the latest public release without downloading or installing anything."""
    request = Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "SpendScope"},
    )
    with urlopen(request, timeout=8) as response:
        payload: dict[str, Any] = json.load(response)
    latest = str(payload["tag_name"])
    release_url = str(payload.get("html_url") or f"{SUPPORT_URL}/releases/latest")
    return UpdateResult(
        latest, release_url, _version_tuple(latest) > _version_tuple(current_version)
    )
