"""Focused desktop dialogs for everyday expense workflows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spendscope.config import AppConfig, Appearance, RetentionPolicy
from spendscope.domain.models import (
    BudgetDraft,
    ManualExpenseDraft,
    Money,
    ReceiptCorrectionDraft,
    ReceiptItemCorrection,
    RefundDraft,
)
from spendscope.reporting.google_auth import bundled_client_secrets
from spendscope.ui.controller import DesktopController
from spendscope.ui.theme import apply_appearance


def money_text(minor: int, currency: str) -> str:
    return f"{currency} {Decimal(minor) / Decimal(100):,.2f}"


class ManualEntryDialog(QDialog):
    def __init__(self, controller: DesktopController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Add an expense or refund")
        self.kind = QComboBox()
        self.kind.addItems(["Expense", "Refund"])
        self.when = QDateEdit(QDate.currentDate())
        self.when.setCalendarPopup(True)
        self.description = QLineEdit()
        self.merchant = QLineEdit()
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, 999_999_999.99)
        self.amount.setDecimals(2)
        self.category = QComboBox()
        for internal, display in controller.categories():
            self.category.addItem(display, internal)
        self.note = QTextEdit()
        self.note.setMaximumHeight(90)
        form = QFormLayout()
        form.addRow("Entry type", self.kind)
        form.addRow("Date", self.when)
        form.addRow("Description", self.description)
        form.addRow("Merchant (optional)", self.merchant)
        form.addRow(f"Amount ({controller.config.default_currency})", self.amount)
        form.addRow("Category", self.category)
        form.addRow("Note (optional)", self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _save(self) -> None:
        if not self.description.text().strip():
            QMessageBox.warning(self, "Description required", "Enter a description.")
            self.description.setFocus()
            return
        amount_minor = Money.from_decimal(
            Decimal(str(self.amount.value())), self.controller.config.default_currency
        ).minor_units
        values = dict(
            transaction_date=date(
                self.when.date().year(), self.when.date().month(), self.when.date().day()
            ),
            description=self.description.text().strip(),
            category_internal_name=str(self.category.currentData()),
            amount_minor=amount_minor,
            currency=self.controller.config.default_currency,
            merchant=self.merchant.text().strip() or None,
        )
        try:
            if self.kind.currentText() == "Refund":
                self.controller.create_manual(RefundDraft(**values))
            else:
                self.controller.create_manual(
                    ManualExpenseDraft(**values, note=self.note.toPlainText().strip() or None)
                )
        except (ValueError, LookupError) as error:
            QMessageBox.critical(self, "Entry could not be saved", str(error))
            return
        self.accept()


class ReviewDialog(QDialog):
    receipt_resolved = Signal()

    def __init__(
        self,
        controller: DesktopController,
        parent: QWidget | None = None,
        *,
        confirmed_receipt_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.confirmed_receipt_id = confirmed_receipt_id
        self.setWindowTitle(
            "Edit expense" if confirmed_receipt_id is not None else "Review receipts"
        )
        self.resize(1180, 820)
        self.setMinimumSize(900, 680)
        self.setSizeGripEnabled(True)
        self._loading = False
        self.list = QListWidget()
        self.list.setMinimumWidth(250)
        self.list.setVisible(confirmed_receipt_id is None)
        self.list.currentRowChanged.connect(self._selection_changed)
        self.preview = QLabel("Select a receipt to preview its source file.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 260)
        self.preview.setMaximumHeight(280)
        self.preview.setWordWrap(True)
        self.reason = QLabel()
        self.reason.setObjectName("secondaryText")
        self.reason.setWordWrap(True)
        self.reason.setMinimumHeight(64)
        self.merchant = QLineEdit()
        self.when = QDateEdit()
        self.when.setCalendarPopup(True)
        self.currency = QLabel()
        self.subtotal = self._money_input()
        self.tax = self._money_input()
        self.tip = self._money_input()
        self.discount = self._money_input()
        self.total = self._money_input()
        for field in (self.subtotal, self.tax, self.tip, self.discount):
            field.valueChanged.connect(self._update_reconciliation)
        self.total.setReadOnly(True)
        for field in (self.subtotal, self.tax, self.tip, self.discount):
            field.valueChanged.connect(self._update_total)
        details = QFormLayout()
        details.addRow("Merchant", self.merchant)
        details.addRow("Date", self.when)
        details.addRow("Currency", self.currency)
        details.addRow("Subtotal", self.subtotal)
        details.addRow("Tax", self.tax)
        details.addRow("Tip", self.tip)
        details.addRow("Discount", self.discount)
        details.addRow("Final total", self.total)

        self.items = QTableWidget(0, 3)
        self.items.setHorizontalHeaderLabels(["Description", "Amount", "Category"])
        self.items.setMinimumHeight(300)
        self.items.verticalHeader().setDefaultSectionSize(48)
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.items.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.items.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.items.itemChanged.connect(self._update_reconciliation)
        add_item = QPushButton("Add item")
        remove_item = QPushButton("Remove selected item")
        add_item.clicked.connect(self._add_item)
        remove_item.clicked.connect(self._remove_item)
        item_actions = QHBoxLayout()
        item_actions.addWidget(add_item)
        item_actions.addWidget(remove_item)
        item_actions.addStretch()
        self.remember = QCheckBox("Remember corrected item names and categories")
        self.remember.setChecked(True)
        self.reconciliation = QLabel()
        self.reconciliation.setWordWrap(True)
        self.confirm = QPushButton(
            "Save changes" if confirmed_receipt_id is not None else "Save corrections and confirm"
        )
        self.confirm.setObjectName("primaryAction")
        self.reject_button = QPushButton("Reject receipt")
        self.reject_button.setVisible(confirmed_receipt_id is None)
        self.delete_button = QPushButton("Delete expense")
        self.delete_button.setVisible(confirmed_receipt_id is not None)
        self.open_source = QPushButton("Open source")
        self.confirm.clicked.connect(lambda: self._resolve(True))
        self.reject_button.clicked.connect(lambda: self._resolve(False))
        self.delete_button.clicked.connect(self._delete_expense)
        self.open_source.clicked.connect(self._open_source)
        metadata = QVBoxLayout()
        metadata.addWidget(self.reason)
        metadata.addLayout(details)
        metadata.addStretch()
        receipt_details = QHBoxLayout()
        receipt_details.addWidget(self.preview, 3)
        receipt_details.addLayout(metadata, 2)
        editor = QVBoxLayout()
        editor.addLayout(receipt_details)
        editor.addWidget(QLabel("Line items"))
        editor.addWidget(self.items, 1)
        editor.addLayout(item_actions)
        editor.addWidget(self.remember)
        editor.addWidget(self.reconciliation)
        content = QHBoxLayout()
        content.addWidget(self.list, 1)
        content.addLayout(editor, 3)
        actions = QHBoxLayout()
        actions.addWidget(self.open_source)
        actions.addStretch()
        actions.addWidget(self.delete_button)
        actions.addWidget(self.reject_button)
        actions.addWidget(self.confirm)
        title = QLabel("Edit expense" if confirmed_receipt_id is not None else "Review receipts")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "Update its details or categories. Your dashboard will refresh immediately."
            if confirmed_receipt_id is not None
            else "Check the important details, then confirm when everything looks right."
        )
        subtitle.setObjectName("dialogSubtitle")
        header = QVBoxLayout()
        header.setSpacing(3)
        header.addWidget(title)
        header.addWidget(subtitle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addLayout(content)
        layout.addLayout(actions)
        self._size_to_available_screen()
        self.rows = self.controller.pending_receipts()
        self._reload()

    def _size_to_available_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(1400, max(1180, int(available.width() * 0.94)))
        height = min(900, max(760, int(available.height() * 0.88)))
        self.resize(width, height)

    @staticmethod
    def _money_input() -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setRange(0, 999_999_999.99)
        field.setDecimals(2)
        field.setPrefix("  ")
        return field

    def _reload(self) -> None:
        if self.confirmed_receipt_id is not None:
            try:
                self.rows = [self.controller.confirmed_receipt(self.confirmed_receipt_id)]
            except LookupError:
                self.rows = []
        else:
            self.rows = self.controller.pending_receipts()
        self.list.clear()
        for receipt in self.rows:
            self.list.addItem(
                f"{receipt.transaction_date.isoformat()}\n{receipt.merchant}\n"
                f"{money_text(receipt.final_total_minor, receipt.currency)}"
            )
        enabled = bool(self.rows)
        self.confirm.setEnabled(enabled)
        self.reject_button.setEnabled(enabled)
        self.open_source.setEnabled(enabled)
        if enabled:
            self.list.setCurrentRow(0)
        else:
            self._clear_editor()

    def _clear_editor(self) -> None:
        self._loading = True
        self.list.setCurrentRow(-1)
        self.preview.clear()
        self.preview.setText("All caught up — no receipts need review.")
        self.reason.setText("Your confirmed receipt is now included in your spending.")
        self.merchant.clear()
        self.when.setDate(QDate.currentDate())
        self.currency.clear()
        for field in (self.subtotal, self.tax, self.tip, self.discount, self.total):
            field.setValue(0)
        self.items.clearContents()
        self.items.setRowCount(0)
        self.remember.setChecked(False)
        self.reconciliation.setText("")
        self._loading = False

    def _selection_changed(self, index: int) -> None:
        if not 0 <= index < len(self.rows):
            return
        receipt = self.rows[index]
        self._loading = True
        self.merchant.setText(receipt.merchant)
        self.when.setDate(
            QDate(
                receipt.transaction_date.year,
                receipt.transaction_date.month,
                receipt.transaction_date.day,
            )
        )
        self.currency.setText(receipt.currency)
        self.subtotal.setValue(receipt.subtotal_minor / 100)
        self.tax.setValue(receipt.tax_minor / 100)
        self.tip.setValue(receipt.tip_minor / 100)
        self.discount.setValue(receipt.discount_minor / 100)
        self.total.setValue(receipt.final_total_minor / 100)
        readable_reason = (
            receipt.review_reason.replace("_", " ").replace(";", ".").strip().capitalize()
            if receipt.review_reason
            else None
        )
        self.reason.setText(
            f"Why this needs a look: {readable_reason}"
            if readable_reason
            else (
                "Editing a confirmed expense. Saved changes will be ready for Google Sheets."
                if self.confirmed_receipt_id is not None
                else "Review the extracted details before confirming."
            )
        )
        self.items.setRowCount(0)
        for item in receipt.items:
            self._append_item(
                item.id,
                item.description,
                item.line_total_minor,
                item.category_internal_name,
            )
        self._loading = False
        self._update_total()
        self._update_reconciliation()
        path_value = receipt.source_path
        if not path_value:
            self.preview.setText("No source file is available for this receipt.")
            return
        path = Path(path_value)
        pixmap = self._source_pixmap(path)
        if pixmap is not None:
            self.preview.setPixmap(
                pixmap.scaled(
                    self.preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            return
        self.preview.setText(f"Source preview\n{path.name}\n\nUse Open source to view this file.")

    @staticmethod
    def _source_pixmap(path: Path) -> QPixmap | None:
        if path.suffix.casefold() in {".jpg", ".jpeg", ".png"}:
            pixmap = QPixmap(str(path))
            return None if pixmap.isNull() else pixmap
        if path.suffix.casefold() == ".pdf":
            try:
                import pymupdf

                with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
                    if not document.page_count:
                        return None
                    matrix = pymupdf.Matrix(1.5, 1.5)  # type: ignore[no-untyped-call]
                    data = document[0].get_pixmap(matrix=matrix).tobytes("png")
                pixmap = QPixmap()
                return pixmap if pixmap.loadFromData(data) else None
            except (OSError, RuntimeError, ValueError):
                return None
        return None

    def _append_item(
        self,
        item_id: int | None,
        description: str,
        line_total_minor: int,
        category_name: str,
    ) -> None:
        row = self.items.rowCount()
        self.items.insertRow(row)
        description_item = QTableWidgetItem(description)
        description_item.setData(Qt.ItemDataRole.UserRole, item_id)
        self.items.setItem(row, 0, description_item)
        amount = self._money_input()
        amount.setValue(line_total_minor / 100)
        amount.valueChanged.connect(self._line_amount_changed)
        amount.valueChanged.connect(self._update_reconciliation)
        self.items.setCellWidget(row, 1, amount)
        category = QComboBox()
        for internal, display in self.controller.categories():
            category.addItem(display, internal)
        category.setCurrentIndex(max(0, category.findData(category_name)))
        category.currentIndexChanged.connect(self._update_reconciliation)
        self.items.setCellWidget(row, 2, category)

    def _add_item(self) -> None:
        self._append_item(None, "New item", 0, "unallocated")
        self.items.setCurrentCell(self.items.rowCount() - 1, 0)
        self.items.editItem(self.items.currentItem())
        self._update_reconciliation()

    def _remove_item(self) -> None:
        row = self.items.currentRow()
        if row >= 0:
            self.items.removeRow(row)
            self._sync_subtotal_to_items()
            self._update_reconciliation()

    def _line_amount_changed(self, *_args: object) -> None:
        self._sync_subtotal_to_items()
        self._update_reconciliation()

    def _sync_subtotal_to_items(self) -> None:
        if self._loading or not self.items.rowCount():
            return
        subtotal = sum(self._row_amount(row).value() for row in range(self.items.rowCount()))
        self.subtotal.blockSignals(True)
        self.subtotal.setValue(subtotal)
        self.subtotal.blockSignals(False)

    def _update_reconciliation(self, *_args: object) -> None:
        if self._loading:
            return
        item_total = sum(self._row_amount(row).value() for row in range(self.items.rowCount()))
        calculated = (
            self.subtotal.value() + self.tax.value() + self.tip.value() - self.discount.value()
        )
        differences = []
        if self.items.rowCount() and round(item_total - self.subtotal.value(), 2):
            differences.append(
                f"items differ from subtotal by {item_total - self.subtotal.value():+.2f}"
            )
        if round(calculated - self.total.value(), 2):
            differences.append(
                f"calculated total differs by {calculated - self.total.value():+.2f}"
            )
        if differences:
            self.reconciliation.setText("Needs correction: " + "; ".join(differences))
            self.confirm.setEnabled(False)
        else:
            self.reconciliation.setText("Balanced — this receipt is ready to confirm.")
            self.confirm.setEnabled(bool(self.rows))

    def _update_total(self, *_args: object) -> None:
        if self._loading:
            return
        self.total.setValue(
            self.subtotal.value() + self.tax.value() + self.tip.value() - self.discount.value()
        )
        self._update_reconciliation()

    def _row_amount(self, row: int) -> QDoubleSpinBox:
        return self.items.cellWidget(row, 1)  # type: ignore[return-value]

    def _draft(self) -> ReceiptCorrectionDraft:
        index = self.list.currentRow()
        if not 0 <= index < len(self.rows):
            raise ValueError("Select a receipt to confirm")
        receipt = self.rows[index]
        item_drafts = []
        for row in range(self.items.rowCount()):
            description = self.items.item(row, 0)
            category = self.items.cellWidget(row, 2)
            if description is None or not isinstance(category, QComboBox):
                raise ValueError("Every line item needs a description and category")
            item_drafts.append(
                ReceiptItemCorrection(
                    id=description.data(Qt.ItemDataRole.UserRole),
                    description=description.text().strip(),
                    line_total_minor=Money.from_decimal(
                        Decimal(str(self._row_amount(row).value())), receipt.currency
                    ).minor_units,
                    category_internal_name=str(category.currentData()),
                    remember=self.remember.isChecked(),
                )
            )
        selected_date = self.when.date()
        return ReceiptCorrectionDraft(
            receipt_id=receipt.id,
            merchant=self.merchant.text().strip(),
            transaction_date=date(selected_date.year(), selected_date.month(), selected_date.day()),
            subtotal_minor=self._minor_value(self.subtotal, receipt.currency),
            tax_minor=self._minor_value(self.tax, receipt.currency),
            tip_minor=self._minor_value(self.tip, receipt.currency),
            discount_minor=self._minor_value(self.discount, receipt.currency),
            final_total_minor=self._minor_value(self.total, receipt.currency),
            items=item_drafts,
        )

    @staticmethod
    def _minor_value(field: QDoubleSpinBox, currency: str) -> int:
        return Money.from_decimal(Decimal(str(field.value())), currency).minor_units

    def _open_source(self) -> None:
        index = self.list.currentRow()
        if 0 <= index < len(self.rows) and self.rows[index].source_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.rows[index].source_path or ""))

    def _delete_expense(self) -> None:
        if self.confirmed_receipt_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete this expense?",
            "This removes the expense from SpendScope and queues its removal from Google Sheets.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.delete_receipt(self.confirmed_receipt_id)
        except (LookupError, OSError, ValueError) as error:
            QMessageBox.critical(self, "Expense could not be deleted", str(error))
            return
        self.receipt_resolved.emit()
        self.accept()

    def _resolve(self, confirm: bool) -> None:
        index = self.list.currentRow()
        if not 0 <= index < len(self.rows):
            return
        if confirm:
            try:
                if self.confirmed_receipt_id is not None:
                    self.controller.update_confirmed_receipt(self._draft())
                else:
                    self.controller.correct_and_confirm_receipt(self._draft())
            except (ValueError, LookupError, OSError) as error:
                QMessageBox.critical(self, "Receipt could not be confirmed", str(error))
                return
        else:
            answer = QMessageBox.question(
                self,
                "Reject this receipt?",
                "The receipt will be marked rejected. Its data will not count toward spending.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.controller.resolve_receipt(self.rows[index].id, confirm=False)
        self.receipt_resolved.emit()
        if self.confirmed_receipt_id is not None:
            self.accept()
            return
        self._reload()


class BudgetsDialog(QDialog):
    def __init__(self, controller: DesktopController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Monthly budgets")
        self.resize(860, 560)
        today = date.today()
        self.year = QSpinBox()
        self.year.setRange(2000, 9999)
        self.year.setValue(today.year)
        self.month = QComboBox()
        self.month.addItems([f"{number:02d}" for number in range(1, 13)])
        self.month.setCurrentIndex(today.month - 1)
        self.category = QComboBox()
        self.category.addItem("Overall budget", None)
        for internal, display in controller.categories():
            self.category.addItem(display, internal)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, 999_999_999.99)
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 100)
        self.threshold.setValue(controller.config.budget_warning_percent)
        save = QPushButton("Set budget")
        save.setObjectName("primaryAction")
        save.clicked.connect(self._save)
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)
        fields = (
            ("Year", self.year),
            ("Month", self.month),
            ("Budget type", self.category),
            ("Amount", self.amount),
            ("Alert me at %", self.threshold),
        )
        for column, (label, widget) in enumerate(fields):
            caption = QLabel(label)
            caption.setObjectName("secondaryText")
            form.addWidget(caption, 0, column)
            form.addWidget(widget, 1, column)
        form.addWidget(save, 1, len(fields))
        form_panel = QFrame()
        form_panel.setObjectName("dialogPanel")
        panel_layout = QVBoxLayout(form_panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        panel_layout.addLayout(form)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Scope", "Budget", "Spent", "Remaining", "Status"])
        self.year.valueChanged.connect(self._reload)
        self.month.currentIndexChanged.connect(self._reload)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        title = QLabel("Plan your month")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Choose a comfortable target. You can adjust it at any time.")
        subtitle.setObjectName("dialogSubtitle")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(form_panel)
        layout.addWidget(self.table)
        layout.addWidget(close)
        self._reload()

    def _save(self) -> None:
        try:
            minor = Money.from_decimal(
                Decimal(str(self.amount.value())), self.controller.config.default_currency
            ).minor_units
            self.controller.set_budget(
                BudgetDraft(
                    year=self.year.value(),
                    month=self.month.currentIndex() + 1,
                    category_internal_name=self.category.currentData(),
                    currency=self.controller.config.default_currency,
                    amount_minor=minor,
                    warning_threshold=self.threshold.value(),
                )
            )
        except (ValueError, InvalidOperation) as error:
            QMessageBox.critical(self, "Budget could not be saved", str(error))
            return
        self._reload()

    def _reload(self) -> None:
        rows = self.controller.budgets(self.year.value(), self.month.currentIndex() + 1)
        self.table.setRowCount(len(rows))
        labels = dict(self.controller.categories())
        for row, summary in enumerate(rows):
            scope = (
                "Overall"
                if summary.category_internal_name is None
                else labels.get(summary.category_internal_name, summary.category_internal_name)
            )
            values = (
                scope,
                money_text(summary.budget_minor, summary.currency),
                money_text(summary.spent_minor, summary.currency),
                money_text(summary.remaining_minor, summary.currency),
                summary.status.value.replace("_", " ").title(),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))


class StorageDialog(QDialog):
    def __init__(self, controller: DesktopController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Storage management")
        self.resize(620, 460)
        self.summary = QLabel()
        self.summary.setObjectName("sectionHeading")
        self.explanation = QLabel()
        self.explanation.setObjectName("secondaryText")
        self.explanation.setWordWrap(True)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["SpendScope area", "Space used"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.retention = QComboBox()
        for policy in RetentionPolicy:
            self.retention.addItem(policy.value.replace("_", " ").title(), policy.value)
        self.retention.setCurrentIndex(
            max(0, self.retention.findData(controller.config.retention_policy.value))
        )
        save = QPushButton("Save retention policy")
        save.clicked.connect(self._save_policy)
        open_archive = QPushButton("Open archive")
        open_archive.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(controller.config.directory_paths()["archive"]))
            )
        )
        controls = QHBoxLayout()
        controls.addWidget(self.retention)
        controls.addWidget(save)
        controls.addWidget(open_archive)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.explanation)
        layout.addWidget(self.table)
        layout.addLayout(controls)
        layout.addWidget(close)
        self._reload()

    def _reload(self) -> None:
        report = self.controller.storage()
        self.summary.setText(
            f"{format_bytes(report.total_bytes)} used by SpendScope out of "
            f"{format_bytes(report.disk_capacity_bytes)} total disk capacity"
        )
        self.explanation.setText(
            f"{format_bytes(report.disk_free_bytes)} is currently free on this disk. "
            "SpendScope usage is calculated by adding the sizes of all files inside your "
            "selected workspace. Disk capacity and free space come from the operating system "
            "for the drive containing that workspace; SpendScope does not impose its own quota."
        )
        areas = report.as_dict()
        labels = {
            "inbox": "Newly imported receipts",
            "archive": "Processed receipt originals",
            "needs_review": "Receipts waiting for review",
            "database": "Spending database",
            "logs": "Diagnostic logs",
            "exports": "Exported reports",
            "total": "Entire SpendScope workspace",
        }
        self.table.setRowCount(len(areas))
        for row, (area, size) in enumerate(areas.items()):
            self.table.setItem(row, 0, QTableWidgetItem(labels[area]))
            self.table.setItem(row, 1, QTableWidgetItem(format_bytes(size)))

    def _save_policy(self) -> None:
        config = self.controller.config.model_copy(
            update={"retention_policy": RetentionPolicy(str(self.retention.currentData()))}
        )
        self.controller.save_settings(config)
        QMessageBox.information(self, "Settings saved", "The retention policy was updated.")


class SettingsDialog(QDialog):
    def __init__(self, controller: DesktopController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Settings")
        self.currency = QLineEdit(controller.config.default_currency)
        self.appearance = QComboBox()
        self.appearance.addItem("Follow system", Appearance.SYSTEM)
        self.appearance.addItem("Light", Appearance.LIGHT)
        self.appearance.addItem("Dark", Appearance.DARK)
        self.appearance.setCurrentIndex(
            max(0, self.appearance.findData(controller.config.appearance))
        )
        self.quality = QSpinBox()
        self.quality.setRange(40, 95)
        self.quality.setValue(controller.config.compression_quality)
        form = QFormLayout()
        form.addRow("Appearance", self.appearance)
        form.addRow("Default currency", self.currency)
        form.addRow("Compression quality", self.quality)
        category_heading = QLabel("Spending categories")
        category_heading.setObjectName("sectionHeading")
        category_help = QLabel(
            "Add your own categories or rename the ones you use. Existing expenses stay intact."
        )
        category_help.setObjectName("secondaryText")
        category_help.setWordWrap(True)
        manage_categories = QPushButton("Manage categories")
        manage_categories.clicked.connect(self._manage_categories)
        google_heading = QLabel("Google Drive report")
        google_heading.setObjectName("sectionHeading")
        self.google_status = QLabel()
        self.google_status.setObjectName("secondaryText")
        self.google_status.setWordWrap(True)
        google_actions = QHBoxLayout()
        self.google_connect = QPushButton("Connect Google Drive")
        self.google_connect.setObjectName("primaryAction")
        self.google_disconnect = QPushButton("Disconnect")
        self.google_open_report = QPushButton("Open report")
        self.google_connect.clicked.connect(self._connect_google)
        self.google_disconnect.clicked.connect(self._disconnect_google)
        self.google_open_report.clicked.connect(self._open_report)
        google_actions.addWidget(self.google_connect)
        google_actions.addWidget(self.google_open_report)
        google_actions.addWidget(self.google_disconnect)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(category_heading)
        layout.addWidget(category_help)
        layout.addWidget(manage_categories)
        layout.addWidget(google_heading)
        layout.addWidget(self.google_status)
        layout.addLayout(google_actions)
        layout.addWidget(buttons)
        self._refresh_google_status()

    def _manage_categories(self) -> None:
        CategoryManagerDialog(self.controller, self).exec()

    def _connect_google(self) -> None:
        path = bundled_client_secrets()
        if path is None:
            QMessageBox.information(
                self,
                "Google connection needs publisher setup",
                "This development build does not yet contain SpendScope's Google OAuth client. "
                "The app owner must register it once before regular users can connect with one "
                "click. You can still use every local feature now.",
            )
            return
        self._finish_google_connection(path)

    def _finish_google_connection(self, path: Path) -> None:
        try:
            result = self.controller.connect_google(path)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Google account could not be connected", str(error))
            return
        if result.error:
            QMessageBox.critical(self, "Google report could not be created", result.error)
            return
        QMessageBox.information(
            self,
            "Google Drive is ready",
            "SpendScope created its Google Drive folder and spending report. Future confirmed "
            "expenses can now be sent there with Update your report.",
        )
        self._refresh_google_status()

    def _disconnect_google(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Disconnect Google account?",
                "Local spending data will remain unchanged.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.controller.disconnect_google()
        QMessageBox.information(self, "Google account", "The account was disconnected.")
        self._refresh_google_status()

    def _open_report(self) -> None:
        url = self.controller.report_url()
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.information(
                self,
                "No report yet",
                "Connect Google Drive and SpendScope will create the folder and report for you.",
            )

    def _refresh_google_status(self) -> None:
        connected = bool(self.controller.report_url())
        self.google_connect.setText(
            "Google Drive connected ✓" if connected else "Connect Google Drive"
        )
        self.google_connect.setEnabled(not connected)
        self.google_open_report.setEnabled(connected)
        self.google_disconnect.setEnabled(connected)
        if connected:
            self.google_status.setText(
                "Ready. SpendScope created and manages a report inside your Google Drive."
            )
        else:
            self.google_status.setText(
                "Not connected. Once connected, SpendScope creates a Drive folder and spending "
                "report automatically—no Sheet ID or folder setup required."
            )

    def _save(self) -> None:
        try:
            config = self.controller.config.model_copy(
                update={
                    "default_currency": self.currency.text(),
                    "appearance": self.appearance.currentData(),
                    "compression_quality": self.quality.value(),
                }
            )
            config = AppConfig.model_validate(config.model_dump())
            self.controller.save_settings(config)
            application = QApplication.instance()
            if isinstance(application, QApplication):
                apply_appearance(application, config.appearance)
        except ValueError as error:
            QMessageBox.critical(self, "Settings could not be saved", str(error))
            return
        self.accept()


class CategoryManagerDialog(QDialog):
    """Allow people to add and rename categories without losing expense links."""

    def __init__(self, controller: DesktopController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Manage categories")
        self.resize(520, 480)
        title = QLabel("Your categories")
        title.setObjectName("dialogTitle")
        help_text = QLabel(
            "Add a category for future expenses, or select one below and change its name."
        )
        help_text.setObjectName("secondaryText")
        help_text.setWordWrap(True)
        self.categories_list = QListWidget()
        self.categories_list.currentItemChanged.connect(self._selection_changed)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Category name")
        add = QPushButton("Add category")
        add.setObjectName("primaryAction")
        self.rename = QPushButton("Rename selected")
        self.rename.setEnabled(False)
        add.clicked.connect(self._add)
        self.rename.clicked.connect(self._rename)
        self.name.returnPressed.connect(self._add)
        actions = QHBoxLayout()
        actions.addWidget(add)
        actions.addWidget(self.rename)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(help_text)
        layout.addWidget(self.categories_list, 1)
        layout.addWidget(self.name)
        layout.addLayout(actions)
        layout.addWidget(close)
        self._refresh()

    def _refresh(self, selected_internal: str | None = None) -> None:
        self.categories_list.clear()
        for internal, display in self.controller.categories():
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, internal)
            self.categories_list.addItem(item)
            if internal == selected_internal:
                self.categories_list.setCurrentItem(item)

    def _selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self.rename.setEnabled(current is not None)
        if current is not None:
            self.name.setText(current.text())

    def _add(self) -> None:
        try:
            internal, _display = self.controller.add_category(self.name.text())
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Category could not be added", str(error))
            return
        self.name.clear()
        self._refresh(internal)

    def _rename(self) -> None:
        current = self.categories_list.currentItem()
        if current is None:
            return
        try:
            internal, _display = self.controller.rename_category(
                str(current.data(Qt.ItemDataRole.UserRole)), self.name.text()
            )
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Category could not be renamed", str(error))
            return
        self._refresh(internal)


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
