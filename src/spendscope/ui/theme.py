"""Application-wide light and dark themes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from spendscope.config import Appearance


class Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class ThemeColors:
    window: str
    surface: str
    surface_alt: str
    text: str
    muted: str
    border: str
    button: str
    button_hover: str
    button_pressed: str
    accent: str
    accent_hover: str
    accent_border: str
    accent_soft: str
    warm_surface: str
    action_teal: str
    action_teal_hover: str
    action_gold: str
    action_gold_hover: str
    action_coral: str
    action_coral_hover: str
    selection_text: str
    disabled_text: str
    disabled_surface: str
    error: str


THEMES = {
    Theme.LIGHT: ThemeColors(
        window="#f5f7fb",
        surface="#ffffff",
        surface_alt="#eef2f6",
        text="#16202a",
        muted="#52606d",
        border="#cbd5df",
        button="#ffffff",
        button_hover="#edf3f7",
        button_pressed="#dfe7ee",
        accent="#147a66",
        accent_hover="#106451",
        accent_border="#0d5948",
        accent_soft="#e5f4ef",
        warm_surface="#fff8e9",
        action_teal="#d9f2e9",
        action_teal_hover="#c5eadd",
        action_gold="#fff0bd",
        action_gold_hover="#f9e39a",
        action_coral="#fbe0dc",
        action_coral_hover="#f5cbc5",
        selection_text="#ffffff",
        disabled_text="#7b8794",
        disabled_surface="#e5eaf0",
        error="#b42318",
    ),
    Theme.DARK: ThemeColors(
        window="#121820",
        surface="#1b2430",
        surface_alt="#253140",
        text="#f2f5f7",
        muted="#b6c1cc",
        border="#465466",
        button="#273444",
        button_hover="#334256",
        button_pressed="#1f2a37",
        accent="#2b9b84",
        accent_hover="#35ad94",
        accent_border="#57c2ad",
        accent_soft="#193b35",
        warm_surface="#30291d",
        action_teal="#17483f",
        action_teal_hover="#1d5a4e",
        action_gold="#4d3d1c",
        action_gold_hover="#624d22",
        action_coral="#4b2d34",
        action_coral_hover="#603740",
        selection_text="#ffffff",
        disabled_text="#8995a3",
        disabled_surface="#222c38",
        error="#ff8a80",
    ),
}


def system_theme(application: QApplication) -> Theme:
    """Return the theme currently requested by the operating system."""
    if application.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        return Theme.DARK
    return Theme.LIGHT


def _palette(colors: ThemeColors) -> QPalette:
    palette = QPalette()
    role_colors = {
        QPalette.ColorRole.Window: colors.window,
        QPalette.ColorRole.WindowText: colors.text,
        QPalette.ColorRole.Base: colors.surface,
        QPalette.ColorRole.AlternateBase: colors.surface_alt,
        QPalette.ColorRole.ToolTipBase: colors.surface_alt,
        QPalette.ColorRole.ToolTipText: colors.text,
        QPalette.ColorRole.Text: colors.text,
        QPalette.ColorRole.Button: colors.button,
        QPalette.ColorRole.ButtonText: colors.text,
        QPalette.ColorRole.BrightText: colors.error,
        QPalette.ColorRole.Highlight: colors.accent,
        QPalette.ColorRole.HighlightedText: colors.selection_text,
        QPalette.ColorRole.Link: colors.accent_hover,
        QPalette.ColorRole.PlaceholderText: colors.muted,
    }
    for role, value in role_colors.items():
        palette.setColor(QPalette.ColorGroup.All, role, QColor(value))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(colors.disabled_text)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(colors.disabled_text)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(colors.disabled_text)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(colors.disabled_surface)
    )
    return palette


def _stylesheet(colors: ThemeColors) -> str:
    return f"""
        QMainWindow, QDialog, QMessageBox, QProgressDialog {{
            background-color: {colors.window};
            color: {colors.text};
        }}
        QWidget {{ color: {colors.text}; font-size: 14px; }}
        QLabel {{ background-color: transparent; color: {colors.text}; }}
        QLabel#brandLabel {{
            color: {colors.accent};
            font-size: 11px;
            font-weight: 700;
        }}
        QLabel#pageHeading {{ font-size: 34px; font-weight: 700; }}
        QLabel#pageSubtitle {{ color: {colors.muted}; font-size: 15px; }}
        QLabel#secondaryText, QLabel#metricHeading {{ color: {colors.muted}; }}
        QLabel#metricHeading {{ font-size: 12px; font-weight: 600; }}
        QLabel#metricValue {{ font-size: 22px; font-weight: 700; }}
        QLabel#metricDetail {{ color: {colors.muted}; font-size: 11px; }}
        QLabel#sectionHeading {{ font-size: 19px; font-weight: 700; }}
        QLabel#sectionSubtitle {{ color: {colors.muted}; font-size: 13px; }}
        QLabel#emptyTitle {{ font-size: 16px; font-weight: 650; }}
        QFrame#heroPanel {{
            background-color: {colors.surface};
            border: 1px solid {colors.border};
            border-radius: 18px;
        }}
        QFrame#importPanel {{
            background-color: {colors.accent_soft};
            border: 1px solid {colors.accent_border};
            border-radius: 14px;
        }}
        QFrame#emptyState {{
            background-color: {colors.warm_surface};
            border: 1px solid {colors.border};
            border-radius: 14px;
        }}
        QFrame#metricCard {{
            background-color: {colors.surface};
            border: 1px solid {colors.border};
            border-radius: 14px;
        }}
        QFrame#metricAccent {{
            background-color: {colors.accent};
            border: 0;
            border-radius: 2px;
        }}
        QPushButton {{
            min-height: 36px;
            padding: 4px 14px;
            color: {colors.text};
            background-color: {colors.button};
            border: 1px solid {colors.border};
            border-radius: 9px;
            font-weight: 550;
        }}
        QPushButton:hover {{ background-color: {colors.button_hover}; }}
        QPushButton:pressed {{ background-color: {colors.button_pressed}; }}
        QPushButton:disabled {{
            color: {colors.disabled_text};
            background-color: {colors.disabled_surface};
            border-color: {colors.border};
        }}
        QPushButton#primaryAction {{
            color: white;
            background-color: {colors.accent};
            border-color: {colors.accent_border};
            min-height: 40px;
            font-weight: 700;
        }}
        QPushButton#primaryAction:hover {{ background-color: {colors.accent_hover}; }}
        QFrame#actionCard {{
            border-radius: 16px;
            border: 1px solid {colors.border};
        }}
        QFrame#actionCard[tone="teal"] {{
            background-color: {colors.action_teal};
            border-color: {colors.accent};
        }}
        QFrame#actionCard[tone="teal"]:hover {{
            background-color: {colors.action_teal_hover};
            border-color: {colors.accent_border};
        }}
        QFrame#actionCard[tone="gold"] {{
            background-color: {colors.action_gold};
            border-color: #c79326;
        }}
        QFrame#actionCard[tone="gold"]:hover {{
            background-color: {colors.action_gold_hover};
            border-color: #e0a72f;
        }}
        QFrame#actionCard[tone="coral"] {{
            background-color: {colors.action_coral};
            border-color: #c96962;
        }}
        QFrame#actionCard[tone="coral"]:hover {{
            background-color: {colors.action_coral_hover};
            border-color: #e17b72;
        }}
        QLabel#actionTitle {{
            color: white;
            background: transparent;
            border: 0;
            font-size: 20px;
            font-weight: 750;
        }}
        QLabel#actionSubtitle {{
            color: rgba(255, 255, 255, 0.82);
            background: transparent;
            border: 0;
            font-size: 13px;
            font-weight: 500;
        }}
        QLabel#actionArrow {{
            color: white;
            background: rgba(255, 255, 255, 0.14);
            border-radius: 14px;
            padding: 1px 8px;
            font-size: 18px;
            font-weight: 700;
        }}
        QFrame#chartCard, QFrame#dialogPanel {{
            color: {colors.text};
            background-color: {colors.surface};
            border: 1px solid {colors.border};
            border-radius: 16px;
        }}
        QLabel#dialogTitle {{
            color: {colors.text};
            font-size: 24px;
            font-weight: 750;
        }}
        QLabel#dialogSubtitle {{ color: {colors.muted}; font-size: 13px; }}
        QPushButton#navigationAction {{
            min-height: 32px;
            padding: 2px 13px;
            color: {colors.text};
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 9px;
            font-weight: 600;
        }}
        QPushButton#navigationAction:hover {{
            color: {colors.text};
            background-color: {colors.button_hover};
            border-color: {colors.border};
        }}
        QPushButton#navigationAction:pressed {{
            background-color: {colors.accent_soft};
            border-color: {colors.accent_border};
        }}
        QPushButton#tableAction {{
            min-height: 26px;
            padding: 1px 14px;
            color: {colors.accent};
            background-color: {colors.accent_soft};
            border-color: {colors.accent_border};
            border-radius: 9px;
            font-weight: 700;
        }}
        QPushButton#tableAction:hover {{
            color: white;
            background-color: {colors.accent};
        }}
        QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit,
        QListWidget, QTableWidget {{
            color: {colors.text};
            background-color: {colors.surface};
            selection-color: {colors.selection_text};
            selection-background-color: {colors.accent};
            border: 1px solid {colors.border};
            border-radius: 4px;
        }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
            min-height: 28px;
            padding: 2px 6px;
        }}
        QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled,
        QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled {{
            color: {colors.disabled_text};
            background-color: {colors.disabled_surface};
        }}
        QHeaderView::section {{
            color: {colors.text};
            background-color: {colors.surface_alt};
            border: 0;
            border-right: 1px solid {colors.border};
            border-bottom: 1px solid {colors.border};
            padding: 9px;
            font-weight: 600;
        }}
        QTableWidget {{
            alternate-background-color: {colors.surface_alt};
            gridline-color: transparent;
            padding: 3px;
        }}
        QTableWidget::item {{ padding: 7px; border: 0; }}
        QTableCornerButton::section {{
            background-color: {colors.surface_alt};
            border: 1px solid {colors.border};
        }}
        QMenuBar, QMenu, QStatusBar {{
            color: {colors.text};
            background-color: {colors.surface};
        }}
        QStatusBar {{ color: {colors.muted}; border-top: 1px solid {colors.border}; }}
        QMenuBar::item:selected, QMenu::item:selected {{
            color: {colors.selection_text};
            background-color: {colors.accent};
        }}
        QToolTip {{
            color: {colors.text};
            background-color: {colors.surface_alt};
            border: 1px solid {colors.border};
        }}
    """


def apply_theme(application: QApplication, theme: Theme) -> None:
    """Apply a complete, embedded theme to all current and future widgets."""
    colors = THEMES[theme]
    application.setProperty("spendscopeTheme", theme.value)
    application.setPalette(_palette(colors))
    application.setStyleSheet(_stylesheet(colors))


def apply_system_theme(application: QApplication) -> None:
    apply_theme(application, system_theme(application))


def apply_appearance(application: QApplication, appearance: Appearance) -> None:
    """Apply a saved preference, resolving System against the current OS theme."""
    application.setProperty("spendscopeAppearance", appearance.value)
    if appearance is Appearance.SYSTEM:
        apply_system_theme(application)
    else:
        apply_theme(application, Theme(appearance.value))


def enable_system_theme(application: QApplication) -> None:
    """Start with the OS theme and keep following it while System is selected."""
    application.setStyle("Fusion")
    apply_appearance(application, Appearance.SYSTEM)
    application.styleHints().colorSchemeChanged.connect(
        lambda _scheme: (
            apply_system_theme(application)
            if application.property("spendscopeAppearance") == Appearance.SYSTEM.value
            else None
        )
    )
