"""Idempotent Google Sheets synchronization backed by the durable local queue."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from spendscope.branding import DEFAULT_REPORT_TITLE
from spendscope.config import AppConfig
from spendscope.database.repositories import SettingsRepository
from spendscope.database.schema import SyncQueueRecord
from spendscope.database.service_repositories import AuditRepository
from spendscope.domain.enums import SyncStatus
from spendscope.reporting.google_auth import GoogleOAuthManager
from spendscope.reporting.google_sheets import SheetsGateway, gateway_for
from spendscope.reporting.models import SyncResult, SyncState
from spendscope.reporting.summaries import ReportBuilder
from spendscope.services.sync_queue import SyncQueueService

SHEET_ID_SETTING = "reporting.google_sheet_id"
SHEET_URL_SETTING = "reporting.google_sheet_url"
LAST_SYNC_SETTING = "reporting.last_successful_sync"


class ReportSyncService:
    """Coordinate authorization, report creation, queue sync, and rebuilding."""

    def __init__(
        self,
        session: Session,
        config: AppConfig,
        *,
        auth: GoogleOAuthManager | None = None,
        gateway_factory: Callable[[Credentials], SheetsGateway] = gateway_for,
        now: Callable[[], datetime] = datetime.now,
        max_retries: int = 5,
    ) -> None:
        self.session = session
        self.config = config
        self.auth = auth or GoogleOAuthManager()
        self.gateway_factory = gateway_factory
        self.now = now
        self.max_retries = max_retries
        self.settings = SettingsRepository(session)
        self.queue = SyncQueueService(session)
        self.audit = AuditRepository(session)

    def connect_account(self, client_secrets: Path) -> SyncResult:
        credentials = self.auth.connect(client_secrets)
        self.audit.record("report", "google", "account_connected")
        return SyncResult(
            state=SyncState.READY if credentials.valid else SyncState.FAILED,
            spreadsheet_id=self.spreadsheet_id,
            spreadsheet_url=self.spreadsheet_url,
        )

    def disconnect_account(self) -> SyncResult:
        self.auth.disconnect()
        self.audit.record("report", "google", "account_disconnected")
        return SyncResult(
            state=SyncState.DISCONNECTED,
            spreadsheet_id=self.spreadsheet_id,
            spreadsheet_url=self.spreadsheet_url,
        )

    def create_report(self, title: str | None = None) -> SyncResult:
        credentials = self._credentials()
        if credentials is None:
            return self._disconnected()
        gateway = self.gateway_factory(credentials)
        spreadsheet_id, spreadsheet_url = gateway.create_workbook(
            (title or self.config.report_title or DEFAULT_REPORT_TITLE).strip()
        )
        self.settings.set_many(
            ((SHEET_ID_SETTING, spreadsheet_id), (SHEET_URL_SETTING, spreadsheet_url))
        )
        self.audit.record("report", spreadsheet_id, "created")
        return self.rebuild_report()

    def sync_pending(self, *, limit: int = 100) -> SyncResult:
        records = self._retryable(limit)
        if not records:
            return self.get_sync_status()
        return self._write(records)

    def rebuild_report(self) -> SyncResult:
        return self._write(self._queued_for_rebuild(), force=True)

    def get_sync_status(self) -> SyncResult:
        failed = self.session.scalar(
            select(SyncQueueRecord)
            .where(SyncQueueRecord.status == SyncStatus.FAILED.value)
            .limit(1)
        )
        pending = self.session.scalar(
            select(SyncQueueRecord)
            .where(SyncQueueRecord.status.in_((SyncStatus.PENDING.value, SyncStatus.SYNCING.value)))
            .limit(1)
        )
        if not self.auth.is_connected():
            state = SyncState.DISCONNECTED
        elif failed is not None:
            state = SyncState.FAILED
        elif pending is not None:
            state = SyncState.READY
        elif self.settings.get(LAST_SYNC_SETTING) is not None:
            state = SyncState.SYNCED
        else:
            state = SyncState.READY
        return SyncResult(
            state=state,
            spreadsheet_id=self.spreadsheet_id,
            spreadsheet_url=self.spreadsheet_url,
        )

    @property
    def spreadsheet_id(self) -> str | None:
        value = self.settings.get(SHEET_ID_SETTING, self.config.google_sheet_id)
        return value if isinstance(value, str) and value else None

    @property
    def spreadsheet_url(self) -> str | None:
        value = self.settings.get(SHEET_URL_SETTING)
        if isinstance(value, str) and value:
            return value
        return (
            None
            if self.spreadsheet_id is None
            else f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}"
        )

    def _write(self, records: list[SyncQueueRecord], *, force: bool = False) -> SyncResult:
        credentials = self._credentials()
        spreadsheet_id = self.spreadsheet_id
        if credentials is None:
            return self._disconnected(attempted=len(records))
        if spreadsheet_id is None:
            return SyncResult(
                state=SyncState.FAILED,
                spreadsheet_id=None,
                spreadsheet_url=None,
                attempted=len(records),
                failed=len(records),
                error="No report workbook is configured",
            )
        if not force and not records:
            return self.get_sync_status()
        for record in records:
            if record.status == SyncStatus.FAILED.value:
                self.queue.retry(record)
            self.queue.mark_syncing(record)
        # Release the write lock before the comparatively slow Google API request.
        self.session.commit()
        try:
            last_sync = self.settings.get(LAST_SYNC_SETTING)
            snapshot = ReportBuilder(self.session, now=self.now()).build(
                last_successful_sync=last_sync if isinstance(last_sync, str) else None
            )
            url = self.gateway_factory(credentials).write_report(spreadsheet_id, snapshot)
            completed_at = self.now()
            self.settings.set_many(
                (
                    (SHEET_URL_SETTING, url),
                    (LAST_SYNC_SETTING, completed_at.isoformat()),
                )
            )
            for record in records:
                self.queue.mark_synced(record)
            self.audit.record(
                "report",
                spreadsheet_id,
                "rebuilt" if force else "synchronized",
                {"queue_records": len(records)},
            )
            return SyncResult(
                state=SyncState.SYNCED,
                spreadsheet_id=spreadsheet_id,
                spreadsheet_url=url,
                attempted=len(records),
                synced=len(records),
                completed_at=completed_at,
            )
        except Exception as error:
            message = self._safe_error(error)
            for record in records:
                self.queue.mark_failed(record, message)
            self.audit.record(
                "report", spreadsheet_id, "sync_failed", {"queue_records": len(records)}
            )
            return SyncResult(
                state=SyncState.FAILED,
                spreadsheet_id=spreadsheet_id,
                spreadsheet_url=self.spreadsheet_url,
                attempted=len(records),
                failed=len(records),
                error=message,
            )

    def _retryable(self, limit: int) -> list[SyncQueueRecord]:
        return list(
            self.session.scalars(
                select(SyncQueueRecord)
                .where(
                    SyncQueueRecord.status.in_((SyncStatus.PENDING.value, SyncStatus.FAILED.value)),
                    SyncQueueRecord.retry_count < self.max_retries,
                )
                .order_by(SyncQueueRecord.created_at, SyncQueueRecord.id)
                .limit(limit)
            )
        )

    def _queued_for_rebuild(self) -> list[SyncQueueRecord]:
        return list(
            self.session.scalars(
                select(SyncQueueRecord)
                .where(
                    SyncQueueRecord.status.in_((SyncStatus.PENDING.value, SyncStatus.FAILED.value))
                )
                .order_by(SyncQueueRecord.created_at, SyncQueueRecord.id)
            )
        )

    def _credentials(self) -> Credentials | None:
        try:
            return self.auth.credentials()
        except Exception:
            self.audit.record("report", "google", "authorization_failed")
            return None

    def _disconnected(self, *, attempted: int = 0) -> SyncResult:
        return SyncResult(
            state=SyncState.DISCONNECTED,
            spreadsheet_id=self.spreadsheet_id,
            spreadsheet_url=self.spreadsheet_url,
            attempted=attempted,
            error="Connect a Google account before synchronizing",
        )

    @staticmethod
    def _safe_error(error: Exception) -> str:
        message = str(error).strip() or error.__class__.__name__
        return message[:500]
