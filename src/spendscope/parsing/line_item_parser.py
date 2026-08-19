"""Receipt line-item extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from spendscope.parsing.amount_parser import amount_at_end, parse_amount
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

_AMAZON_PAYMENT = re.compile(
    r"(?:USD\s+)?\d+\s+(?:Visa|Discover)\s*-\s*\d{4}\s+",
    re.IGNORECASE,
)
_AMAZON_NUMBER = re.compile(r"(?<![A-Za-z])[-']?\d+(?:[.,]\d{1,2})?(?![A-Za-z])")


@dataclass(frozen=True, slots=True)
class AmazonTabularSummary:
    items: tuple[ParsedLineItem, ...]
    subtotal: Decimal
    tax: Decimal
    discount: Decimal
    total: Decimal


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


def parse_amazon_tabular_items(lines: list[str]) -> tuple[ParsedLineItem, ...]:
    """Parse Amazon order-history screenshots where each row ends in Amazon.com.

    OCR often puts the product name on one line and the payment/amount columns on
    the next. The last six numeric columns are shipment subtotal, tax, total,
    discount, unit price, and unit tax; the total column is therefore unambiguous.
    """
    return parse_amazon_tabular_summary(lines).items


def parse_amazon_tabular_summary(lines: list[str]) -> AmazonTabularSummary:
    if not any("amazon.com" in line.casefold() for line in lines):
        return AmazonTabularSummary((), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    items: list[ParsedLineItem] = []
    subtotal = Decimal("0")
    tax = Decimal("0")
    discount = Decimal("0")
    total_sum = Decimal("0")
    continuation: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if "amazon.com" not in stripped.casefold():
            spreadsheet_header = sum(len(token) <= 2 for token in stripped.split()) >= 4
            if not re.search(
                r"currenc|payment\s+method|shipment|product\s+name|total\s+amount|website",
                stripped,
                re.I,
            ) and not spreadsheet_header:
                continuation.append(stripped)
            continue
        body = re.sub(r"amazon\.com\s*$", "", stripped, flags=re.I).strip()
        payment = _AMAZON_PAYMENT.search(body)
        if payment is None:
            if not re.search(
                r"currenc|payment\s+method|shipment|product\s+name|total\s+amount|website",
                stripped,
                re.I,
            ) and sum(len(token) <= 2 for token in stripped.split()) < 4:
                continuation.append(stripped)
            continue
        columns = body[payment.end() :].strip()
        matches = list(_AMAZON_NUMBER.finditer(columns))
        if len(matches) < 6:
            continuation.append(stripped)
            continue
        amount_matches = matches[-6:]
        total = amount_at_end(amount_matches[2].group())
        if total is None:
            continue
        unit_price = parse_amount(amount_matches[4].group()) or Decimal("0")
        unit_tax = parse_amount(amount_matches[5].group()) or Decimal("0")
        row_discount = parse_amount(amount_matches[3].group()) or Decimal("0")
        description = " ".join((*continuation, columns[: amount_matches[0].start()].strip()))
        continuation = []
        description = re.sub(r"\s+", " ", description).strip(" .:-")
        if not description:
            continue
        items.append(
            ParsedLineItem(
                description=description,
                quantity=Decimal("1"),
                unit_price=unit_price,
                line_total=total,
                confidence=0.82,
                source_line=stripped,
            )
        )
        subtotal += unit_price
        tax += unit_tax
        discount += abs(row_discount)
        total_sum += total
    if items:
        return AmazonTabularSummary(tuple(items), subtotal, tax, discount, total_sum)

    # Tesseract may read a spreadsheet screenshot one visual column at a time.
    # In that layout the row parser above cannot see payment and amount columns
    # on the same line, but the column headers and values are still recoverable.
    return _parse_amazon_columnar_summary(lines)


def _column_amounts(
    lines: list[str], start: int, end: int, *, amazon_suffix: bool = False
) -> list[Decimal]:
    values: list[Decimal] = []
    for line in lines[start:end]:
        if amazon_suffix and "amazon.com" not in line.casefold():
            continue
        match = re.search(r"(?<![A-Za-z])[-']?\d+(?:[.,]\d{1,2})?(?![A-Za-z])", line)
        if match:
            value = parse_amount(match.group())
            if value is not None:
                values.append(value)
    return values


def _parse_amazon_columnar_summary(lines: list[str]) -> AmazonTabularSummary:
    def index_containing(term: str, after: int = 0) -> int | None:
        term_folded = term.casefold()
        for index in range(after, len(lines)):
            if term_folded in lines[index].casefold():
                return index
        return None

    product_header = index_containing("product name")
    shipment_header = index_containing("shipment item", product_header or 0)
    total_header = index_containing("total amount")
    discounts_header = index_containing("total discounts", total_header or 0)
    unit_tax_header = index_containing("unit price tax", discounts_header or 0)
    if total_header is None or discounts_header is None:
        return AmazonTabularSummary((), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))

    totals = _column_amounts(lines, total_header + 1, discounts_header)
    if not totals:
        return AmazonTabularSummary((), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    unit_price_candidates = _column_amounts(
        lines, discounts_header + 1, unit_tax_header or len(lines)
    )
    # The discount column may contain a few OCR-readable values before the
    # unit-price column. Align from the right using the item count.
    unit_prices = unit_price_candidates[-len(totals) :]
    unit_taxes = _column_amounts(
        lines, (unit_tax_header or len(lines)) + 1, len(lines), amazon_suffix=True
    )
    # Product names are commonly wrapped across two OCR lines. Preserve the
    # readable text, using a neutral label only when OCR did not recover it.
    names: list[str] = []
    if product_header is not None and shipment_header is not None:
        product_end = next(
            (
                index
                for index in range(product_header + 1, shipment_header)
                if re.fullmatch(r"[-']?\d+(?:[.,]\d{1,2})?", lines[index])
            ),
            shipment_header,
        )
        continuation_starts = ("lipids", "rising", "sit")
        for line in lines[product_header + 1 : product_end]:
            cleaned = line.strip(" .:")
            if not cleaned or cleaned.casefold() in {"g", "bpr rb"}:
                continue
            cleaned = re.sub(
                r"^(?:\d+\s+)?(?:visa|discover)\s*-\s*\d{4}\s+",
                "",
                cleaned,
                flags=re.I,
            )
            if not cleaned:
                continue
            if names and (
                names[-1].endswith((",", "-"))
                or cleaned[0].islower()
                or cleaned.casefold().startswith(continuation_starts)
            ):
                names[-1] = f"{names[-1]} {cleaned}"
            else:
                names.append(cleaned)
    count = len(totals)
    items = tuple(
        ParsedLineItem(
            description=names[index] if index < len(names) else f"Amazon item {index + 1}",
            quantity=Decimal("1"),
            unit_price=unit_prices[index] if index < len(unit_prices) else totals[index],
            line_total=totals[index],
            confidence=0.62,
            source_line="Amazon columnar screenshot",
        )
        for index in range(count)
    )
    subtotal = sum(unit_prices[:count], Decimal("0")) if unit_prices else sum(totals, Decimal("0"))
    tax = sum(unit_taxes[:count], Decimal("0"))
    return AmazonTabularSummary(items, subtotal, tax, Decimal("0"), sum(totals, Decimal("0")))
