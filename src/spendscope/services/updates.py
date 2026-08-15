"""Small, read-only GitHub Releases update check."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from spendscope.branding import SUPPORT_URL

RELEASES_API = "https://api.github.com/repos/esthermensah/spendscope/releases?per_page=20"


@dataclass(frozen=True, slots=True)
class UpdateResult:
    latest_version: str
    release_url: str
    update_available: bool


def _version_tuple(value: str) -> tuple[int, int, int, int, int]:
    match = re.fullmatch(
        r"v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(alpha|beta|rc)[.-]?(\d+))?",
        value.strip(),
        re.IGNORECASE,
    )
    if match is None:
        raise ValueError(f"Unsupported release version: {value}")
    prerelease = match.group(4)
    stage = 3 if prerelease is None else {"alpha": 0, "beta": 1, "rc": 2}[prerelease.lower()]
    prerelease_number = 0 if prerelease is None else int(match.group(5))
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), stage, prerelease_number


def check_for_update(current_version: str) -> UpdateResult:
    """Read the latest public release without downloading or installing anything."""
    request = Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "SpendScope"},
    )
    with urlopen(request, timeout=8) as response:
        payload: list[dict[str, Any]] = json.load(response)
    release = next((entry for entry in payload if not entry.get("draft", False)), None)
    if release is None:
        raise ValueError("GitHub did not return a published SpendScope release")
    latest = str(release["tag_name"])
    release_url = str(release.get("html_url") or f"{SUPPORT_URL}/releases")
    return UpdateResult(
        latest, release_url, _version_tuple(latest) > _version_tuple(current_version)
    )
