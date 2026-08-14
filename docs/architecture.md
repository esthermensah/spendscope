# Architecture

## Goals and boundaries

SpendScope is a Windows and macOS desktop application. SQLite is the authoritative local store. Receipt files remain in a user-selected local folder; synced folders are treated as ordinary filesystem locations. Extraction, parsing, categorization, budgeting, and review work without network access. Google Sheets is an optional reporting target, never a source of truth.

The system excludes bank connectivity, payment features, financial advice, remote OCR, cloud receipt storage, automatic currency conversion, and Google Drive file access.

## Recommended architecture

Use Python 3.11+ with PySide6 for the native desktop interface. Keep UI, domain, storage, processing, and reporting layers separate so the product can be tested without a running GUI and renamed through one branding module.

```text
PySide6 desktop UI
       │
Application services ── processing / review / budgets / exports
       │
Domain models and policies
       │
SQLite repositories ── local filesystem services ── extraction adapters
       │                         │                     │
 SQLite database            Inbox/Archive/Review     OCR/PDF libraries
       │
Synchronization queue ── optional Google Sheets adapter
```

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| `ui` | Setup flow, dashboard, review and correction, manual entries, settings, accessible status feedback. |
| `domain` | Typed entities, enums, invariants, money and currency rules. |
| `database` | Schema migrations, transactions, repositories, query projections. |
| `processing` | Inbox scanning, validation, hashing, duplicate checks, archive/review movement, pipeline orchestration. |
| `extraction` | Direct PDF text extraction, local OCR fallback, image preprocessing. |
| `parsing` | Merchant, date, total, tax, tip, discount, and line-item candidates. |
| `categorization` | Normalization, deterministic item rules, merchant tags, correction memory, confidence. |
| `budgeting` | Per-currency monthly budget comparisons and threshold status. |
| `reporting` | Local CSV/JSON exports, queued/idempotent Google Sheets synchronization. |
| `storage` | Compression, retention actions, and usage calculation. |

## Processing lifecycle

1. Scan the configured Inbox and validate an allowed file within the Inbox path.
2. Hash the file and reject previously processed hashes before extraction.
3. Extract text locally: direct text for PDFs first, then rendered-page/image OCR when needed.
4. Parse receipt data and line items, normalize descriptions, and categorize each item independently.
5. Reconcile line items, tax, tip, discount, and final total. Calculate confidence and duplicate fingerprint.
6. Save a confirmed record or a review record in a single SQLite transaction.
7. Move the file to Archive or Needs Review, queue a report sync, recalculate budget views, and record structured logs.

The pipeline must be restart-safe: persisted file hashes, receipt status, archive paths, and sync records prevent duplicate work.

## Local data and configuration

The setup wizard creates configurable Inbox, Archive, Needs Review, Data, Exports, Config, log, extracted-text, and backup folders below the selected root. Configuration is stored locally as JSON with non-secret settings only. OAuth refresh tokens belong in the OS credential store; the SQLite database contains only account and synchronization metadata.

## Google Sheets integration

Google Sheets synchronization is optional and asynchronous. On first connection, SpendScope uses the
per-file `drive.file` scope to create its visible Drive folder and place an app-owned workbook inside
it. Confirmed changes produce durable queue entries. The adapter uses stable record identifiers and
upserts to the workbook's prescribed reporting sheets. Failed operations stay queued with retry
metadata; receipt files and the SQLite database are never uploaded through Google APIs.

## Quality attributes

- Cross-platform paths use `pathlib`; no shell commands are required for normal use.
- All financial amounts use `Decimal`, integer minor units, and explicit ISO currency codes—never floats.
- Database changes use numbered migrations and transaction boundaries.
- Extraction adapters are replaceable and run only locally.
- UI work must remain responsive; long operations run off the GUI thread and send progress/status events.
- Logs exclude receipt text, full file paths, OAuth data, and sensitive financial details by default.

## Minimum dependency set

| Need | Dependency | Reason |
| --- | --- | --- |
| GUI | `PySide6` | Mature native desktop UI for Windows and macOS. |
| Models/settings | `pydantic` + `pydantic-settings` | Typed configuration and validation. |
| Database migrations | `SQLAlchemy` + `alembic` | Portable SQLite persistence with explicit migrations. |
| Image OCR | `Pillow` + `pytesseract` | Local image preparation and Tesseract bridge. |
| PDF handling | `pypdf` + `PyMuPDF` | Direct text extraction plus page rendering fallback. |
| Google Sheets | `google-auth-oauthlib` + `google-api-python-client` | Optional OAuth and Sheets API adapter. |
| Secure credentials | `keyring` | Platform credential storage. |
| Tests/tooling | `pytest`, `pytest-cov`, `ruff`, `mypy`, `pre-commit` | Quality baseline. |

Tesseract itself is a documented packaged/system dependency, not a Python-only substitute. Its final packaging approach requires owner approval.
