"""Accessible first-run workspace setup dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from spendscope.app import initialize_configured_workspace
from spendscope.config import AppConfig, save_config


class SetupWizard(QDialog):
    def __init__(self, config_path: Path, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.config_path = config_path
        self.result_config: AppConfig | None = None
        self.setWindowTitle("Welcome to SpendScope")
        self.setMinimumWidth(560)
        intro = QLabel(
            "SpendScope creates and organizes everything for you. Your private receipt files and "
            "expense database stay in one workspace on this Mac. You can accept the suggested "
            "location or choose another folder."
        )
        intro.setWordWrap(True)
        self.root_edit = QLineEdit()
        self.root_edit.setAccessibleName("Workspace folder")
        documents = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        suggested = Path(documents) if documents else Path.home() / "Documents"
        self.root_edit.setText(str(suggested / "SpendScope"))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        root_row = QHBoxLayout()
        root_row.addWidget(self.root_edit)
        root_row.addWidget(browse)
        self.currency = QComboBox()
        self.currency.addItems(["USD", "CAD", "GBP", "EUR", "GHS"])
        form = QFormLayout()
        form.addRow("SpendScope workspace", root_row)
        form.addRow("Default currency", self.currency)
        note = QLabel(
            "On first save, SpendScope creates its receipt folders, local database, backups, and "
            "exports automatically. Nothing else needs to be prepared."
        )
        note.setObjectName("secondaryText")
        note.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose SpendScope workspace")
        if selected:
            self.root_edit.setText(selected)

    def _save(self) -> None:
        root = self.root_edit.text().strip()
        if not root:
            QMessageBox.warning(self, "Workspace required", "Choose a workspace folder.")
            self.root_edit.setFocus()
            return
        try:
            config = AppConfig(root_folder=Path(root), default_currency=self.currency.currentText())
            initialize_configured_workspace(config)
            save_config(config, self.config_path)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Setup could not be completed", str(error))
            return
        self.result_config = config
        self.accept()
