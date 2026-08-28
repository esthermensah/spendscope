# SpendScope

**A free, privacy-conscious desktop spending tracker that turns receipts into useful insights while
keeping you in control of your data.**

## Project case study
Read the [SpendScope solution-engineering case study](https://your-portfolio-site.com/projects/spendscope) to learn why I built it, the constraints I designed around, and the architecture behind the application.

SpendScope imports receipts and manually entered purchases, helps you review and categorize them,
and shows where your money is going. Your financial data stays on your computer by default, and an
optional Google connection can send your spending report to Google Sheets for access from another
device.

## Why I built it

I built SpendScope because I wanted three things that most spending apps did not give me:

- maximum control over my financial data;
- no subscription fee; and
- a desktop-first experience instead of another app constantly living on my phone.

SpendScope is free and open source. It works locally and offline, while still letting me use Google
Drive and Sheets when I want access from my phone or another device. The Google connection is
optional—the desktop app remains the main home for tracking and reviewing spending.

## How it works

1. Import a receipt image or PDF, or enter a purchase manually.
2. SpendScope reads the merchant, date, total, and individual items locally.
3. Review the result, correct anything that needs attention, and choose spending categories.
4. See the confirmed expense immediately in the dashboard, budgets, and category chart.
5. Optionally connect Google Drive to create and update a Google Sheets spending report.

## Download the unsigned beta

Open the repository's [Releases page](https://github.com/esthermensah/spendscope/releases) and
download the ZIP for your computer. Only download builds from this repository.

On macOS:

1. Unzip `SpendScope-macOS-ARM64.zip` and move `SpendScope.app` to Applications.
2. Try opening SpendScope once. macOS will warn that Apple cannot verify the developer.
3. Open **System Settings → Privacy & Security**, scroll to **Security**, and click **Open Anyway**.
4. Confirm **Open**. Enter your Mac login password if macOS requests it.

Apple documents this exception process in
[Open apps safely on your Mac](https://support.apple.com/102445). Because this portfolio beta is
not signed or notarized, macOS cannot confirm that Apple checked it for malicious software. Verify
that the ZIP came from this repository before choosing **Open Anyway**.

Windows packaging is included for contributors, but it has not been personally tested by the
project owner. If you try it, unzip `SpendScope-Windows-X64.zip` and open `SpendScope.exe` inside
the SpendScope folder. Windows may display a SmartScreen warning because the beta is not
code-signed; please report what you find in GitHub Issues.

These beta builds are intentionally unsigned and the Mac build is not Apple-notarized. Receipt OCR also requires Tesseract to be
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
