"""Thin Google Sheets API adapter for deterministic workbook updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, cast

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from spendscope.reporting.models import DashboardChart, ReportSnapshot, SheetTable
from spendscope.reporting.summaries import SHEET_NAMES


class SheetsGateway(Protocol):
    def create_workbook(self, title: str) -> tuple[str, str]: ...

    def write_report(self, spreadsheet_id: str, snapshot: ReportSnapshot) -> str: ...


class GoogleSheetsGateway:
    """Create a Drive-organized report and replace app-owned tables."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        service: object | None = None,
        drive_service: object | None = None,
        workspace_name: str = "SpendScope",
    ) -> None:
        self.service: Any = service or build(
            "sheets", "v4", credentials=credentials, cache_discovery=False
        )
        self.drive: Any = drive_service
        if service is None and drive_service is None:
            self.drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.workspace_name = workspace_name

    def create_workbook(self, title: str) -> tuple[str, str]:
        body = {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": name}} for name in SHEET_NAMES],
        }
        response = (
            self.service.spreadsheets()
            .create(body=body, fields="spreadsheetId,spreadsheetUrl")
            .execute()
        )
        spreadsheet_id = str(response["spreadsheetId"])
        if self.drive is not None:
            folder_id = self._find_or_create_workspace_folder()
            self._move_to_folder(spreadsheet_id, folder_id)
        return spreadsheet_id, str(response["spreadsheetUrl"])

    def _find_or_create_workspace_folder(self) -> str:
        escaped = self.workspace_name.replace("'", "\\'")
        response = (
            self.drive.files()
            .list(
                q=(
                    "mimeType = 'application/vnd.google-apps.folder' "
                    f"and name = '{escaped}' and trashed = false"
                ),
                spaces="drive",
                fields="files(id,name)",
                pageSize=1,
            )
            .execute()
        )
        matches = response.get("files", [])
        if matches:
            return str(matches[0]["id"])
        created = (
            self.drive.files()
            .create(
                body={
                    "name": self.workspace_name,
                    "mimeType": "application/vnd.google-apps.folder",
                },
                fields="id",
            )
            .execute()
        )
        return str(created["id"])

    def _move_to_folder(self, spreadsheet_id: str, folder_id: str) -> None:
        metadata = self.drive.files().get(fileId=spreadsheet_id, fields="parents").execute()
        previous_parents = ",".join(str(value) for value in metadata.get("parents", []))
        arguments: dict[str, Any] = {
            "fileId": spreadsheet_id,
            "addParents": folder_id,
            "fields": "id,parents,webViewLink",
        }
        if previous_parents:
            arguments["removeParents"] = previous_parents
        self.drive.files().update(**arguments).execute()

    def write_report(self, spreadsheet_id: str, snapshot: ReportSnapshot) -> str:
        sheet_ids = self._ensure_sheets(spreadsheet_id)
        for table in snapshot.tables:
            self._replace_table(spreadsheet_id, table)
        self._format_tables(spreadsheet_id, snapshot.tables, sheet_ids)
        self._replace_dashboard_charts(
            spreadsheet_id, sheet_ids["Dashboard"], snapshot.dashboard_charts
        )
        metadata = (
            self.service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="spreadsheetUrl")
            .execute()
        )
        return str(
            metadata.get("spreadsheetUrl")
            or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        )

    def _ensure_sheets(self, spreadsheet_id: str) -> dict[str, int]:
        metadata = (
            self.service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets.properties(sheetId,title)",
            )
            .execute()
        )
        sheet_ids = {
            str(sheet["properties"]["title"]): int(sheet["properties"]["sheetId"])
            for sheet in metadata.get("sheets", [])
        }
        missing = [name for name in SHEET_NAMES if name not in sheet_ids]
        if missing:
            response = (
                self.service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={
                        "requests": [
                            {"addSheet": {"properties": {"title": name}}} for name in missing
                        ]
                    },
                )
                .execute()
            )
            for reply, name in zip(response.get("replies", []), missing, strict=True):
                sheet_ids[name] = int(reply["addSheet"]["properties"]["sheetId"])
        return sheet_ids

    def _replace_table(self, spreadsheet_id: str, table: SheetTable) -> None:
        range_name = self._quoted(table.name)
        values_api = self.service.spreadsheets().values()
        values_api.clear(spreadsheetId=spreadsheet_id, range=range_name, body={}).execute()
        values_api.update(
            spreadsheetId=spreadsheet_id,
            range=f"{range_name}!A1",
            valueInputOption="RAW",
            body={"majorDimension": "ROWS", "values": table.values()},
        ).execute()

    def _format_tables(
        self,
        spreadsheet_id: str,
        tables: tuple[SheetTable, ...],
        sheet_ids: Mapping[str, int],
    ) -> None:
        requests: list[dict[str, Any]] = []
        for table in tables:
            sheet_id = sheet_ids[table.name]
            requests.extend(
                [
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": max(1, len(table.headers)),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": {"red": 0.12, "green": 0.35, "blue": 0.29},
                                    "textFormat": {
                                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                        "bold": True,
                                    },
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat)",
                        }
                    },
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "gridProperties": {"frozenRowCount": 1},
                            },
                            "fields": "gridProperties.frozenRowCount",
                        }
                    },
                    {
                        "autoResizeDimensions": {
                            "dimensions": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": 0,
                                "endIndex": max(1, len(table.headers)),
                            }
                        }
                    },
                ]
            )
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    def _replace_dashboard_charts(
        self, spreadsheet_id: str, dashboard_id: int, charts: tuple[DashboardChart, ...]
    ) -> None:
        metadata = (
            self.service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets(properties(sheetId),charts(chartId))",
            )
            .execute()
        )
        existing_ids: list[int] = []
        for sheet in metadata.get("sheets", []):
            if int(sheet["properties"]["sheetId"]) == dashboard_id:
                existing_ids = [int(chart["chartId"]) for chart in sheet.get("charts", [])]
                break
        requests: list[dict[str, Any]] = [
            {"deleteEmbeddedObject": {"objectId": value}} for value in existing_ids
        ]
        for chart in charts:
            if chart.chart_type == "PIE":
                chart_spec: dict[str, Any] = {
                    "pieChart": {
                        "legendPosition": "RIGHT_LEGEND",
                        "pieHole": 0.45,
                        "domain": {
                            "sourceRange": {
                                "sources": [
                                    self._range(
                                        dashboard_id,
                                        chart.domain_column,
                                        chart.start_row,
                                        chart.end_row,
                                    )
                                ]
                            }
                        },
                        "series": {
                            "sourceRange": {
                                "sources": [
                                    self._range(
                                        dashboard_id,
                                        chart.series_columns[0],
                                        chart.start_row,
                                        chart.end_row,
                                    )
                                ]
                            }
                        },
                    }
                }
            else:
                chart_spec = {
                    "basicChart": {
                        "chartType": chart.chart_type,
                        "legendPosition": "BOTTOM_LEGEND",
                        "headerCount": 1,
                        "domains": [
                            {
                                "domain": {
                                    "sourceRange": {
                                        "sources": [
                                            self._range(
                                                dashboard_id,
                                                chart.domain_column,
                                                chart.start_row,
                                                chart.end_row,
                                            )
                                        ]
                                    }
                                }
                            }
                        ],
                        "series": [
                            {
                                "series": {
                                    "sourceRange": {
                                        "sources": [
                                            self._range(
                                                dashboard_id,
                                                column,
                                                chart.start_row,
                                                chart.end_row,
                                            )
                                        ]
                                    }
                                }
                            }
                            for column in chart.series_columns
                        ],
                    }
                }
            requests.append(
                {
                    "addChart": {
                        "chart": {
                            "spec": {
                                "title": chart.title,
                                **chart_spec,
                            },
                            "position": {
                                "overlayPosition": {
                                    "anchorCell": {
                                        "sheetId": dashboard_id,
                                        "rowIndex": chart.anchor_row,
                                        "columnIndex": chart.anchor_column,
                                    },
                                    "widthPixels": 640,
                                    "heightPixels": 320,
                                }
                            },
                        }
                    }
                }
            )
        if requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": requests}
            ).execute()

    @staticmethod
    def _range(sheet_id: int, column: int, start_row: int, end_row: int) -> dict[str, int]:
        return {
            "sheetId": sheet_id,
            "startRowIndex": start_row,
            "endRowIndex": max(start_row + 1, end_row),
            "startColumnIndex": column,
            "endColumnIndex": column + 1,
        }

    @staticmethod
    def _quoted(name: str) -> str:
        return f"'{name.replace(chr(39), chr(39) * 2)}'"


def gateway_for(credentials: Credentials) -> SheetsGateway:
    return cast(SheetsGateway, GoogleSheetsGateway(credentials))
