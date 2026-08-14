"""Application bootstrap services shared by the desktop interface and CLI."""

from __future__ import annotations

import shutil
from pathlib import Path

from spendscope.config import AppConfig, save_config
from spendscope.database.connection import create_sqlite_engine, session_scope
from spendscope.database.migrations import migrate_database
from spendscope.database.repositories import CategoryRepository, SettingsRepository
from spendscope.logging_config import configure_logging
from spendscope.utilities.paths import collision_safe_path


def _migrate_legacy_receipt_folders(config: AppConfig) -> dict[Path, Path]:
    """Move pre-0.2 receipt folders into the Receipts library without overwriting files."""
    paths = config.directory_paths()
    moved: dict[Path, Path] = {}
    for name in ("inbox", "needs_review", "archive"):
        legacy = config.root_folder / getattr(config.folders, name)
        destination = paths[name]
        if not legacy.is_dir() or legacy.resolve() == destination.resolve():
            continue
        destination.mkdir(parents=True, exist_ok=True)
        for source in sorted(legacy.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(legacy)
            target_directory = destination / relative.parent
            target_directory.mkdir(parents=True, exist_ok=True)
            target = collision_safe_path(target_directory, source.name)
            old_path = source.resolve()
            shutil.move(str(source), target)
            moved[old_path] = target.resolve()
        for directory in sorted(
            (item for item in legacy.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            directory.rmdir()
        legacy.rmdir()
    return moved


def _update_migrated_database_paths(config: AppConfig, moved: dict[Path, Path]) -> None:
    if not moved or not config.database_path.exists():
        return
    engine = create_sqlite_engine(config.database_path)
    try:
        with engine.begin() as connection:
            for old, new in moved.items():
                values = {"old": str(old), "new": str(new)}
                connection.exec_driver_sql(
                    "UPDATE processed_files SET original_path = :new WHERE original_path = :old",
                    values,
                )
                connection.exec_driver_sql(
                    "UPDATE processed_files SET archive_path = :new WHERE archive_path = :old",
                    values,
                )
                connection.exec_driver_sql(
                    "UPDATE receipts SET source_file_original_path = :new "
                    "WHERE source_file_original_path = :old",
                    values,
                )
                connection.exec_driver_sql(
                    "UPDATE receipts SET source_file_archive_path = :new "
                    "WHERE source_file_archive_path = :old",
                    values,
                )
    finally:
        engine.dispose()


def initialize_workspace(root_folder: Path, *, currency: str = "USD") -> AppConfig:
    config = AppConfig(root_folder=root_folder, default_currency=currency)
    return initialize_configured_workspace(config)


def initialize_configured_workspace(config: AppConfig) -> AppConfig:
    """Create a workspace from a fully validated desktop configuration."""
    moved_receipts = _migrate_legacy_receipt_folders(config)
    paths = config.directory_paths()
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    save_config(config, paths["config"] / "settings.json")
    configure_logging(paths["logs"])
    migrate_database(config.database_path)
    _update_migrated_database_paths(config, moved_receipts)

    engine = create_sqlite_engine(config.database_path)
    with session_scope(engine) as session:
        CategoryRepository(session).seed_defaults()
        SettingsRepository(session).set_many(
            (
                ("default_currency", config.default_currency),
                ("retention_policy", config.retention_policy.value),
                ("schema_initialized", True),
            )
        )
    engine.dispose()
    return config
