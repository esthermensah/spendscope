from pathlib import Path

import pytest
from pydantic import ValidationError

from spendscope.config import (
    AppConfig,
    Appearance,
    ConfidenceThresholds,
    FolderNames,
    load_config,
    save_config,
)


def test_configuration_normalizes_currency_and_builds_paths(tmp_path: Path) -> None:
    config = AppConfig(root_folder=tmp_path / "workspace", default_currency=" usd ")

    assert config.default_currency == "USD"
    assert config.database_path == (tmp_path / "workspace" / "Data" / "expenses.db").resolve()
    assert config.directory_paths()["logs"].name == "logs"
    assert (
        config.directory_paths()["inbox"]
        == (tmp_path / "workspace" / "Receipts" / "Inbox").resolve()
    )


@pytest.mark.parametrize("currency", ["US", "123", "USDD"])
def test_configuration_rejects_invalid_currency(tmp_path: Path, currency: str) -> None:
    with pytest.raises(ValidationError):
        AppConfig(root_folder=tmp_path, default_currency=currency)


@pytest.mark.parametrize("folder", ["../outside", "/absolute", "", "."])
def test_folder_names_prevent_traversal(folder: str) -> None:
    with pytest.raises(ValidationError):
        FolderNames(inbox=folder)


def test_folder_names_are_unique() -> None:
    with pytest.raises(ValidationError):
        FolderNames(inbox="Receipts", archive="receipts")


def test_confidence_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        ConfidenceThresholds(high=0.6, medium=0.7)


def test_sync_requires_sheet_id(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        AppConfig(root_folder=tmp_path, sync_enabled=True)


def test_configuration_round_trip(tmp_path: Path) -> None:
    source = AppConfig(
        root_folder=tmp_path / "workspace",
        default_currency="GBP",
        appearance=Appearance.DARK,
    )
    destination = tmp_path / "settings.json"

    save_config(source, destination)
    loaded = load_config(destination)

    assert loaded == source
    assert loaded.appearance is Appearance.DARK
    assert destination.read_text(encoding="utf-8").endswith("\n")
