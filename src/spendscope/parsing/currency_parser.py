"""Original-currency detection without conversion."""

from __future__ import annotations

import re

from spendscope.parsing.models import ParsedValue

_CURRENCY_MARKERS: tuple[tuple[str, str], ...] = (
    (r"\bGHS\b|GH₵", "GHS"),
    (r"\bEUR\b|€", "EUR"),
    (r"\bGBP\b|£", "GBP"),
    (r"\bCAD\b|CA\$", "CAD"),
    (r"\bAUD\b|AU\$", "AUD"),
    (r"\bUSD\b|US\$", "USD"),
)


def parse_currency(text: str, *, default_currency: str) -> ParsedValue[str]:
    found = []
    for pattern, code in _CURRENCY_MARKERS:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(code)
    if not found and "$" in text:
        return ParsedValue(
            default_currency,
            0.55,
            (default_currency,),
            ("unqualified dollar symbol; default currency was used",),
        )
    unique = tuple(dict.fromkeys(found))
    if not unique:
        return ParsedValue(
            default_currency,
            0.35,
            (default_currency,),
            ("currency was not printed; default currency was used",),
        )
    if len(unique) > 1:
        return ParsedValue(
            unique[0],
            0.4,
            unique,
            ("multiple currencies detected; review is required",),
        )
    return ParsedValue(unique[0], 0.95, unique)
