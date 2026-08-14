from decimal import Decimal

import pytest

from spendscope.parsing.amount_parser import amount_at_end, parse_amount, parse_labeled_amount
from spendscope.parsing.currency_parser import parse_currency


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,234.56", Decimal("1234.56")),
        ("EUR 1.234,56", Decimal("1234.56")),
        ("(12.50)", Decimal("-12.50")),
        ("GH₵ 860.00", Decimal("860.00")),
        ("- 5.00", Decimal("-5.00")),
    ],
)
def test_parse_amount_formats(raw: str, expected: Decimal) -> None:
    assert parse_amount(raw) == expected


def test_amount_parsing_rejects_invalid_text() -> None:
    assert parse_amount("none") is None
    assert amount_at_end("No amount") is None


@pytest.mark.parametrize(
    "line",
    [
        "Total $64.20 >",
        "Total $64.20 \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}",
        "Total $64.20 \N{RIGHTWARDS ARROW}",
    ],
)
def test_amount_at_end_allows_app_navigation_chevrons(line: str) -> None:
    assert amount_at_end(line) == Decimal("64.20")


def test_labeled_amount_reports_multiple_candidates() -> None:
    parsed = parse_labeled_amount(["Subtotal 10.00", "Updated subtotal 12.00"], (r"subtotal",))
    assert parsed.value == Decimal("12.00")
    assert parsed.candidates == (Decimal("10.00"), Decimal("12.00"))
    assert parsed.warnings


def test_currency_detection_handles_explicit_ambiguous_and_fallback() -> None:
    assert parse_currency("Total GHS 10", default_currency="USD").value == "GHS"
    ambiguous = parse_currency("USD 5 and EUR 4", default_currency="USD")
    assert ambiguous.confidence == 0.4
    assert ambiguous.candidates == ("EUR", "USD")
    dollar = parse_currency("Total $5.00", default_currency="CAD")
    assert dollar.value == "CAD" and dollar.warnings
    missing = parse_currency("Total 5.00", default_currency="GBP")
    assert missing.value == "GBP" and missing.confidence == 0.35
