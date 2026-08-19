"""SpendScope desktop dashboard and primary navigation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spendscope.branding import VERSION
from spendscope.config import Appearance
from spendscope.database.connection import create_sqlite_engine, session_scope
from spendscope.extraction.ocr import TesseractOcrEngine
from spendscope.extraction.receipt_extractor import ReceiptTextExtractor
from spendscope.processing.pipeline import IntakeStatus, StoragePipeline
from spendscope.services.processing import ReceiptProcessingService
from spendscope.services.updates import UpdateResult, check_for_update
from spendscope.ui.controller import DesktopController
from spendscope.ui.dialogs import (
    BudgetsDialog,
    ManualEntryDialog,
    ReviewDialog,
    SettingsDialog,
    StorageDialog,
    format_bytes,
    money_text,
)
from spendscope.ui.theme import apply_appearance
from spendscope.ui.workers import BackgroundJob


@dataclass(frozen=True, slots=True)
class ProcessingSummary:
    confirmed: int = 0
    needs_review: int = 0
    duplicates: int = 0
    invalid: int = 0
    failed: int = 0
    errors: tuple[str, ...] = ()


FINANCIAL_PROMPTS = (
    "Notice the pattern before you judge the purchase.",
    "A clear record makes the next decision easier.",
    "Small choices become visible when you track them.",
    "Spend on purpose, not from pressure.",
    "Your budget is a plan, not a punishment.",
    "Clarity today creates options tomorrow.",
    "A receipt is a tiny piece of your bigger picture.",
    "Progress begins with knowing where you are.",
    "Make room for what matters most to you.",
    "Consistency is more useful than perfection.",
    "Track the habit, then shape the habit.",
    "Money feels lighter when the numbers are clear.",
    "A thoughtful pause can protect a meaningful goal.",
    "Your spending should reflect your priorities.",
    "Every recorded purchase improves the picture.",
    "Plan for joy as deliberately as you plan for bills.",
    "Good decisions grow from honest information.",
    "Today's awareness is tomorrow's flexibility.",
    "Keep the system simple enough to keep using it.",
    "Let your numbers tell you what needs attention.",
)


class MetricCard(QFrame):
    clicked = Signal()

    def __init__(self, title: str, detail: str, accessible_name: str | None = None) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAccessibleName(accessible_name or title)
        self.setMinimumHeight(104)
        accent = QFrame()
        accent.setObjectName("metricAccent")
        accent.setFixedWidth(4)
        heading = QLabel(title)
        heading.setObjectName("metricHeading")
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        self.detail = QLabel(detail)
        self.detail.setObjectName("metricDetail")
        content = QVBoxLayout()
        content.setSpacing(3)
        content.addWidget(heading)
        content.addWidget(self.value)
        content.addWidget(self.detail)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(12)
        layout.addWidget(accent)
        layout.addLayout(content)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ActionCard(QFrame):
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, tone: str) -> None:
        super().__init__()
        self.setObjectName("actionCard")
        self.setProperty("tone", tone)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(112)
        self.title = QLabel(title)
        self.title.setObjectName("actionTitle")
        copy = QLabel(subtitle)
        copy.setObjectName("actionSubtitle")
        copy.setWordWrap(True)
        arrow = QLabel("→")
        arrow.setObjectName("actionArrow")
        top = QHBoxLayout()
        top.addWidget(self.title)
        top.addStretch()
        top.addWidget(arrow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addWidget(copy)
        layout.addStretch()
        self.setAccessibleName(title)

    def set_title(self, value: str) -> None:
        self.title.setText(value)
        self.setAccessibleName(value)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SpendingDonut(QWidget):
    COLORS = ("#35b6a6", "#e1aa35", "#e87970", "#8f7bd8", "#5e9ed6", "#7ec27e")

    def __init__(self) -> None:
        super().__init__()
        self.values: tuple[tuple[str, int], ...] = ()
        self.setFixedSize(190, 190)

    def set_values(self, values: tuple[tuple[str, int], ...]) -> None:
        self.values = values
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 10, -10, -10)
        total = sum(max(0, amount) for _, amount in self.values)
        if total <= 0:
            painter.setPen(QColor("#6f8091"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect)
            painter.end()
            return
        start = 90 * 16
        for index, (_, amount) in enumerate(self.values[:6]):
            span = -round((max(0, amount) / total) * 360 * 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.COLORS[index]))
            painter.drawPie(rect, start, span)
            start += span
        hole = rect.adjusted(43, 43, -43, -43)
        painter.setBrush(self.palette().window())
        painter.drawEllipse(hole)
        painter.end()


class SpendingChartCard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("chartCard")
        title = QLabel("Spending by category")
        title.setObjectName("sectionHeading")
        subtitle = QLabel("A quick view of what is shaping this month.")
        subtitle.setObjectName("sectionSubtitle")
        self.chart = SpendingDonut()
        self.legend = QVBoxLayout()
        self.legend.setSpacing(8)
        self.empty = QLabel("Confirm spending to see your category mix.")
        self.empty.setObjectName("sectionSubtitle")
        self.legend.addWidget(self.empty)
        copy = QVBoxLayout()
        copy.addWidget(title)
        copy.addWidget(subtitle)
        copy.addSpacing(12)
        copy.addLayout(self.legend)
        copy.addStretch()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.addLayout(copy, 1)
        layout.addWidget(self.chart)

    def set_values(self, values: tuple[tuple[str, int], ...], currency: str) -> None:
        while self.legend.count():
            item = self.legend.takeAt(0)
            widget = None if item is None else item.widget()
            if widget is not None:
                widget.deleteLater()
        shown = values[:6]
        if not shown:
            label = QLabel("Confirm spending to see your category mix.")
            label.setObjectName("sectionSubtitle")
            self.legend.addWidget(label)
        for index, (name, amount) in enumerate(shown):
            label = QLabel(f"●  {name}    {money_text(amount, currency)}")
            label.setStyleSheet(f"color: {SpendingDonut.COLORS[index]}; font-weight: 650;")
            self.legend.addWidget(label)
        self.chart.set_values(shown)


class MainWindow(QMainWindow):
    def __init__(self, controller: DesktopController) -> None:
        super().__init__()
        self.controller = controller
        self.thread_pool = QThreadPool.globalInstance()
        self.progress: QProgressDialog | None = None
        application = QApplication.instance()
        if isinstance(application, QApplication):
            apply_appearance(application, controller.config.appearance)
        self.setWindowTitle("SpendScope")
        self.resize(1240, 860)
        self.setMinimumSize(900, 640)
        self.setAcceptDrops(True)
        self._build_menu()
        self._build_content()
        self.quote_timer = QTimer(self)
        self.quote_timer.setInterval(60 * 60 * 1000)
        self.quote_timer.timeout.connect(self._advance_prompt)
        self.quote_timer.start()
        self._processing_active = False
        self._last_auto_process_signature: tuple[tuple[str, int, int], ...] = ()
        self.inbox_timer = QTimer(self)
        self.inbox_timer.setInterval(5000)
        self.inbox_timer.timeout.connect(self._auto_process_new_inbox_files)
        self.inbox_timer.start()
        self.statusBar().showMessage(f"Workspace: {controller.config.root_folder}")
        self.refresh()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        import_action = QAction("&Import receipts…", self)
        import_action.setShortcut("Ctrl+O")
        import_action.triggered.connect(self.choose_receipts)
        file_menu.addAction(import_action)
        process_action = QAction("&Process new receipts", self)
        process_action.triggered.connect(self.process_receipts)
        file_menu.addAction(process_action)
        file_menu.addSeparator()
        settings = QAction("&Settings", self)
        settings.setShortcut("Ctrl+,")
        settings.triggered.connect(self.open_settings)
        file_menu.addAction(settings)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        view_menu = self.menuBar().addMenu("&View")
        refresh = QAction("&Refresh", self)
        refresh.setShortcut("Ctrl+R")
        refresh.triggered.connect(self.refresh)
        view_menu.addAction(refresh)
        appearance_menu = view_menu.addMenu("&Appearance")
        self.appearance_actions: dict[Appearance, QAction] = {}
        appearance_group = QActionGroup(self)
        appearance_group.setExclusive(True)
        for appearance, label in (
            (Appearance.SYSTEM, "Follow &System"),
            (Appearance.LIGHT, "&Light"),
            (Appearance.DARK, "&Dark"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.controller.config.appearance is appearance)
            action.triggered.connect(
                lambda checked, selected=appearance: (
                    self._set_appearance(selected) if checked else None
                )
            )
            appearance_group.addAction(action)
            appearance_menu.addAction(action)
            self.appearance_actions[appearance] = action
        help_menu = self.menuBar().addMenu("&Help")
        updates = QAction("Check for &Updates…", self)
        updates.triggered.connect(self.check_for_updates)
        help_menu.addAction(updates)

    def _set_appearance(self, appearance: Appearance) -> None:
        config = self.controller.config.model_copy(update={"appearance": appearance})
        self.controller.save_settings(config)
        self.appearance_actions[appearance].setChecked(True)
        application = QApplication.instance()
        if isinstance(application, QApplication):
            apply_appearance(application, appearance)

    def check_for_updates(self) -> None:
        self.statusBar().showMessage("Checking GitHub for a newer SpendScope release…")
        job = BackgroundJob(lambda: check_for_update(VERSION))
        job.signals.finished.connect(self._update_check_finished)
        job.signals.failed.connect(self._update_check_failed)
        self.thread_pool.start(job)

    def _update_check_finished(self, value: object) -> None:
        result = cast(UpdateResult, value)
        self.statusBar().clearMessage()
        if not result.update_available:
            QMessageBox.information(
                self,
                "SpendScope is up to date",
                f"You are using the latest release ({VERSION}).",
            )
            return
        if (
            QMessageBox.question(
                self,
                "A SpendScope update is available",
                f"Version {result.latest_version} is available. Open the verified GitHub "
                "release page to download it?",
            )
            == QMessageBox.StandardButton.Yes
        ):
            QDesktopServices.openUrl(QUrl(result.release_url))

    def _update_check_failed(self, message: str) -> None:
        self.statusBar().clearMessage()
        QMessageBox.warning(
            self,
            "Could not check for updates",
            "SpendScope could not reach GitHub Releases. Check your internet connection and try "
            f"again.\n\nDetails: {message}",
        )

    def _build_content(self) -> None:
        brand = QLabel("SPENDSCOPE  •  PRIVATE BY DEFAULT")
        brand.setObjectName("brandLabel")
        receipts_button = QPushButton("Receipts")
        receipts_button.setToolTip("Open your imported and processed receipt files.")
        receipts_button.clicked.connect(self._open_receipts)
        self.report_button = QPushButton("Report")
        self.report_button.setToolTip("Open your spending report in Google Sheets.")
        self.report_button.clicked.connect(self.open_report)
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self.open_settings)
        self.navigation_buttons = (receipts_button, self.report_button, settings_button)
        for button in self.navigation_buttons:
            button.setObjectName("navigationAction")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        navigation = QHBoxLayout()
        navigation.setContentsMargins(4, 0, 4, 0)
        navigation.setSpacing(8)
        navigation.addWidget(brand)
        navigation.addStretch()
        for button in self.navigation_buttons:
            navigation.addWidget(button)

        heading = QLabel("See where your money is going")
        heading.setObjectName("pageHeading")
        self.prompt_index = 0
        self.prompt = QLabel(f"“{FINANCIAL_PROMPTS[self.prompt_index]}”")
        self.prompt.setObjectName("pageSubtitle")
        prompt_font = self.prompt.font()
        prompt_font.setItalic(True)
        self.prompt.setFont(prompt_font)
        self.prompt.setWordWrap(True)
        self.prompt.setAccessibleName("Financial reflection")
        hero_layout = QVBoxLayout()
        hero_layout.setContentsMargins(32, 28, 32, 28)
        hero_layout.setSpacing(7)
        hero_layout.addWidget(heading)
        hero_layout.addWidget(self.prompt)
        hero = QFrame()
        hero.setObjectName("heroPanel")
        hero.setMinimumHeight(220)
        hero.setLayout(hero_layout)

        self.cards = {
            "spending": MetricCard("SPENT THIS MONTH", "Confirmed expenses"),
            "budget": MetricCard("BUDGET", "Your monthly breathing room"),
            "inbox": MetricCard("NEW RECEIPTS", "Waiting to be processed", "Inbox"),
            "review": MetricCard("NEEDS A LOOK", "Receipts needing your input"),
            "sync": MetricCard("READY TO SYNC", "Changes not yet in your report"),
            "storage": MetricCard("LOCAL STORAGE", "SpendScope files on this drive"),
        }
        self.cards["storage"].setCursor(Qt.CursorShape.PointingHandCursor)
        self.cards["storage"].setToolTip("View storage details and cleanup options.")
        self.cards["storage"].clicked.connect(self.open_storage)
        self.cards["inbox"].setProperty("interactive", True)
        self.cards["inbox"].setCursor(Qt.CursorShape.PointingHandCursor)
        self.cards["inbox"].setToolTip("Process receipts waiting in the Inbox.")
        self.cards["inbox"].clicked.connect(self.process_receipts)
        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        for index, card in enumerate(self.cards.values()):
            cards.addWidget(card, index // 3, index % 3)

        import_title = QLabel("Have a new receipt?")
        import_title.setObjectName("sectionHeading")
        import_copy = QLabel("Drop it here or choose a JPG, PNG, or PDF.")
        import_copy.setObjectName("sectionSubtitle")
        import_copy.setWordWrap(True)
        self.import_button = QPushButton("Import receipt files")
        self.import_button.setObjectName("primaryAction")
        self.import_button.setAccessibleName("Choose receipt files to import and process")
        self.import_button.clicked.connect(self.choose_receipts)
        self.process_button = QPushButton("Process waiting receipts")
        self.process_button.setAccessibleName("Process receipts waiting in the Inbox")
        self.process_button.clicked.connect(self.process_receipts)
        self.process_button.hide()
        import_layout = QVBoxLayout()
        import_layout.setContentsMargins(24, 24, 24, 24)
        import_layout.setSpacing(8)
        import_layout.addWidget(import_title)
        import_layout.addWidget(import_copy)
        import_layout.addStretch()
        import_layout.addWidget(self.import_button)
        import_layout.addWidget(self.process_button)
        import_panel = QFrame()
        import_panel.setObjectName("importPanel")
        import_panel.setFixedSize(260, 260)
        import_panel.setLayout(import_layout)

        opening = QHBoxLayout()
        opening.setSpacing(14)
        opening.addWidget(hero, 1)
        opening.addWidget(import_panel)

        self.review_action = ActionCard(
            "Review receipts", "Check receipts that need your attention", "coral"
        )
        self.review_action.clicked.connect(self.open_review)
        manual = ActionCard("Add an expense", "Record a purchase without a receipt", "teal")
        manual.clicked.connect(self.open_manual)
        budgets = ActionCard("Set a budget", "Plan a comfortable monthly target", "gold")
        budgets.clicked.connect(self.open_budgets)
        self.sync_action = ActionCard(
            "Sync report", "Send confirmed spending to Google Sheets", "teal"
        )
        self.sync_action.clicked.connect(self.sync_report)

        actions = QGridLayout()
        actions.setHorizontalSpacing(12)
        actions.setVerticalSpacing(12)
        action_buttons = (manual, self.review_action, budgets, self.sync_action)
        for index, action_card in enumerate(action_buttons):
            actions.addWidget(action_card, index // 2, index % 2)
        self.category_chart = SpendingChartCard()
        overview_heading = QLabel("Your overview")
        overview_heading.setObjectName("sectionHeading")
        overview_subtitle = QLabel("The useful numbers, without the noise.")
        overview_subtitle.setObjectName("sectionSubtitle")
        overview_header = QVBoxLayout()
        overview_header.setSpacing(3)
        overview_header.addWidget(overview_heading)
        overview_header.addWidget(overview_subtitle)
        recent_heading = QLabel("Recent activity")
        recent_heading.setObjectName("sectionHeading")
        recent_subtitle = QLabel("Your latest confirmed spending will appear here.")
        recent_subtitle.setObjectName("sectionSubtitle")
        recent_header = QVBoxLayout()
        recent_header.setSpacing(3)
        recent_header.addWidget(recent_heading)
        recent_header.addWidget(recent_subtitle)
        self.recent = QTableWidget(0, 4)
        self.recent.setHorizontalHeaderLabels(["Date", "Merchant", "Amount", ""])
        self.recent.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.recent.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.recent.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.recent.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.recent.setColumnWidth(3, 104)
        self.recent.verticalHeader().setVisible(False)
        self.recent.setShowGrid(False)
        self.recent.setAlternatingRowColors(True)
        self.recent.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.recent.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recent.setMinimumHeight(190)
        self.recent.setAccessibleName("Recent confirmed expenses")
        self.recent.cellDoubleClicked.connect(lambda row, _column: self._edit_recent(row))

        empty_title = QLabel("A fresh start")
        empty_title.setObjectName("emptyTitle")
        empty_copy = QLabel(
            "Import a receipt or add an expense, and your recent activity will begin to take shape."
        )
        empty_copy.setObjectName("sectionSubtitle")
        empty_copy.setWordWrap(True)
        empty_layout = QVBoxLayout()
        empty_layout.setContentsMargins(24, 22, 24, 22)
        empty_layout.setSpacing(5)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_copy)
        empty_layout.addStretch()
        self.recent_empty = QFrame()
        self.recent_empty.setObjectName("emptyState")
        self.recent_empty.setMinimumHeight(120)
        self.recent_empty.setLayout(empty_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 36, 0, 44)
        layout.setSpacing(18)
        layout.addLayout(navigation)
        layout.addLayout(opening)
        layout.addSpacing(8)
        layout.addLayout(overview_header)
        layout.addLayout(cards)
        layout.addWidget(self.category_chart)
        layout.addSpacing(8)
        layout.addLayout(actions)
        layout.addSpacing(12)
        layout.addLayout(recent_header)
        layout.addWidget(self.recent_empty)
        layout.addWidget(self.recent)
        content = QWidget()
        content.setObjectName("contentColumn")
        content.setMaximumWidth(1120)
        content.setLayout(layout)
        shell = QWidget()
        shell.setObjectName("dashboardShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(36, 0, 36, 0)
        shell_layout.addStretch()
        shell_layout.addWidget(content, 1)
        shell_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(shell)
        self.setCentralWidget(scroll)

    def refresh(self) -> None:
        try:
            snapshot = self.controller.dashboard()
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Dashboard could not be refreshed", str(error))
            return
        currency = self.controller.config.default_currency
        self.cards["spending"].value.setText(money_text(snapshot.month_spending_minor, currency))
        if snapshot.budget_minor is None:
            budget = "Not set"
        else:
            remaining = snapshot.budget_minor - snapshot.month_spending_minor
            budget = f"{money_text(remaining, currency)} left"
        self.cards["budget"].value.setText(budget)
        self.cards["inbox"].value.setText(str(snapshot.inbox_count))
        if snapshot.inbox_count:
            receipt_word = "receipt" if snapshot.inbox_count == 1 else "receipts"
            self.cards["inbox"].detail.setText("Click to process now")
            self.process_button.setText(
                f"Process {snapshot.inbox_count} waiting {receipt_word}"
            )
            self.process_button.show()
        else:
            self.cards["inbox"].detail.setText("Waiting to be processed")
            self.process_button.hide()
        self.cards["review"].value.setText(str(snapshot.review_count))
        self.cards["sync"].value.setText(str(snapshot.pending_sync))
        review_label = (
            f"Review receipts ({snapshot.review_count})"
            if snapshot.review_count
            else "Review receipts"
        )
        self.review_action.set_title(review_label)
        sync_label = (
            f"Sync report ({snapshot.pending_sync})" if snapshot.pending_sync else "Sync report"
        )
        self.sync_action.set_title(sync_label)
        self.category_chart.set_values(snapshot.category_spending, currency)
        self.report_button.setText(
            "Open Google Sheet" if self.controller.report_url() else "Connect Google"
        )
        storage_text = (
            f"{format_bytes(snapshot.storage_bytes)} of "
            f"{format_bytes(snapshot.disk_capacity_bytes)}"
        )
        self.cards["storage"].value.setText(storage_text)
        self.cards["storage"].setToolTip(
            f"SpendScope uses {format_bytes(snapshot.storage_bytes)} on this disk. "
            f"The disk has {format_bytes(snapshot.disk_capacity_bytes)} total capacity and "
            f"{format_bytes(snapshot.disk_free_bytes)} currently free."
        )
        self.recent.setRowCount(len(snapshot.recent_receipts))
        has_recent = bool(snapshot.recent_receipts)
        self.recent.setVisible(has_recent)
        self.recent_empty.setVisible(not has_recent)
        for row, (receipt_id, when, merchant, total, receipt_currency) in enumerate(
            snapshot.recent_receipts
        ):
            for column, value in enumerate((when, merchant, money_text(total, receipt_currency))):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, receipt_id)
                self.recent.setItem(row, column, item)
            edit = QPushButton("Edit")
            edit.setObjectName("tableAction")
            edit.setMinimumWidth(76)
            edit.setCursor(Qt.CursorShape.PointingHandCursor)
            edit.setAccessibleName(f"Edit {merchant} expense")
            edit.clicked.connect(lambda _checked=False, selected=row: self._edit_recent(selected))
            self.recent.setCellWidget(row, 3, edit)

    def _edit_recent(self, row: int) -> None:
        item = self.recent.item(row, 0)
        if item is None:
            return
        receipt_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(receipt_id, int):
            return
        dialog = ReviewDialog(self.controller, self, confirmed_receipt_id=receipt_id)
        dialog.receipt_resolved.connect(self.refresh)
        dialog.exec()
        self.refresh()

    def _advance_prompt(self) -> None:
        self.prompt_index = (self.prompt_index + 1) % len(FINANCIAL_PROMPTS)
        self.prompt.setText(f"“{FINANCIAL_PROMPTS[self.prompt_index]}”")

    def choose_receipts(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            "Import receipt files",
            filter="Receipts (*.jpg *.jpeg *.png *.pdf)",
        )
        if selected:
            self.import_receipts([Path(value) for value in selected])

    def import_receipts(self, sources: list[Path]) -> None:
        imported, rejected = self.controller.import_receipts(sources)
        if rejected:
            QMessageBox.warning(
                self,
                "Some files were not imported",
                "\n".join(rejected),
            )
        if imported:
            self.statusBar().showMessage(f"Imported {len(imported)} receipt file(s)", 5000)
            self.process_receipts()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if urls and all(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        sources = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        self.import_receipts(sources)
        event.acceptProposedAction()

    def process_receipts(self) -> None:
        if self._processing_active:
            return
        self._processing_active = True
        self.process_button.setEnabled(False)
        self.progress = QProgressDialog("Reading receipts from Inbox…", "", 0, 0, self)
        self.progress.setWindowTitle("Processing receipts")
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)
        job = BackgroundJob(self._process_inbox)
        job.signals.finished.connect(self._processing_finished)
        job.signals.failed.connect(self._processing_failed)
        self.thread_pool.start(job)

    def _process_inbox(self) -> ProcessingSummary:
        engine = create_sqlite_engine(self.controller.config.database_path)
        confirmed = 0
        needs_review = 0
        duplicates = 0
        invalid = 0
        failed = 0
        errors: list[str] = []
        try:
            with session_scope(engine) as session:
                storage = StoragePipeline(self.controller.config, session)
                intake = storage.scan_and_register()
                service = ReceiptProcessingService(
                    self.controller.config,
                    session,
                    ReceiptTextExtractor(
                        self.controller.config,
                        TesseractOcrEngine(self.controller.config.ocr_executable),
                    ),
                )
                for entry in intake:
                    if (
                        entry.status in {IntakeStatus.ACCEPTED, IntakeStatus.RESUMED}
                        and entry.record_id
                    ):
                        result = service.process(entry.path, entry.record_id)
                        if result.status == "high":
                            confirmed += 1
                        elif result.status in {"medium", "low"}:
                            needs_review += 1
                        elif result.status == "duplicate":
                            duplicates += 1
                        else:
                            failed += 1
                            errors.append(
                                f"{entry.path.name}: {result.reason or 'processing failed'}"
                            )
                    elif entry.status is IntakeStatus.DUPLICATE:
                        existing = storage.repository.get(entry.record_id or 0)
                        if existing is not None and existing.processing_status == "failed":
                            result = service.process(entry.path, existing.id)
                            if result.status == "failed":
                                failed += 1
                                errors.append(
                                    f"{entry.path.name}: {result.reason or 'processing failed'}"
                                )
                            else:
                                needs_review += 1
                        elif existing is not None and existing.processing_status == "needs_review":
                            result = service.reprocess_needs_review(entry.path, existing.id)
                            if result.status in {"high", "medium", "low", "failed"}:
                                needs_review += 1
                            else:
                                duplicates += 1
                        else:
                            duplicates += 1
                    else:
                        invalid += 1
                        errors.append(f"{entry.path.name}: {entry.reason or 'invalid file'}")
            return ProcessingSummary(
                confirmed,
                needs_review,
                duplicates,
                invalid,
                failed,
                tuple(errors),
            )
        finally:
            engine.dispose()

    def _processing_finished(self, result: object) -> None:
        self._processing_active = False
        self.process_button.setEnabled(True)
        if self.progress is not None:
            self.progress.close()
        summary = cast(ProcessingSummary, result)
        lines = [
            f"Confirmed automatically: {summary.confirmed}",
            f"Ready for review: {summary.needs_review}",
            f"Duplicates skipped: {summary.duplicates}",
            f"Invalid files: {summary.invalid}",
            f"Failed: {summary.failed}",
        ]
        if summary.errors:
            lines.extend(("", "Details:", *summary.errors[:8]))
        QMessageBox.information(
            self,
            "Receipt processing complete",
            "\n".join(lines),
        )
        self.refresh()
        if summary.needs_review:
            self.open_review()

    def _processing_failed(self, message: str) -> None:
        self._processing_active = False
        self.process_button.setEnabled(True)
        if self.progress is not None:
            self.progress.close()
        QMessageBox.critical(self, "Receipt processing failed", message)

    def _auto_process_new_inbox_files(self) -> None:
        """Notice files synced into Inbox without requiring a manual menu action."""
        if self._processing_active:
            return
        inbox = self.controller.config.directory_paths()["inbox"]
        if not inbox.exists():
            return
        files = tuple(
            sorted(
                (
                    str(path.resolve()),
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                )
                for path in inbox.iterdir()
                if path.is_file()
            )
        )
        snapshot = self.controller.dashboard()
        if snapshot.inbox_count and files != self._last_auto_process_signature:
            self._last_auto_process_signature = files
            self.process_receipts()

    def sync_report(self) -> None:
        self.progress = QProgressDialog("Synchronizing the report…", "", 0, 0, self)
        self.progress.setWindowTitle("Report sync")
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)
        job = BackgroundJob(self.controller.sync_report)
        job.signals.finished.connect(self._sync_finished)
        job.signals.failed.connect(self._sync_failed)
        self.thread_pool.start(job)

    def _sync_finished(self, result: object) -> None:
        if self.progress is not None:
            self.progress.close()
        error = getattr(result, "error", None)
        if error:
            QMessageBox.warning(self, "Report sync", str(error))
        else:
            QMessageBox.information(self, "Report sync", "The report is up to date.")
        self.refresh()

    def _sync_failed(self, _message: str) -> None:
        if self.progress is not None:
            self.progress.close()
        QMessageBox.warning(
            self,
            "Report could not sync",
            "SpendScope could not update Google Sheets just now. Your spending is safely "
            "saved on this Mac; please wait a moment and try again.",
        )

    def open_report(self) -> None:
        url = self.controller.report_url()
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.information(
                self,
                "Set up your Google report",
                "Open Settings and choose “Connect Google Drive.” SpendScope will create its "
                "Drive folder and spending report for you.",
            )
            self.open_settings()

    def open_manual(self) -> None:
        if ManualEntryDialog(self.controller, self).exec():
            self.refresh()

    def open_review(self) -> None:
        dialog = ReviewDialog(self.controller, self)
        dialog.receipt_resolved.connect(self.refresh)
        dialog.exec()
        self.refresh()

    def open_budgets(self) -> None:
        BudgetsDialog(self.controller, self).exec()
        self.refresh()

    def open_storage(self) -> None:
        StorageDialog(self.controller, self).exec()
        self.refresh()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.controller, self)
        if dialog.exec():
            self.appearance_actions[self.controller.config.appearance].setChecked(True)
        # Google connection changes take effect immediately, even if no appearance or
        # currency settings were saved.
        self.refresh()

    def _open_folder(self, name: str) -> None:
        path: Path = self.controller.config.directory_paths()[name]
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_receipts(self) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.controller.config.directory_paths()["receipts"]))
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self.controller.close()
        super().closeEvent(event)
