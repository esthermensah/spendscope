"""Conservative item and merchant text normalization."""

from __future__ import annotations

import re
import unicodedata

_SPACE_PATTERN = re.compile(r"\s+")
_PUNCTUATION_PATTERN = re.compile(r"[^a-z0-9&+ ]+")
_MERCHANT_SUFFIX_PATTERN = re.compile(
    r"\b(?:incorporated|inc|limited|ltd|llc|corp(?:oration)?|company|co)\b"
)
_LOCATION_PATTERN = re.compile(r"\b(?:store|shop|location|branch)\s*#?\s*\d+\b")
_ITEM_CODE_PATTERN = re.compile(
    r"\b(?:sku|upc|item)\s*#?\s*[a-z0-9]+(?:-[a-z0-9]+)*\b", re.IGNORECASE
)


def _plain_text(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = _PUNCTUATION_PATTERN.sub(" ", ascii_text.casefold())
    return _SPACE_PATTERN.sub(" ", cleaned).strip()


def normalize_merchant(value: str) -> str:
    normalized = _plain_text(value)
    normalized = _LOCATION_PATTERN.sub(" ", normalized)
    normalized = _MERCHANT_SUFFIX_PATTERN.sub(" ", normalized)
    return _SPACE_PATTERN.sub(" ", normalized).strip()


def normalize_item(value: str) -> str:
    return _plain_text(_ITEM_CODE_PATTERN.sub(" ", value))
