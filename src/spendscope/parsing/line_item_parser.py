"""Receipt line-item extraction."""

from __future__ import annotations

import re
from decimal import Decimal

from spendscope.parsing.amount_parser import amount_at_end
from spendscope.parsing.models import ParsedLineItem

_SUMMARY_LABEL = re.compile(
    r"(?i)\bsub\s*total\b|\btotal\b|\btax\b|\btip\b|\bgratuity\b|"
    r"\bdiscount\b|\bchange\b|\bamount paid\b|\bbalance\b|"
    r"\breceipt\b|\binvoice\b|\border\b|\btransaction\b|\bdate\b"
)
_QUANTITY = re.compile(
    r"^(?P<description>.+?)\s+(?P<quantity>\d+(?:\.\d+)?)\s*[x@]\s*(?P<unit>\d+[.,]\d{2})\s+",
    re.IGNORECASE,
)
_TRAILING_AMOUNT = re.compile(
    r"\(?\s*[-\N{MINUS SIGN}]?\s*"
    r"(?:(?:USD|EUR|GBP|GHS|CAD|AUD|GH₵|US\$|CA\$|[€£$])\s*)?"
    r"(?:\d{1,3}(?:[., ]\d{3})+|\d+)(?:[.,]\d{1,2})?\s*\)?\s*$",
    re.IGNORECASE,
)
_CREDIBLE_ITEM_AMOUNT = re.compile(
    r"(?:"
    r"(?:USD|EUR|GBP|GHS|CAD|AUD|GH₵|US\$|CA\$|[€£$])\s*\d+(?:[.,]\d{1,2})?"
    r"|\d+[.,]\d{2}"
    r")\s*$",
    re.IGNORECASE,
)


def parse_line_items(lines: list[str]) -> tuple[ParsedLineItem, ...]:
    items = []
    for line in lines:
        stripped = line.strip()
        if not stripped or _SUMMARY_LABEL.search(stripped):
            continue
        # Addresses, dates, phone numbers, order IDs, and status text commonly end in
        # integers. A credible item row must end in cents or an explicitly marked currency.
        if _CREDIBLE_ITEM_AMOUNT.search(stripped) is None:
            continue
        total = amount_at_end(stripped)
        if total is None:
            continue
        description_part = _TRAILING_AMOUNT.sub("", stripped).strip(" .:-")
        if not description_part or not any(character.isalpha() for character in description_part):
            continue
        quantity = Decimal("1")
        unit_price = None
        confidence = 0.72
        quantity_match = _QUANTITY.search(stripped)
        if quantity_match:
            description_part = quantity_match.group("description").strip(" .:-")
            quantity = Decimal(quantity_match.group("quantity"))
            unit_price_text = quantity_match.group("unit").replace(",", ".")
            unit_price = Decimal(unit_price_text)
            confidence = 0.88
        items.append(
            ParsedLineItem(
                description=description_part,
                quantity=quantity,
                unit_price=unit_price,
                line_total=total,
                confidence=confidence,
                source_line=stripped,
            )
        )
    return tuple(items)
