# SpendScope

SpendScope is a local-first desktop application for item-level receipt and expense tracking. It stores financial data locally, supports offline workflows, and can optionally synchronize reporting data to Google Sheets.

## Download the beta

Open the repository's [Releases page](https://github.com/esthermensah/spendscope/releases) and
download the ZIP for your computer. On macOS, unzip
`SpendScope-macOS-ARM64.zip`, move `SpendScope.app` to Applications, then Control-click the app and
choose **Open** the first time. On Windows, unzip `SpendScope-Windows-X64.zip` and open
`SpendScope.exe` inside the SpendScope folder.

These beta builds are not yet signed or notarized. Receipt OCR also requires Tesseract to be
installed separately; manual expenses, budgets, local storage, and Google reporting remain
available without it. The source code remains available through **Code → Download ZIP** for
developers who prefer to run it directly.

The project currently includes its architecture, application foundation, and local receipt storage
pipeline: validated configuration, centralized branding, privacy-conscious logging, domain models,
SQLite migrations, secure Inbox scanning, exact duplicate detection, collision-safe archiving,
review-file handling, image compression, retention controls, and storage usage reporting. Local image
OCR adapters, direct and scanned-PDF extraction, receipt-field parsing, item extraction, and total
reconciliation are also available without remote processing. Deterministic item categorization,
mixed-category allocation, merchant and item normalization, persistent correction rules, confidence
routing, receipt fingerprinting, and explicit Unallocated handling are included in the local engine.
SQLite-backed services now orchestrate receipt processing and review, manual expenses, refunds,
monthly budgets, threshold warnings, offline synchronization work, and CSV/JSON exports.
The optional reporting layer uses Sheets-only Google OAuth, stores refresh tokens in the operating
system credential manager, maintains one ten-sheet report workbook, calculates dashboard and summary
data locally, and synchronizes the durable offline queue with stable IDs and idempotent rebuilds.
The native desktop interface provides first-run setup, a spending dashboard, background receipt
processing, receipt review with source previews, manual expense and refund entry, monthly budgets,
storage controls, and application settings.

## Development setup

SpendScope requires Python 3.11 or newer.

```shell
python -m venv .venv
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
mypy src
```

Initialize a local development workspace with:

```shell
spendscope init /path/to/local/workspace --currency USD
```

Launch the desktop application with:

```shell
spendscope-desktop
```

Use **Import receipt files** or drag JPG, JPEG, PNG, and PDF receipts onto the dashboard. SpendScope
copies validated files into its private Inbox and processes them locally. A completion summary shows
which receipts were confirmed, need review, were duplicates, or failed validation. In **Review
receipts**, compare the source preview with the extracted merchant, date, totals, and line items;
correct descriptions, amounts, and categories; reconcile the totals; then confirm or reject the
receipt. Confirmed changes appear on the dashboard immediately.

The first launch asks where to keep the private local workspace. For development and
troubleshooting, an existing settings file can be opened directly with
`spendscope-desktop --config /path/to/settings.json`.

See `docs/` for the system design, data model, architecture decisions, and delivery plan.
Google Cloud setup for contributors is documented in
[`docs/google_sheets_setup.md`](docs/google_sheets_setup.md).
Development application bundles and the unsigned release process are documented in
[`docs/packaging.md`](docs/packaging.md).

## License

SpendScope is open-source software licensed under the [Apache License 2.0](LICENSE).
