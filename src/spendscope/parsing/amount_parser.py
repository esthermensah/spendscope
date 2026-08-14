"""Locale-tolerant monetary amount parsing."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from spendscope.parsing.models import ParsedValue

_AMOUNT_AT_END = re.compile(
    r"(?P<amount>\(?\s*[-\N{MINUS SIGN}]?\s*"
    r"(?:USD|EUR|GBP|GHS|CAD|AUD|GH₵|US\$|CA\$|[€£$])?\s*"
    r"(?:\d{1,3}(?:[., ]\d{3})+|\d+)(?:[.,]\d{1,2})?\s*\)?)\s*"
    r"[>\N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}\N{RIGHTWARDS ARROW}]?\s*$",
    re.IGNORECASE,
)


def parse_amount(value: str) -> Decimal | None:
    cleaned = value.strip().replace("\N{MINUS SIGN}", "-").replace("\u00a0", " ")
    negative_parentheses = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = re.sub(r"(?i)USD|EUR|GBP|GHS|CAD|AUD|GH₵|US\$|CA\$|[€£$()]", "", cleaned)
    cleaned = cleaned.replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        decimals = len(cleaned.rsplit(",", 1)[1])
        cleaned = cleaned.replace(",", ".") if decimals in {1, 2} else cleaned.replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -abs(amount) if negative_parentheses else amount


def amount_at_end(line: str) -> Decimal | None:
    match = _AMOUNT_AT_END.search(line)
    return None if match is None else parse_amount(match.group("amount"))


def parse_labeled_amount(
    lines: list[str], labels: tuple[str, ...], *, prefer_last: bool = True
) -> ParsedValue[Decimal]:
    matches: list[Decimal] = []
    for line in lines:
        lowered = line.casefold()
        if any(re.search(label, lowered) for label in labels):
            amount = amount_at_end(line)
            if amount is not None:
                matches.append(amount)
    if not matches:
        return ParsedValue(None, 0.0)
    selected = matches[-1] if prefer_last else matches[0]
    warnings = ("multiple labeled amount candidates found",) if len(matches) > 1 else ()
    confidence = 0.9 if len(matches) == 1 else 0.7
    return ParsedValue(selected, confidence, tuple(matches), warnings)
