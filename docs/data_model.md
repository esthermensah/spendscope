# Data model

## Modeling principles

- SQLite is authoritative; reports are derived projections.
- Monetary values are stored as integer minor units with an explicit ISO 4217 currency code. No conversion is performed.
- A receipt is context for its items, not a blanket category. Categories apply to line items and manual expenses.
- Tax, tip, discount, adjustment, and unallocated remainder remain separately identifiable.
- Records use stable UUIDs for synchronization.

## Core entities

| Entity | Purpose | Key fields |
| --- | --- | --- |
| `Category` | User-editable category taxonomy. | `id`, `name`, `parent_id`, `active`, `sort_order` |
| `Merchant` | Normalized merchant context. | `id`, `display_name`, `normalized_name` |
| `Receipt` | Imported document or manual receipt header. | `id`, `merchant_id`, `transaction_date`, `currency`, totals, `status`, `confidence` |
| `LineItem` | Independently categorized purchased/refunded item. | `id`, `receipt_id`, descriptions, `category_id`, `amount_minor`, `quantity`, `confidence`, `kind` |
| `SourceFile` | Local document provenance and archival state. | `id`, `receipt_id`, `sha256`, paths, `mime_type`, `size_bytes`, `retention_action` |
| `Budget` | Optional monthly cap scoped to category/currency. | `id`, `category_id`, `currency`, `month`, `amount_minor`, `warning_percent` |
| `CorrectionRule` | User-confirmed normalization/category memory. | `id`, `match_type`, `match_value`, `category_id`, `merchant_id` |
| `ReviewCase` | Work required before confirmation. | `id`, `receipt_id`, `reason`, `severity`, `status` |
| `SyncQueueItem` | Durable optional reporting work. | `id`, `entity_type`, `entity_id`, `operation`, `attempt_count`, `status`, `last_error` |
| `AppSetting` | Non-secret local settings. | `key`, `value_json`, `updated_at` |

## Relationships

```text
Merchant 1 ── * Receipt 1 ── * LineItem * ── 1 Category
                    │
                    ├── * SourceFile
                    ├── * ReviewCase
                    └── * SyncQueueItem
Category 1 ── * Budget
Category/Merchant 1 ── * CorrectionRule
```

## Reconciliation and integrity

`Receipt.status` transitions: `discovered → processing → confirmed`, `needs_review`, `duplicate`, or `failed`. A correction creates fresh synchronization queue work and audit entries.

`sum(item amounts) + tax + tip - discount + adjustments = total`

Any difference becomes a visible `unallocated` line item or requires review. Refunds use negative amounts. Receipt-level tax and tip never become merchant/category spending.

Required integrity rules: unique source file SHA-256; unique nullable receipt fingerprint; indexes by date/currency/status and category; unique category/currency/month budget; enabled SQLite foreign keys.

## Audit and privacy

Store correction and review events with record IDs, timestamps, and action names only. Extracted text is an optional local artifact subject to retention policy. Never store OAuth tokens, card information, or full receipt contents in logs.
