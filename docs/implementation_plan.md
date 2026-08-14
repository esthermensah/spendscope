# Implementation plan

## Repository assessment

The repository is an empty Git workspace. There is no runtime, package definition, test suite, documentation, or CI configuration. This makes the proposed layered structure low-risk to establish, but all technology and product choices remain unvalidated.

## Phased delivery

1. **Foundation** — Python project, quality tooling, centralized branding/configuration/logging, domain types, SQLite migrations and repositories.
2. **File and storage** — folder setup, secure scanning, hashing, duplicate detection, archive/review handling, compression/retention, usage tests.
3. **Extraction and parsing** — local image/PDF adapters and deterministic receipt parsers with synthetic fixtures.
4. **Categorization and reconciliation** — category rules, correction memory, confidence scoring, mixed-category allocation, totals validation.
5. **Application services** — orchestration, manual entry, refunds, budgets, exports, offline synchronization queue.
6. **Sheets reporting** — OAuth, secure tokens, workbook writer, summaries, idempotent queue processing and mocked tests.
7. **Desktop UI** — setup, dashboard, review, manual entry, budgets, settings, storage controls, accessibility review.
8. **Packaging and release** — Windows/macOS packaging, dependency documentation, CI builds, signing guidance, user documentation.

## Phase 1 proposed files

- `pyproject.toml`, `.gitignore`, `.pre-commit-config.yaml`
- `src/spendscope/{__init__,branding,config,logging_config}.py`
- `src/spendscope/domain/{enums,models}.py`
- `src/spendscope/database/{connection,schema,migrations,repositories}.py`
- Unit tests for configuration, models, and repositories
- Migration integration test and a GitHub Actions test workflow

## Phase 1 checklist

- [ ] Establish `src/` layout and Python 3.11 support policy.
- [ ] Centralize product name, application identifiers, and directory defaults.
- [ ] Add validated configuration and safe default folder naming.
- [ ] Configure structured, redacted local logging.
- [ ] Define money, currency, record-status, and confidence domain types.
- [ ] Create initial SQLite migration with foreign keys and required indexes.
- [ ] Implement transaction-aware repository interfaces for categories, settings, receipts, and line items.
- [ ] Add unit/integration tests using temporary SQLite databases and synthetic data.
- [ ] Add Ruff, MyPy, Pytest, coverage threshold, and pre-commit configuration.
- [ ] Add CI that runs lint, type checks, and tests on supported Python versions.

## Technical and product risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Variable receipt layouts/OCR quality | Incorrect items and totals | Confidence tiers, review workflow, original files, synthetic regression fixtures. |
| Bundling Tesseract/PDF rendering | Platform-specific setup complexity | Prototype packaged builds early; document fallback and licenses. |
| Item-level categorization ambiguity | Misleading reports | Deterministic rules, visible confidence, correction memory, unallocated remainder. |
| Google Sheets quotas/schema drift | Incomplete reporting | SQLite authority, durable queue, stable IDs, idempotent writes, rebuild capability. |
| Large/malformed documents | Resource exhaustion | File/page/size limits, timeouts, isolated processing, validation before render. |
| SQLite concurrent access | Locking/data loss | Application-owned connection policy, short transactions, backups, WAL evaluation. |

## Privacy and security risks

- Receipt files contain personal and financial data; keep them local and provide explicit retention controls.
- OCR text and logs can expose private details; redact logs and make extracted-text retention configurable.
- OAuth credentials require OS credential storage and revocation/disconnection support.
- File imports need canonical path checks, allowlists, safe temporary files, size limits, and no content execution.
- SQL must remain parameterized and migrations reviewed; encrypted disk is a user/system responsibility unless app-level encryption is approved.

## Owner decisions required

1. **License:** choose a permissive license (recommended: Apache-2.0) or a copyleft license before public release.
2. **OCR distribution:** bundle Tesseract with packaged apps, provide guided installation, or use a different local engine.
3. **Database stack:** approve SQLAlchemy/Alembic or prefer a lighter `sqlite3`-only persistence layer.
4. **Google OAuth:** provide an owner-managed Google Cloud OAuth client and publish required privacy/support information.
5. **Retention default:** confirm archive/compression policy and whether extracted text is retained at all.
6. **Currency behavior:** confirm default currencies and minor-unit treatment for zero/three-decimal currencies.
7. **Accessibility target:** confirm minimum OS versions and assistive-technology support matrix.
