from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLineEdit, QPushButton, QWidget
from sqlalchemy import select

from spendscope.app import initialize_configured_workspace
from spendscope.config import AppConfig, Appearance, load_config, save_config
from spendscope.database.connection import session_scope
from spendscope.database.schema import ReceiptRecord
from spendscope.domain.enums import ReviewSeverity
from spendscope.domain.models import (
    BudgetDraft,
    ManualExpenseDraft,
    ReceiptCorrectionDraft,
    ReceiptItemCorrection,
)
from spendscope.services.review import ReviewService
from spendscope.ui.application import default_config_path
from spendscope.ui.controller import DesktopController
from spendscope.ui.dialogs import (
    CategoryManagerDialog,
    ManualEntryDialog,
    ReviewDialog,
    SettingsDialog,
    StorageDialog,
    format_bytes,
)
from spendscope.ui.main_window import FINANCIAL_PROMPTS, MainWindow
from spendscope.ui.setup_wizard import SetupWizard
from spendscope.ui.theme import THEMES, Theme, apply_appearance, apply_theme
from spendscope.ui.workers import BackgroundJob


@pytest.fixture(scope="module")
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop_controller(tmp_path: Path) -> DesktopController:
    config = initialize_configured_workspace(
        AppConfig(root_folder=tmp_path / "workspace", default_currency="USD")
    )
    config_path = tmp_path / "settings.json"
    save_config(config, config_path)
    controller = DesktopController(config, config_path)
    yield controller
    controller.close()


def test_controller_drives_dashboard_entries_and_budget(
    desktop_controller: DesktopController,
) -> None:
    initial = desktop_controller.dashboard(date(2026, 8, 7))
    assert initial.inbox_count == 0
    assert initial.review_count == 0
    assert initial.month_spending_minor == 0

    desktop_controller.create_manual(
        ManualExpenseDraft(
            transaction_date=date(2026, 8, 7),
            description="Coffee",
            category_internal_name="eating_out",
            amount_minor=650,
            currency="USD",
            merchant="Corner Cafe",
        )
    )
    desktop_controller.set_budget(
        BudgetDraft(year=2026, month=8, currency="USD", amount_minor=20_000)
    )

    snapshot = desktop_controller.dashboard(date(2026, 8, 7))
    assert snapshot.month_spending_minor == 650
    assert snapshot.budget_minor == 20_000
    assert snapshot.pending_sync == 2
    assert isinstance(snapshot.recent_receipts[0][0], int)
    assert snapshot.recent_receipts[0][2] == "Corner Cafe"


def test_main_window_exposes_dashboard_and_workflows(
    qt_application: QApplication, desktop_controller: DesktopController
) -> None:
    window = MainWindow(desktop_controller)
    assert window.windowTitle() == "SpendScope"
    assert window.cards["inbox"].accessibleName() == "Inbox"
    assert window.recent.accessibleName() == "Recent confirmed expenses"
    assert " of " in window.cards["storage"].value.text()
    assert "total capacity" in window.cards["storage"].toolTip()
    assert window.prompt.text() == f"“{FINANCIAL_PROMPTS[0]}”"
    assert window.prompt.font().italic()
    assert window.quote_timer.interval() == 60 * 60 * 1000
    assert window.findChild(QWidget, "contentColumn").maximumWidth() == 1120
    assert window.findChild(QFrame, "shortcutPanel") is None
    window._advance_prompt()
    assert window.prompt.text() == f"“{FINANCIAL_PROMPTS[1]}”"
    assert window.report_button.text() == "Connect Google"
    assert [button.text() for button in window.navigation_buttons] == [
        "Receipts",
        "Connect Google",
        "Settings",
    ]
    assert all(button.objectName() == "navigationAction" for button in window.navigation_buttons)
    assert all(
        button.cursor().shape() == Qt.CursorShape.PointingHandCursor
        for button in window.navigation_buttons
    )
    assert window.review_action.property("tone") == "coral"
    assert window.sync_action.property("tone") == "teal"
    assert "Review receipts" in window.review_action.title.text()
    window.close()


def test_first_run_suggests_and_explains_automatic_workspace(
    qt_application: QApplication, tmp_path: Path
) -> None:
    wizard = SetupWizard(tmp_path / "settings.json")
    assert Path(wizard.root_edit.text()).name == "SpendScope"
    assert wizard.root_edit.accessibleName() == "Workspace folder"


def test_storage_dialog_explains_workspace_and_disk_calculations(
    qt_application: QApplication, desktop_controller: DesktopController
) -> None:
    dialog = StorageDialog(desktop_controller)
    assert "used by SpendScope" in dialog.summary.text()
    assert "does not impose its own quota" in dialog.explanation.text()
    assert dialog.table.horizontalHeaderItem(1).text() == "Space used"
    assert dialog.table.item(0, 0).text() == "Newly imported receipts"


def test_settings_hides_manual_sheet_id_and_explains_automatic_report(
    qt_application: QApplication, desktop_controller: DesktopController
) -> None:
    dialog = SettingsDialog(desktop_controller)
    assert "creates a Drive folder" in dialog.google_status.text()
    assert dialog.google_connect.text() == "Connect Google Drive"
    assert dialog.google_connect.isEnabled()
    assert not dialog.google_open_report.isEnabled()
    assert not dialog.google_disconnect.isEnabled()
    assert dialog.appearance.currentData() == Appearance.SYSTEM
    assert not any(
        "Developer connection" in button.text() for button in dialog.findChildren(QPushButton)
    )


def test_settings_shows_connected_google_state(
    qt_application: QApplication,
    desktop_controller: DesktopController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        desktop_controller,
        "report_url",
        lambda: "https://docs.google.com/spreadsheets/d/report-123",
    )

    dialog = SettingsDialog(desktop_controller)

    assert dialog.google_connect.text() == "Google Drive connected ✓"
    assert not dialog.google_connect.isEnabled()
    assert dialog.google_open_report.isEnabled()
    assert dialog.google_disconnect.isEnabled()


def test_appearance_can_be_changed_from_dashboard_and_persists(
    qt_application: QApplication, desktop_controller: DesktopController
) -> None:
    window = MainWindow(desktop_controller)
    window._set_appearance(Appearance.DARK)

    assert desktop_controller.config.appearance is Appearance.DARK
    assert load_config(desktop_controller.config_path).appearance is Appearance.DARK
    assert qt_application.property("spendscopeAppearance") == "dark"
    assert qt_application.property("spendscopeTheme") == "dark"
    assert window.appearance_actions[Appearance.DARK].isChecked()
    window.close()


def test_explicit_appearance_uses_embedded_theme(qt_application: QApplication) -> None:
    apply_appearance(qt_application, Appearance.LIGHT)
    assert qt_application.property("spendscopeAppearance") == "light"
    assert qt_application.property("spendscopeTheme") == "light"


@pytest.mark.parametrize("theme", [Theme.LIGHT, Theme.DARK])
def test_embedded_themes_style_text_inputs_and_buttons(
    qt_application: QApplication, theme: Theme
) -> None:
    apply_theme(qt_application, theme)
    expected = THEMES[theme]
    palette = qt_application.palette()
    assert qt_application.property("spendscopeTheme") == theme.value
    assert palette.color(QPalette.ColorRole.Window).name() == expected.window
    assert palette.color(QPalette.ColorRole.WindowText).name() == expected.text
    assert palette.color(QPalette.ColorRole.Base).name() == expected.surface

    field = QLineEdit()
    button = QPushButton("Visible action")
    assert field.palette().color(QPalette.ColorRole.Text).name() == expected.text
    assert button.palette().color(QPalette.ColorRole.ButtonText).name() == expected.text
    assert expected.disabled_text in qt_application.styleSheet()


def test_manual_and_review_dialogs_render_offscreen(
    qt_application: QApplication, desktop_controller: DesktopController
) -> None:
    manual = ManualEntryDialog(desktop_controller)
    assert manual.windowTitle() == "Add an expense or refund"
    assert manual.category.count() > 0
    review = ReviewDialog(desktop_controller)
    assert review.list.count() == 0
    assert not review.confirm.isEnabled()


def test_categories_can_be_added_and_renamed_from_desktop(
    qt_application: QApplication, desktop_controller: DesktopController
) -> None:
    internal, display = desktop_controller.add_category("  Self   care  ")
    assert display == "Self care"
    assert (internal, display) in desktop_controller.categories()

    renamed = desktop_controller.rename_category(internal, "Wellness")
    assert renamed == (internal, "Wellness")
    assert (internal, "Wellness") in desktop_controller.categories()

    dialog = CategoryManagerDialog(desktop_controller)
    assert dialog.windowTitle() == "Manage categories"
    assert any(
        dialog.categories_list.item(row).text() == "Wellness"
        for row in range(dialog.categories_list.count())
    )


def _create_review_receipt(controller: DesktopController) -> int:
    controller.create_manual(
        ManualExpenseDraft(
            transaction_date=date(2026, 8, 7),
            description="Mystery item",
            category_internal_name="unallocated",
            amount_minor=500,
            currency="USD",
            merchant="LOCAL MARKET",
        )
    )
    with session_scope(controller.engine) as session:
        receipt = session.scalar(select(ReceiptRecord).order_by(ReceiptRecord.id.desc()))
        assert receipt is not None
        ReviewService(session).flag(
            receipt, "item category needs review", severity=ReviewSeverity.HIGH
        )
        return receipt.id


def test_receipt_review_corrections_confirm_and_update_dashboard(
    qt_application: QApplication, desktop_controller: DesktopController
) -> None:
    receipt_id = _create_review_receipt(desktop_controller)
    pending = desktop_controller.pending_receipts()
    assert len(pending) == 1
    assert pending[0].review_reason == "item category needs review"

    desktop_controller.correct_and_confirm_receipt(
        ReceiptCorrectionDraft(
            receipt_id=receipt_id,
            merchant="Neighborhood Market",
            transaction_date=date(2026, 8, 7),
            subtotal_minor=500,
            final_total_minor=500,
            items=[
                ReceiptItemCorrection(
                    id=pending[0].items[0].id,
                    description="Rice flour",
                    line_total_minor=500,
                    category_internal_name="groceries",
                    remember=True,
                )
            ],
        )
    )

    assert desktop_controller.pending_receipts() == []
    snapshot = desktop_controller.dashboard(date(2026, 8, 7))
    assert snapshot.month_spending_minor == 500
    assert snapshot.recent_receipts[0][2] == "Neighborhood Market"
    with session_scope(desktop_controller.engine) as session:
        receipt = session.get(ReceiptRecord, receipt_id)
        assert receipt is not None
        assert receipt.line_items[0].description_original == "Rice flour"
        assert receipt.line_items[0].category.internal_name == "groceries"

    confirmed = desktop_controller.confirmed_receipt(receipt_id)
    desktop_controller.update_confirmed_receipt(
        ReceiptCorrectionDraft(
            receipt_id=receipt_id,
            merchant="Neighborhood Market",
            transaction_date=date(2026, 8, 7),
            subtotal_minor=500,
            final_total_minor=500,
            items=[
                ReceiptItemCorrection(
                    id=confirmed.items[0].id,
                    description="Rice flour",
                    line_total_minor=500,
                    category_internal_name="shopping",
                )
            ],
        )
    )
    assert desktop_controller.dashboard(date(2026, 8, 7)).category_spending == (("Shopping", 500),)


def test_review_dialog_exposes_editable_receipt_fields(
    qt_application: QApplication, desktop_controller: DesktopController
) -> None:
    _create_review_receipt(desktop_controller)
    dialog = ReviewDialog(desktop_controller)
    assert dialog.list.count() == 1
    assert dialog.merchant.text() == "LOCAL MARKET"
    assert dialog.items.rowCount() == 1
    assert dialog.confirm.isEnabled()
    assert "Balanced" in dialog.reconciliation.text()


def test_direct_receipt_import_accepts_images_and_explains_rejections(
    tmp_path: Path, desktop_controller: DesktopController
) -> None:
    receipt = tmp_path / "receipt.png"
    Image.new("RGB", (30, 30), "white").save(receipt)
    invalid = tmp_path / "notes.txt"
    invalid.write_text("not a receipt", encoding="utf-8")

    imported, rejected = desktop_controller.import_receipts([receipt, invalid])

    assert len(imported) == 1
    assert imported[0].parent == desktop_controller.config.directory_paths()["inbox"]
    assert imported[0].read_bytes().startswith(b"\x89PNG")
    assert rejected == ["notes.txt: unsupported file type"]


def test_receipt_correction_requires_reconciled_totals() -> None:
    with pytest.raises(ValueError, match="final total"):
        ReceiptCorrectionDraft(
            receipt_id=1,
            merchant="Market",
            transaction_date=date(2026, 8, 7),
            subtotal_minor=500,
            tax_minor=50,
            final_total_minor=500,
            items=[],
        )


def test_worker_reports_result_and_error(qt_application: QApplication) -> None:
    results: list[object] = []
    errors: list[str] = []
    success = BackgroundJob(lambda: 42)
    success.signals.finished.connect(results.append)
    success.run()
    failure = BackgroundJob(lambda: 1 / 0)
    failure.signals.failed.connect(errors.append)
    failure.run()
    assert results == [42]
    assert errors and "zero" in errors[0]


def test_config_and_display_helpers(tmp_path: Path, qt_application: QApplication) -> None:
    assert format_bytes(1536) == "1.5 KB"
    assert default_config_path().name == "settings.json"
    config_path = tmp_path / "settings.json"
    save_config(AppConfig(root_folder=tmp_path / "workspace"), config_path)
    assert load_config(config_path).root_folder == (tmp_path / "workspace").resolve()
