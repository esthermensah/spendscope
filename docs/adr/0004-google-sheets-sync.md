# ADR 0004: Google Sheets synchronization is optional and queued

**Status:** Proposed

Google Sheets reporting is optional. Confirmed local changes are persisted before a sync queue record is created. Sync uses stable IDs and idempotent upserts, with retry metadata for offline or API failures. Receipt files are never accessed through Google Drive APIs.
