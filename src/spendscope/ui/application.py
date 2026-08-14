"""Desktop application entry point."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QDialog

from spendscope.app import initialize_configured_workspace
from spendscope.branding import APP_ID, PRODUCT_NAME, VERSION
from spendscope.config import AppConfig, Appearance, load_config, save_config
from spendscope.ui.controller import DesktopController
from spendscope.ui.main_window import MainWindow
from spendscope.ui.setup_wizard import SetupWizard
from spendscope.ui.theme import enable_system_theme


def default_config_path() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(location) / "settings.json"


def _use_local_database(config: AppConfig, config_path: Path) -> AppConfig:
    """Keep SQLite local even when receipt files live in a cloud-synced folder."""
    if config.local_database_path is not None:
        return config
    old_database = config.database_path
    local_database = config_path.parent / "Data" / "expenses.db"
    local_database.parent.mkdir(parents=True, exist_ok=True)
    if old_database.exists() and not local_database.exists():
        shutil.copy2(old_database, local_database)
    localized = config.model_copy(update={"local_database_path": local_database.resolve()})
    save_config(localized, config_path)
    return localized


def create_window(config_path: Path) -> MainWindow | None:
    if config_path.exists():
        config = initialize_configured_workspace(load_config(config_path))
        config = _use_local_database(config, config_path)
    else:
        wizard = SetupWizard(config_path)
        if wizard.exec() != QDialog.DialogCode.Accepted or wizard.result_config is None:
            return None
        config = _use_local_database(wizard.result_config, config_path)
    return MainWindow(DesktopController(config, config_path))


def run_packaged_smoke_test(application: QApplication) -> int:
    """Exercise bundled Qt, migrations, and window construction without persistent data."""
    with TemporaryDirectory(prefix="spendscope-smoke-") as temporary:
        root = Path(temporary) / "workspace"
        config = initialize_configured_workspace(AppConfig(root_folder=root))
        config_path = root / "settings.json"
        save_config(config, config_path)
        window = create_window(config_path)
        if window is None:
            raise RuntimeError("packaged smoke test could not create the main window")
        window.show()
        application.processEvents()
        window._set_appearance(Appearance.DARK)
        if application.property("spendscopeTheme") != Appearance.DARK.value:
            raise RuntimeError("dark appearance could not be applied")
        window._set_appearance(Appearance.LIGHT)
        if load_config(config_path).appearance is not Appearance.LIGHT:
            raise RuntimeError("appearance preference was not saved")
        window.close()
    print(f"{PRODUCT_NAME} {VERSION} packaged smoke test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the SpendScope desktop application")
    parser.add_argument("--config", type=Path, help="Path to a SpendScope settings file")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)
    application = cast(QApplication | None, QApplication.instance()) or QApplication(sys.argv[:1])
    application.setApplicationName(PRODUCT_NAME)
    application.setApplicationVersion(VERSION)
    application.setOrganizationName(PRODUCT_NAME)
    application.setOrganizationDomain(APP_ID)
    enable_system_theme(application)
    if args.smoke_test:
        return run_packaged_smoke_test(application)
    window = create_window(args.config or default_config_path())
    if window is None:
        return 0
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
