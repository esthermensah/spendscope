"""Merchant and receipt-number extraction."""

from __future__ import annotations

import re

from spendscope.parsing.models import ParsedValue

_NON_MERCHANT = re.compile(
    r"(?i)receipt|invoice|date|time|currency|tel|phone|www\.|https?://|subtotal|total|tax|cashier|address"
)
_RECEIPT_NUMBER = re.compile(
    r"(?i)\b(?:receipt|invoice|order|transaction)\s*(?:no\.?|number|#|:)\s*([A-Z0-9-]{3,})"
)


def parse_merchant(lines: list[str]) -> ParsedValue[str]:
    candidates = tuple(
        line.strip()
        for line in lines[:8]
        if line.strip()
        and not _NON_MERCHANT.search(line)
        and not any(char.isdigit() for char in line)
    )
    if not candidates:
        return ParsedValue(None, 0.0, warnings=("merchant could not be identified",))
    return ParsedValue(candidates[0], 0.78 if len(candidates) == 1 else 0.65, candidates)


def parse_receipt_number(text: str) -> ParsedValue[str]:
    matches = tuple(dict.fromkeys(_RECEIPT_NUMBER.findall(text)))
    if not matches:
        return ParsedValue(None, 0.0)
    return ParsedValue(matches[0], 0.9 if len(matches) == 1 else 0.65, matches)
