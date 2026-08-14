from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

from google.oauth2.credentials import Credentials
from sqlalchemy import Engine, select

from spendscope.config import AppConfig
from spendscope.database.connection import session_scope
from spendscope.database.schema import SyncQueueRecord
from spendscope.domain.models import BudgetDraft, ManualExpenseDraft
from spendscope.reporting.google_auth import DEFAULT_SCOPES, GoogleOAuthManager
from spendscope.reporting.google_sheets import SheetsGateway
from spendscope.reporting.models import ReportSnapshot, SyncState
from spendscope.reporting.summaries import SHEET_NAMES, ReportBuilder
from spendscope.reporting.sync_service import LAST_SYNC_SETTING, ReportSyncService
from spendscope.services.budgets import BudgetService
from spendscope.services.expenses import ManualExpenseService


class MemoryCredentialStore:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def get(self) -> str | None:
        return self.value

    def set(self, token_json: str) -> None:
        self.value = token_json

    def delete(self) -> None:
        self.value = None


class FakeFlow:
    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials

    def run_local_server(self, *, port: int) -> Credentials:
        assert port == 0
        return self.credentials


class FakeGateway:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.snapshots: list[ReportSnapshot] = []
        self.created_titles: list[str] = []

    def create_workbook(self, title: str) -> tuple[str, str]:
        self.created_titles.append(title)
        return "sheet-123", "https://docs.google.com/spreadsheets/d/sheet-123"

    def write_report(self, spreadsheet_id: str, snapshot: ReportSnapshot) -> str:
        assert spreadsheet_id == "sheet-123"
        if self.fail:
            raise OSError("network unavailable")
        self.snapshots.append(snapshot)
        return "https://docs.google.com/spreadsheets/d/sheet-123"


def credentials() -> Credentials:
    return Credentials(
        token="access-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=list(DEFAULT_SCOPES),
        expiry=datetime.now(UTC) + timedelta(hours=1),
    )


def config(tmp_path: Path, *, sheet_id: str | None = None) -> AppConfig:
    return AppConfig(root_folder=tmp_path, google_sheet_id=sheet_id)


def expense(
    transaction_date: date,
    *,
    amount_minor: int = 10_00,
    currency: str = "USD",
    category: str = "groceries",
    merchant: str = "Market",
    tax_minor: int = 0,
    tip_minor: int = 0,
) -> ManualExpenseDraft:
    return ManualExpenseDraft(
        transaction_date=transaction_date,
        description="Rice",
        category_internal_name=category,
        amount_minor=amount_minor,
        currency=currency,
        merchant=merchant,
        tax_minor=tax_minor,
        tip_minor=tip_minor,
    )


def connected_auth() -> GoogleOAuthManager:
    store = MemoryCredentialStore(credentials().to_json())
    return GoogleOAuthManager(store=store)


def test_oauth_connect_and_disconnect_uses_secure_store(tmp_path: Path) -> None:
    client = tmp_path / "client.json"
    client.write_text("{}", encoding="utf-8")
    store = MemoryCredentialStore()
    expected = credentials()
    manager = GoogleOAuthManager(
        store=store,
        flow_factory=lambda path, scopes: FakeFlow(expected),
    )

    result = manager.connect(client)

    assert result.token == "access-token"
    assert store.value is not None
    assert json.loads(store.value)["refresh_token"] == "refresh-token"
    assert manager.credentials() is not None
    manager.disconnect()
    assert store.value is None


def test_report_builder_produces_all_required_sheets_and_stable_ids(
    database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 7, 12, 0)
    with session_scope(database_engine) as session:
        receipt = ManualExpenseService(session).create(
            expense(date(2026, 8, 6), tax_minor=125, tip_minor=75)
        )
        ManualExpenseService(session).create(
            expense(date(2026, 7, 1), amount_minor=500, currency="EUR")
        )
        snapshot = ReportBuilder(session, now=now).build(
            selected_month="2026-08", selected_currency="USD"
        )

        assert tuple(table.name for table in snapshot.tables) == SHEET_NAMES
        assert snapshot.selected_currency == "USD"
        item_ids = {row[0] for row in snapshot.table("Items").rows}
        assert str(receipt.line_items[0].item_uuid) in item_ids
        assert f"{receipt.receipt_uuid}:tax" in item_ids
        assert f"{receipt.receipt_uuid}:tips" in item_ids
        assert len(snapshot.dashboard_charts) == 3
        assert snapshot.dashboard_charts[0].chart_type == "PIE"


def test_summaries_do_not_combine_currencies(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        ManualExpenseService(session).create(expense(date(2026, 8, 1), amount_minor=1000))
        ManualExpenseService(session).create(
            expense(date(2026, 8, 2), amount_minor=2000, currency="EUR")
        )
        table = ReportBuilder(session).build().table("Monthly Summary")

        totals = {(row[0], row[1]): row[5] for row in table.rows}
        assert totals[("2026-08", "USD")] == 10.0
        assert totals[("2026-08", "EUR")] == 20.0


def test_budget_and_dashboard_values_are_calculated_locally(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        ManualExpenseService(session).create(expense(date(2026, 8, 1), amount_minor=8000))
        BudgetService(session).set_budget(
            BudgetDraft(year=2026, month=8, currency="USD", amount_minor=10_000)
        )
        snapshot = ReportBuilder(session).build(selected_month="2026-08", selected_currency="USD")

        budget = snapshot.table("Budgets").rows[0]
        metrics = {row[0]: row[1] for row in snapshot.table("Dashboard").rows if row[0]}
        assert budget[5:9] == (100.0, 80.0, 20.0, 80.0)
        assert metrics["Total Spending"] == 80.0
        assert metrics["Percentage of Budget Used"] == 80.0


def test_empty_report_is_valid(database_engine: Engine) -> None:
    with session_scope(database_engine) as session:
        snapshot = ReportBuilder(session, now=datetime(2026, 8, 7)).build()

        assert snapshot.selected_month == "2026-08"
        assert snapshot.table("Items").rows == ()
        assert snapshot.table("Receipts").rows == ()
        assert snapshot.table("Dashboard").rows


def test_create_report_rebuilds_and_persists_nonsecret_metadata(
    database_engine: Engine, tmp_path: Path
) -> None:
    gateway = FakeGateway()
    with session_scope(database_engine) as session:
        ManualExpenseService(session).create(expense(date(2026, 8, 1)))
        service = ReportSyncService(
            session,
            config(tmp_path),
            auth=connected_auth(),
            gateway_factory=lambda _: cast(SheetsGateway, gateway),
            now=lambda: datetime(2026, 8, 7, 12, 0),
        )

        result = service.create_report("Household Spending")

        assert result.state is SyncState.SYNCED
        assert result.spreadsheet_id == "sheet-123"
        assert gateway.created_titles == ["Household Spending"]
        assert len(gateway.snapshots) == 1
        assert service.settings.get(LAST_SYNC_SETTING) == "2026-08-07T12:00:00"
        queue = session.scalar(select(SyncQueueRecord))
        assert queue is not None and queue.status == "synced"


def test_pending_sync_is_idempotent_and_marks_queue_synced(
    database_engine: Engine, tmp_path: Path
) -> None:
    gateway = FakeGateway()
    with session_scope(database_engine) as session:
        receipt = ManualExpenseService(session).create(expense(date(2026, 8, 1)))
        service = ReportSyncService(
            session,
            config(tmp_path, sheet_id="sheet-123"),
            auth=connected_auth(),
            gateway_factory=lambda _: cast(SheetsGateway, gateway),
        )

        result = service.sync_pending()
        second = service.sync_pending()

        assert result.state is SyncState.SYNCED and result.synced == 1
        assert second.state is SyncState.SYNCED and second.attempted == 0
        assert len(gateway.snapshots) == 1
        queue = session.scalar(
            select(SyncQueueRecord).where(SyncQueueRecord.entity_id == receipt.receipt_uuid)
        )
        assert queue is not None and queue.status == "synced"


def test_offline_failure_is_retryable(database_engine: Engine, tmp_path: Path) -> None:
    gateway = FakeGateway(fail=True)
    with session_scope(database_engine) as session:
        ManualExpenseService(session).create(expense(date(2026, 8, 1)))
        service = ReportSyncService(
            session,
            config(tmp_path, sheet_id="sheet-123"),
            auth=connected_auth(),
            gateway_factory=lambda _: cast(SheetsGateway, gateway),
        )

        failed = service.sync_pending()
        gateway.fail = False
        retried = service.sync_pending()

        assert failed.state is SyncState.FAILED and failed.error == "network unavailable"
        assert retried.state is SyncState.SYNCED and retried.synced == 1


def test_disconnected_sync_leaves_pending_work_untouched(
    database_engine: Engine, tmp_path: Path
) -> None:
    with session_scope(database_engine) as session:
        receipt = ManualExpenseService(session).create(expense(date(2026, 8, 1)))
        service = ReportSyncService(
            session,
            config(tmp_path, sheet_id="sheet-123"),
            auth=GoogleOAuthManager(store=MemoryCredentialStore()),
        )

        result = service.sync_pending()

        assert result.state is SyncState.DISCONNECTED
        queue = session.scalar(
            select(SyncQueueRecord).where(SyncQueueRecord.entity_id == receipt.receipt_uuid)
        )
        assert queue is not None and queue.status == "pending"
