"""Receipt date extraction and safe fallback handling."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from spendscope.parsing.models import ParsedValue

_ISO_DATE = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_NUMERIC_DATE = re.compile(
    r"(?<![\d/])\b(\d{1,2})[/.](\d{1,2})[/.](20\d{2}|\d{2})\b(?![\d/])"
)


def parse_date(
    text: str,
    *,
    date_locale: str = "en_US",
    file_modified: datetime | None = None,
    imported_at: datetime | None = None,
) -> tuple[ParsedValue[date], str]:
    now = (imported_at or datetime.now()).date()
    candidates: list[tuple[date, str]] = []
    warnings: list[str] = []
    source_priority = {"receipt": 0, "invoice": 1, "purchase": 2}
    for line in text.splitlines():
        lowered = line.casefold()
        source = (
            "invoice"
            if "invoice" in lowered
            else "purchase"
            if "purchase" in lowered
            else "receipt"
        )
        for year, month, day in _ISO_DATE.findall(line):
            try:
                candidates.append((date(int(year), int(month), int(day)), source))
            except ValueError:
                continue
        for first, second, year in _NUMERIC_DATE.findall(line):
            full_year = int(year) + 2000 if len(year) == 2 else int(year)
            first_number, second_number = int(first), int(second)
            month_first = date_locale.casefold().startswith("en_us")
            month, day = (
                (first_number, second_number) if month_first else (second_number, first_number)
            )
            if first_number <= 12 and second_number <= 12 and first_number != second_number:
                warnings.append("ambiguous numeric date format")
            try:
                candidates.append((date(full_year, month, day), source))
            except ValueError:
                continue
    candidates.sort(key=lambda candidate: source_priority[candidate[1]])
    unique_pairs = tuple(dict.fromkeys(candidates))
    if unique_pairs:
        selected, selected_source = unique_pairs[0]
        unique_dates = tuple(dict.fromkeys(candidate[0] for candidate in unique_pairs))
        if selected > now + timedelta(days=1):
            warnings.append("receipt date is implausibly in the future")
        confidence = 0.9 if not warnings and len(unique_dates) == 1 else 0.6
        return (
            ParsedValue(selected, confidence, unique_dates, tuple(dict.fromkeys(warnings))),
            selected_source,
        )
    if file_modified is not None:
        fallback = file_modified.date()
        return (
            ParsedValue(
                fallback,
                0.4,
                (fallback,),
                ("printed date not found; file metadata date was used",),
            ),
            "file_metadata",
        )
    return (
        ParsedValue(
            now,
            0.25,
            (now,),
            ("printed date not found; import date was used",),
        ),
        "import_time",
    )
