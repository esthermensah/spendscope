from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from google.oauth2.credentials import Credentials

from spendscope.reporting.google_sheets import GoogleSheetsGateway
from spendscope.reporting.models import DashboardChart, ReportSnapshot, SheetTable
from spendscope.reporting.summaries import SHEET_NAMES


class Request:
    def __init__(
        self, response: dict[str, Any], calls: list[dict[str, Any]], payload: dict[str, Any]
    ) -> None:
        self.response = response
        self.calls = calls
        self.payload = payload

    def execute(self) -> dict[str, Any]:
        self.calls.append(self.payload)
        return self.response


class ValuesResource:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.calls = calls

    def clear(self, **kwargs: Any) -> Request:
        return Request({}, self.calls, {"method": "clear", **kwargs})

    def update(self, **kwargs: Any) -> Request:
        return Request({}, self.calls, {"method": "update", **kwargs})


class SpreadsheetResource:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.get_count = 0

    def create(self, **kwargs: Any) -> Request:
        return Request(
            {"spreadsheetId": "sheet-123", "spreadsheetUrl": "https://example.test/sheet-123"},
            self.calls,
            {"method": "create", **kwargs},
        )

    def get(self, **kwargs: Any) -> Request:
        self.get_count += 1
        if "charts" in kwargs.get("fields", ""):
            response = {"sheets": [{"properties": {"sheetId": 1}, "charts": []}]}
        elif "sheetId,title" in kwargs.get("fields", ""):
            response = {"sheets": []}
        else:
            response = {"spreadsheetUrl": "https://example.test/sheet-123"}
        return Request(response, self.calls, {"method": "get", **kwargs})

    def batchUpdate(self, **kwargs: Any) -> Request:
        requests = kwargs["body"]["requests"]
        if requests and "addSheet" in requests[0]:
            response = {
                "replies": [
                    {"addSheet": {"properties": {"sheetId": index + 1}}}
                    for index, _ in enumerate(requests)
                ]
            }
        else:
            response = {}
        return Request(response, self.calls, {"method": "batchUpdate", **kwargs})

    def values(self) -> ValuesResource:
        return ValuesResource(self.calls)


class Service:
    def __init__(self) -> None:
        self.resource = SpreadsheetResource()

    def spreadsheets(self) -> SpreadsheetResource:
        return self.resource


class DriveFilesResource:
    def __init__(self, *, existing_folder: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.existing_folder = existing_folder

    def list(self, **kwargs: Any) -> Request:
        files = [{"id": "folder-existing", "name": "SpendScope"}] if self.existing_folder else []
        return Request({"files": files}, self.calls, {"method": "list", **kwargs})

    def create(self, **kwargs: Any) -> Request:
        return Request({"id": "folder-new"}, self.calls, {"method": "create", **kwargs})

    def get(self, **kwargs: Any) -> Request:
        return Request({"parents": ["root"]}, self.calls, {"method": "get", **kwargs})

    def update(self, **kwargs: Any) -> Request:
        return Request({}, self.calls, {"method": "update", **kwargs})


class DriveService:
    def __init__(self, *, existing_folder: bool = False) -> None:
        self.resource = DriveFilesResource(existing_folder=existing_folder)

    def files(self) -> DriveFilesResource:
        return self.resource


def test_create_workbook_requests_every_required_sheet() -> None:
    service = Service()
    gateway = GoogleSheetsGateway(cast(Credentials, object()), service=service)

    spreadsheet_id, url = gateway.create_workbook("Spend Report")

    body = service.resource.calls[0]["body"]
    assert spreadsheet_id == "sheet-123"
    assert url == "https://example.test/sheet-123"
    assert len(body["sheets"]) == 10
    assert body["sheets"][0]["properties"]["title"] == "Dashboard"


def test_create_workbook_creates_drive_folder_and_moves_report() -> None:
    service = Service()
    drive = DriveService()
    gateway = GoogleSheetsGateway(cast(Credentials, object()), service=service, drive_service=drive)

    gateway.create_workbook("Spend Report")

    calls = drive.resource.calls
    assert [call["method"] for call in calls] == ["list", "create", "get", "update"]
    assert calls[1]["body"] == {
        "name": "SpendScope",
        "mimeType": "application/vnd.google-apps.folder",
    }
    assert calls[-1]["fileId"] == "sheet-123"
    assert calls[-1]["addParents"] == "folder-new"
    assert calls[-1]["removeParents"] == "root"


def test_create_workbook_reuses_app_created_drive_folder() -> None:
    service = Service()
    drive = DriveService(existing_folder=True)
    gateway = GoogleSheetsGateway(cast(Credentials, object()), service=service, drive_service=drive)

    gateway.create_workbook("Spend Report")

    calls = drive.resource.calls
    assert [call["method"] for call in calls] == ["list", "get", "update"]
    assert calls[-1]["addParents"] == "folder-existing"


def test_sheet_names_are_safely_quoted() -> None:
    assert GoogleSheetsGateway._quoted("Monthly Summary") == "'Monthly Summary'"
    assert GoogleSheetsGateway._quoted("Owner's Sheet") == "'Owner''s Sheet'"


def test_write_report_replaces_tables_formats_sheets_and_builds_charts() -> None:
    service = Service()
    gateway = GoogleSheetsGateway(cast(Credentials, object()), service=service)
    tables = tuple(
        SheetTable(name, ("ID", "Amount"), ((f"{name}-1", 12.5),)) for name in SHEET_NAMES
    )
    snapshot = ReportSnapshot(
        generated_at=datetime(2026, 8, 7),
        selected_month="2026-08",
        selected_currency="USD",
        tables=tables,
        dashboard_charts=(DashboardChart("Spending", "PIE", 0, (1,), 0, 2, 3, 4),),
    )

    url = gateway.write_report("sheet-123", snapshot)

    methods = [call["method"] for call in service.resource.calls]
    assert url == "https://example.test/sheet-123"
    assert methods.count("clear") == 10
    assert methods.count("update") == 10
    assert methods.count("batchUpdate") == 3
    chart_call = next(
        call
        for call in service.resource.calls
        if call["method"] == "batchUpdate"
        and call["body"]["requests"]
        and "addChart" in call["body"]["requests"][0]
    )
    assert chart_call["body"]["requests"][0]["addChart"]["chart"]["spec"]["title"] == "Spending"
    assert "pieChart" in chart_call["body"]["requests"][0]["addChart"]["chart"]["spec"]
