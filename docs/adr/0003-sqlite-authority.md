# ADR 0003: SQLite is the system of record

**Status:** Proposed

All product data is stored in a local SQLite database using migrations and transactional repositories. Google Sheets is a derived reporting view updated through a durable queue. This preserves offline functionality and makes reports rebuildable.
