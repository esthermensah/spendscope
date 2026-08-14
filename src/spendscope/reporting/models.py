"""Transport-neutral report models used by Sheets adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

CellValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class SheetTable:
    name: str
    headers: tuple[str, ...]
    rows: tuple[tuple[CellValue, ...], ...]

    def values(self) -> list[list[CellValue]]:
        return [list(self.headers), *(list(row) for row in self.rows)]


@dataclass(frozen=True, slots=True)
class DashboardChart:
    title: str
    chart_type: str
    domain_column: int
    series_columns: tuple[int, ...]
    start_row: int
    end_row: int
    anchor_row: int
    anchor_column: int


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    generated_at: datetime
    selected_month: str
    selected_currency: str
    tables: tuple[SheetTable, ...]
    dashboard_charts: tuple[DashboardChart, ...]

    def table(self, name: str) -> SheetTable:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)


class SyncState(StrEnum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    SYNCING = "syncing"
    SYNCED = "synced"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SyncResult:
    state: SyncState
    spreadsheet_id: str | None
    spreadsheet_url: str | None
    attempted: int = 0
    synced: int = 0
    failed: int = 0
    error: str | None = None
    completed_at: datetime | None = None
