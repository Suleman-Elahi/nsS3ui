"""
Application stylesheets — dark and light themes.
All panel headers, toolbars, and special widgets are styled via objectName
selectors so the theme applies everywhere without any inline setStyleSheet().
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared structural rules (layout, fonts, sizes) — no colors here
# ---------------------------------------------------------------------------
_BASE = """
QWidget {
    font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical   { height: 1px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QHeaderView::section {
    padding: 4px 8px;
    font-weight: 600;
    font-size: 12px;
    border: none;
}
QTableView::item { padding: 3px 6px; }
QTabBar::tab { padding: 6px 16px; border: none; border-bottom: 2px solid transparent; }
QStatusBar::item { border: none; }
QProgressBar { border: none; border-radius: 3px; height: 6px; text-align: center; }
QProgressBar::chunk { border-radius: 3px; }
QScrollBar { margin: 0; }
QScrollBar:vertical  { width: 10px; }
QScrollBar:horizontal { height: 10px; }
QScrollBar::handle { border-radius: 5px; min-height: 20px; min-width: 20px; }
QMenu::item { padding: 7px 20px 7px 26px; min-height: 18px; }
QMenu::icon { padding-left: 8px; }

/* Panel section headers (BUCKETS / TRANSFERS / PREVIEW) */
QWidget#panelHeader {
    border-bottom: 1px solid;
}
QLabel#panelTitle {
    letter-spacing: 1px;
    font-size: 11px;
}

/* Object browser toolbar strip */
QWidget#browserToolbar {
    border-bottom: 1px solid;
}

/* Load-more link button */
QPushButton#loadMoreBtn {
    background: transparent;
    border: none;
    padding: 4px;
    font-size: 12px;
}

/* Placeholder / empty-state labels */
QLabel#placeholderLabel {
    font-size: 14px;
}

/* Clear Completed button in transfer panel */
QPushButton#clearBtn {
    border-radius: 3px;
    padding: 0 8px;
    font-size: 11px;
}

/* Metadata label in preview */
QLabel#metaLabel {
    padding: 12px;
    font-size: 12px;
}
"""

# ---------------------------------------------------------------------------
# DARK theme
# ---------------------------------------------------------------------------
_DARK_COLORS = """
QWidget          { background-color: #1e1e1e; color: #d4d4d4; }
QMainWindow      { background-color: #1e1e1e; }
QDialog          { background-color: #252526; color: #d4d4d4; }

/* Toolbar */
QToolBar {
    background-color: #2d2d2d;
    border-bottom: 1px solid #3c3c3c;
    spacing: 4px; padding: 2px 6px;
}
QToolBar QToolButton {
    background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 4px 8px; color: #d4d4d4;
}
QToolBar QToolButton:hover  { background-color: #3c3c3c; border-color: #555; }
QToolBar QToolButton:pressed { background-color: #0078d4; }

/* Panel headers */
QWidget#panelHeader  { background-color: #252526; border-color: #3c3c3c; }
QLabel#panelTitle    { color: #9d9d9d; }

/* Browser toolbar */
QWidget#browserToolbar { background-color: #2d2d2d; border-color: #3c3c3c; }

/* Sidebar list */
QListView, QTreeView, QListWidget {
    background-color: #252526; border: none; outline: none; color: #cccccc;
}
QListView::item, QTreeView::item, QListWidget::item {
    padding: 4px 8px; border-radius: 3px;
}
QListView::item:selected, QTreeView::item:selected, QListWidget::item:selected {
    background-color: #094771; color: #ffffff;
}
QListView::item:hover, QTreeView::item:hover, QListWidget::item:hover {
    background-color: #2a2d2e;
}

/* Main table */
QTableView {
    background-color: #1e1e1e; alternate-background-color: #252526;
    gridline-color: #2d2d2d; border: none; outline: none;
    selection-background-color: #094771; selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #2d2d2d; color: #9d9d9d;
    border-right: 1px solid #3c3c3c; border-bottom: 1px solid #3c3c3c;
}
QHeaderView::section:hover { background-color: #3c3c3c; color: #d4d4d4; }

/* Splitter */
QSplitter::handle { background-color: #3c3c3c; }

/* Status bar — neutral, not blue */
QStatusBar { background-color: #2d2d2d; color: #9d9d9d; font-size: 12px; }

/* Inputs */
QLineEdit {
    background-color: #3c3c3c; border: 1px solid #555; border-radius: 4px;
    padding: 4px 8px; color: #d4d4d4; selection-background-color: #0078d4;
}
QLineEdit:focus { border-color: #0078d4; }

/* Buttons */
QPushButton {
    background-color: #0e639c; color: #ffffff; border: none;
    border-radius: 4px; padding: 5px 14px; font-weight: 500;
}
QPushButton:hover   { background-color: #1177bb; }
QPushButton:pressed { background-color: #0d5a8e; }
QPushButton:disabled { background-color: #3c3c3c; color: #6d6d6d; }
QPushButton[flat="true"] {
    background-color: transparent; color: #d4d4d4; border: 1px solid #555;
}
QPushButton[flat="true"]:hover { background-color: #3c3c3c; }

/* Load-more */
QPushButton#loadMoreBtn { color: #4ec9b0; }
QPushButton#loadMoreBtn:hover { color: #9cdcfe; }

/* Clear Completed */
QPushButton#clearBtn {
    background: transparent; color: #9d9d9d; border: 1px solid #555;
}
QPushButton#clearBtn:hover { color: #d4d4d4; border-color: #888; }

/* ComboBox */
QComboBox {
    background-color: #3c3c3c; border: 1px solid #555; border-radius: 4px;
    padding: 4px 8px; color: #d4d4d4; min-width: 120px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #2d2d2d; border: 1px solid #555;
    selection-background-color: #094771; color: #d4d4d4;
}

/* Progress bar */
QProgressBar { background-color: #3c3c3c; color: transparent; }
QProgressBar::chunk { background-color: #0078d4; }

/* Scrollbars */
QScrollBar { background: #1e1e1e; }
QScrollBar::handle { background: #424242; }
QScrollBar::handle:hover { background: #686868; }

/* Menus */
QMenu {
    background-color: #2d2d2d; border: 1px solid #454545;
    border-radius: 4px; padding: 4px; color: #d4d4d4;
}
QMenu::item:selected { background-color: #094771; }
QMenu::separator { height: 1px; background: #454545; margin: 4px 0; }

/* Tabs */
QTabBar::tab { background-color: #2d2d2d; color: #9d9d9d; }
QTabBar::tab:selected { color: #d4d4d4; border-bottom-color: #0078d4; }
QTabBar::tab:hover { color: #d4d4d4; background-color: #3c3c3c; }

/* Labels */
QLabel { color: #d4d4d4; }
QLabel#panelTitle { color: #9d9d9d; }
QLabel#placeholderLabel { color: #6d6d6d; }
QLabel#metaLabel { color: #d4d4d4; }

/* Plain text */
QPlainTextEdit {
    background-color: #1e1e1e; color: #d4d4d4; border: none;
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace; font-size: 12px;
}

/* SpinBox */
QSpinBox {
    background-color: #3c3c3c; border: 1px solid #555; border-radius: 4px;
    padding: 4px 8px; color: #d4d4d4;
}
QSpinBox::up-button, QSpinBox::down-button { background: #555; border: none; width: 16px; }
"""

# ---------------------------------------------------------------------------
# LIGHT theme
# ---------------------------------------------------------------------------
_LIGHT_COLORS = """
QWidget          { background-color: #f3f3f3; color: #1e1e1e; }
QMainWindow      { background-color: #f3f3f3; }
QDialog          { background-color: #f3f3f3; color: #1e1e1e; }

/* Toolbar */
QToolBar {
    background-color: #e8e8e8;
    border-bottom: 1px solid #cccccc;
    spacing: 4px; padding: 2px 6px;
}
QToolBar QToolButton {
    background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 4px 8px; color: #1e1e1e;
}
QToolBar QToolButton:hover  { background-color: #d0d0d0; border-color: #aaa; }
QToolBar QToolButton:pressed { background-color: #0078d4; color: #fff; }

/* Panel headers */
QWidget#panelHeader  { background-color: #e0e0e0; border-color: #cccccc; }
QLabel#panelTitle    { color: #555555; }

/* Browser toolbar */
QWidget#browserToolbar { background-color: #e8e8e8; border-color: #cccccc; }

/* Sidebar list */
QListView, QTreeView, QListWidget {
    background-color: #fafafa; border: none; outline: none; color: #1e1e1e;
}
QListView::item, QTreeView::item, QListWidget::item {
    padding: 4px 8px; border-radius: 3px;
}
QListView::item:selected, QTreeView::item:selected, QListWidget::item:selected {
    background-color: #cce4f7; color: #000000;
}
QListView::item:hover, QTreeView::item:hover, QListWidget::item:hover {
    background-color: #e8f0fe;
}

/* Main table */
QTableView {
    background-color: #ffffff; alternate-background-color: #f7f7f7;
    gridline-color: #e0e0e0; border: none; outline: none;
    selection-background-color: #cce4f7; selection-color: #000000;
}
QHeaderView::section {
    background-color: #ececec; color: #555555;
    border-right: 1px solid #d0d0d0; border-bottom: 1px solid #d0d0d0;
}
QHeaderView::section:hover { background-color: #dcdcdc; color: #1e1e1e; }

/* Splitter */
QSplitter::handle { background-color: #cccccc; }

/* Status bar — neutral */
QStatusBar { background-color: #e8e8e8; color: #555555; font-size: 12px; }

/* Inputs */
QLineEdit {
    background-color: #ffffff; border: 1px solid #aaaaaa; border-radius: 4px;
    padding: 4px 8px; color: #1e1e1e; selection-background-color: #0078d4;
}
QLineEdit:focus { border-color: #0078d4; }

/* Buttons */
QPushButton {
    background-color: #0078d4; color: #ffffff; border: none;
    border-radius: 4px; padding: 5px 14px; font-weight: 500;
}
QPushButton:hover   { background-color: #106ebe; }
QPushButton:pressed { background-color: #005a9e; }
QPushButton:disabled { background-color: #cccccc; color: #888888; }
QPushButton[flat="true"] {
    background-color: transparent; color: #1e1e1e; border: 1px solid #aaa;
}
QPushButton[flat="true"]:hover { background-color: #e0e0e0; }

/* Load-more */
QPushButton#loadMoreBtn { color: #0078d4; }
QPushButton#loadMoreBtn:hover { color: #005a9e; }

/* Clear Completed */
QPushButton#clearBtn {
    background: transparent; color: #555555; border: 1px solid #aaaaaa;
}
QPushButton#clearBtn:hover { color: #1e1e1e; border-color: #666; }

/* ComboBox */
QComboBox {
    background-color: #ffffff; border: 1px solid #aaaaaa; border-radius: 4px;
    padding: 4px 8px; color: #1e1e1e; min-width: 120px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #ffffff; border: 1px solid #aaa;
    selection-background-color: #cce4f7; color: #1e1e1e;
}

/* Progress bar */
QProgressBar { background-color: #e0e0e0; color: transparent; }
QProgressBar::chunk { background-color: #0078d4; }

/* Scrollbars */
QScrollBar { background: #f3f3f3; }
QScrollBar::handle { background: #c0c0c0; }
QScrollBar::handle:hover { background: #999999; }

/* Menus */
QMenu {
    background-color: #ffffff; border: 1px solid #cccccc;
    border-radius: 4px; padding: 4px; color: #1e1e1e;
}
QMenu::item:selected { background-color: #cce4f7; }
QMenu::separator { height: 1px; background: #e0e0e0; margin: 4px 0; }

/* Tabs */
QTabBar::tab { background-color: #e8e8e8; color: #555555; }
QTabBar::tab:selected { color: #1e1e1e; border-bottom-color: #0078d4; }
QTabBar::tab:hover { color: #1e1e1e; background-color: #dcdcdc; }

/* Labels */
QLabel { color: #1e1e1e; }
QLabel#panelTitle { color: #555555; }
QLabel#placeholderLabel { color: #888888; }
QLabel#metaLabel { color: #1e1e1e; }

/* Plain text */
QPlainTextEdit {
    background-color: #ffffff; color: #1e1e1e; border: none;
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace; font-size: 12px;
}

/* SpinBox */
QSpinBox {
    background-color: #ffffff; border: 1px solid #aaaaaa; border-radius: 4px;
    padding: 4px 8px; color: #1e1e1e;
}
QSpinBox::up-button, QSpinBox::down-button { background: #ddd; border: none; width: 16px; }
"""

DARK = _BASE + _DARK_COLORS
LIGHT = _BASE + _LIGHT_COLORS

# Backward compat
STYLESHEET = DARK


def get_stylesheet(theme: str = "dark") -> str:
    return LIGHT if theme == "light" else DARK
