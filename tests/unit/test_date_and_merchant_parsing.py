from datetime import datetime

from spendscope.parsing.date_parser import parse_date
from spendscope.parsing.merchant_parser import parse_merchant, parse_receipt_number


def test_date_parser_prefers_printed_iso_date() -> None:
    parsed, source = parse_date("Purchase date: 2026-08-05", imported_at=datetime(2026, 8, 6))
    assert str(parsed.value) == "2026-08-05"
    assert source == "purchase"
    assert parsed.confidence == 0.9


def test_date_parser_flags_ambiguous_and_future_dates() -> None:
    parsed, _ = parse_date("Date 08/09/2027", imported_at=datetime(2026, 8, 6))
    assert "ambiguous" in " ".join(parsed.warnings)
    assert "future" in " ".join(parsed.warnings)


def test_date_parser_uses_metadata_then_import_fallback() -> None:
    metadata = datetime(2026, 7, 1, 10, 0)
    parsed, source = parse_date("No printed date", file_modified=metadata)
    assert str(parsed.value) == "2026-07-01" and source == "file_metadata"
    imported, source = parse_date("No date", imported_at=datetime(2026, 8, 6))
    assert str(imported.value) == "2026-08-06" and source == "import_time"


def test_date_parser_prioritizes_transaction_over_invoice_and_purchase() -> None:
    parsed, source = parse_date(
        "Invoice date 2026-08-01\nPurchase date 2026-08-02\nDate 2026-08-03",
        imported_at=datetime(2026, 8, 6),
    )
    assert str(parsed.value) == "2026-08-03"
    assert source == "receipt"


def test_merchant_and_receipt_number_parsing() -> None:
    merchant = parse_merchant(["THE CORNER MARKET", "Receipt # AB-123", "Rice 5.00"])
    assert merchant.value == "THE CORNER MARKET"
    number = parse_receipt_number("Receipt # AB-123")
    assert number.value == "AB-123"


def test_missing_merchant_and_receipt_number_are_visible() -> None:
    merchant = parse_merchant(["Receipt", "Date 2026-01-01", "Total 1.00"])
    assert merchant.value is None and merchant.warnings
    assert parse_receipt_number("No identifier here").value is None
