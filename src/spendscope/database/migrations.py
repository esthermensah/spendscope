"""Programmatic Alembic migration entry point."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def migrate_database(database_path: Path) -> None:
    config = Config()
    migrations = Path(__file__).with_name("migrations")
    config.set_main_option("script_location", str(migrations))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.expanduser().resolve()}")
    command.upgrade(config, "head")
