# Google Sheets developer setup

SpendScope uses Google OAuth only to create its visible Drive folder and optional report workbook.
Receipt files and local database contents are never uploaded. The requested scope is:

`https://www.googleapis.com/auth/drive.file`

This non-sensitive, per-file scope allows SpendScope to manage only files it creates or files a user
explicitly shares with it. It does not grant access to the rest of the user's Drive.

## Configure a development client

1. Create or select a Google Cloud project.
2. Enable the Google Sheets API and Google Drive API.
3. Configure the OAuth consent screen and add development test users while the app remains in test
   mode.
4. Create an OAuth client for a desktop application.
5. Download its JSON configuration to a private location outside the repository.
6. For a local developer build, place the downloaded file at
   `src/spendscope/reporting/google_oauth_client.json`. It is gitignored. A production package
   includes the publisher-managed file automatically, allowing ordinary users to use
   **Connect Google Drive** without choosing a file.

For GitHub release builds, store the complete JSON as the encrypted repository secret
`SPENDSCOPE_GOOGLE_OAUTH_CLIENT`. The packaging workflow writes it only into the temporary build
workspace before PyInstaller creates the application. Pull requests from forks continue to build
without the publisher configuration because repository secrets are not exposed to forked code.

Do not commit the downloaded client configuration. Never put access tokens, refresh tokens, account
identifiers, or spreadsheet contents in source control, logs, fixtures, or bug reports.

## Token, folder, and workbook behavior

- OAuth tokens are stored through the operating system credential store: Keychain on macOS and
  Credential Manager on Windows where supported.
- SQLite stores only non-secret report metadata such as the workbook ID, URL, and last successful
  synchronization time.
- The first connection creates or reuses an app-created `SpendScope` folder in My Drive, creates the
  spending report, moves the report into that folder, and builds its tables and charts.
- Disconnecting deletes the credential-store entry. Local processing and the pending synchronization
  queue continue to work while disconnected or offline.
- Reconnecting can resume updates to the existing workbook.
- Rebuilding replaces all report tables and charts from the authoritative SQLite data. Stable receipt
  and item IDs prevent duplicate rows.

## Production ownership

Release maintainers must provide an owner-managed desktop OAuth client, complete Google's
consent-screen requirements, publish the required privacy and support information, and rotate the
client if necessary. User access and refresh tokens remain in the operating-system credential store
and must never be bundled or committed.
