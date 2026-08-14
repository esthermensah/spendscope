"""Add durable local application service tables.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS review_cases (
            id INTEGER PRIMARY KEY,
            receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            severity VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            resolved_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_cases_status_created "
        "ON review_cases(status, created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_expense_details (
            id INTEGER PRIMARY KEY,
            receipt_id INTEGER NOT NULL UNIQUE REFERENCES receipts(id) ON DELETE CASCADE,
            note TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS refund_links (
            id INTEGER PRIMARY KEY,
            refund_receipt_id INTEGER NOT NULL UNIQUE REFERENCES receipts(id) ON DELETE CASCADE,
            original_receipt_id INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
            refund_line_item_id INTEGER NOT NULL REFERENCES line_items(id) ON DELETE CASCADE,
            original_line_item_id INTEGER REFERENCES line_items(id) ON DELETE SET NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY,
            entity_type VARCHAR(50) NOT NULL,
            entity_id VARCHAR(64) NOT NULL,
            action VARCHAR(80) NOT NULL,
            details_json TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_events_entity_created "
        "ON audit_events(entity_type, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_events")
    op.execute("DROP TABLE IF EXISTS refund_links")
    op.execute("DROP TABLE IF EXISTS manual_expense_details")
    op.execute("DROP TABLE IF EXISTS review_cases")
