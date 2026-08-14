"""Google OAuth with refresh tokens delegated to the operating-system keyring."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

from spendscope.branding import APP_ID

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DEFAULT_SCOPES = (DRIVE_FILE_SCOPE,)


def bundled_client_secrets() -> Path | None:
    """Return the publisher-provided desktop OAuth configuration when bundled."""
    candidate = Path(__file__).with_name("google_oauth_client.json")
    return candidate if candidate.is_file() else None


class CredentialStore(Protocol):
    def get(self) -> str | None: ...

    def set(self, token_json: str) -> None: ...

    def delete(self) -> None: ...


class KeyringCredentialStore:
    """Keep OAuth token material out of SQLite and configuration files."""

    def __init__(self, *, service_name: str = APP_ID, username: str = "google-oauth") -> None:
        self.service_name = service_name
        self.username = username

    def get(self) -> str | None:
        import keyring

        return keyring.get_password(self.service_name, self.username)

    def set(self, token_json: str) -> None:
        import keyring

        keyring.set_password(self.service_name, self.username, token_json)

    def delete(self) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        with suppress(PasswordDeleteError):
            keyring.delete_password(self.service_name, self.username)


class GoogleOAuthManager:
    """Authorize, refresh, reconnect, and disconnect an app-scoped Google account."""

    def __init__(
        self,
        store: CredentialStore | None = None,
        *,
        scopes: tuple[str, ...] = DEFAULT_SCOPES,
        flow_factory: Callable[[Path, tuple[str, ...]], object] | None = None,
    ) -> None:
        self.store = store or KeyringCredentialStore()
        self.scopes = scopes
        self._flow_factory = flow_factory or self._default_flow

    @staticmethod
    def _default_flow(client_secrets: Path, scopes: tuple[str, ...]) -> object:
        return InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes=list(scopes))

    def connect(self, client_secrets: Path) -> Credentials:
        path = client_secrets.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Google OAuth client configuration not found: {path}")
        flow = self._flow_factory(path, self.scopes)
        credentials = cast(Credentials, flow.run_local_server(port=0))  # type: ignore[attr-defined]
        self._save(credentials)
        return credentials

    def credentials(self) -> Credentials | None:
        token_json = self.store.get()
        if not token_json:
            return None
        payload = json.loads(token_json)
        credentials = cast(
            Credentials,
            Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
                payload, scopes=list(self.scopes)
            ),
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())  # type: ignore[no-untyped-call]
            self._save(credentials)
        if not credentials.valid:
            return None
        return credentials

    def disconnect(self) -> None:
        self.store.delete()

    def is_connected(self) -> bool:
        return self.credentials() is not None

    def _save(self, credentials: Credentials) -> None:
        self.store.set(credentials.to_json())  # type: ignore[no-untyped-call]
