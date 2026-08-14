import sqlite3
from pathlib import Path

from alembic.config import Config
from sqlalchemy import Engine

from spendscope.app import initialize_configured_workspace, initialize_workspace
from spendscope.cli import main
from spendscope.config import AppConfig, load_config
from spendscope.database.migrations import migrate_database


def test_migration_creates_expected_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "expenses.db"
    migrate_database(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    assert {
        "alembic_version",
        "budgets",
        "audit_events",
        "categories",
        "item_rules",
        "line_items",
        "merchant_rules",
        "manual_expense_details",
        "processed_files",
        "refund_links",
        "receipts",
        "review_cases",
        "settings",
        "sync_queue",
    } <= tables
    assert foreign_keys == 0  # SQLite connection-local setting; application connections enable it.
    assert version == "0002"


def test_application_database_connections_enable_foreign_keys(database_engine: Engine) -> None:
    with database_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_phase_one_database_upgrades_to_local_service_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "existing.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES ('0001');
            CREATE TABLE receipts (id INTEGER PRIMARY KEY);
            CREATE TABLE line_items (id INTEGER PRIMARY KEY);
            """
        )

    migrate_database(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    assert {"audit_events", "manual_expense_details", "refund_links", "review_cases"} <= tables
    assert version == "0002"


def test_workspace_initialization_is_complete_and_repeatable(tmp_path: Path) -> None:
    root = tmp_path / "Spending Data"
    first = initialize_workspace(root, currency="eur")
    second = initialize_workspace(root, currency="EUR")

    assert first == second
    assert first.database_path.exists()
    assert all(path.exists() for path in first.directory_paths().values())
    assert load_config(root / "Config" / "settings.json").default_currency == "EUR"


def test_existing_receipt_folders_move_into_receipts_library(tmp_path: Path) -> None:
    root = tmp_path / "SpendScope"
    legacy_inbox = root / "Inbox"
    legacy_archive = root / "Archive" / "2026" / "08"
    legacy_inbox.mkdir(parents=True)
    legacy_archive.mkdir(parents=True)
    (legacy_inbox / "new.png").write_bytes(b"receipt")
    (legacy_archive / "saved.pdf").write_bytes(b"receipt")

    config = initialize_configured_workspace(AppConfig(root_folder=root))

    assert (config.directory_paths()["inbox"] / "new.png").read_bytes() == b"receipt"
    assert (config.directory_paths()["archive"] / "2026" / "08" / "saved.pdf").exists()
    assert not legacy_inbox.exists()
    assert not (root / "Archive").exists()


def test_cli_initializes_workspace(tmp_path: Path) -> None:
    root = tmp_path / "cli-workspace"
    assert main(["init", str(root), "--currency", "GBP"]) == 0
    assert (root / "Data" / "expenses.db").exists()


def test_alembic_configuration_uses_project_migrations() -> None:
    config = Config("alembic.ini")
    assert config.get_main_option("script_location").endswith("src/spendscope/database/migrations")
