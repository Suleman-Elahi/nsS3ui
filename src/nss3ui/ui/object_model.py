"""
QAbstractTableModel for S3 objects.
Supports lazy loading — append pages without rebuilding.
"""
from __future__ import annotations
import humanize
from datetime import datetime, timezone
from typing import Any, Optional
from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, Qt, QSortFilterProxyModel
)
from PySide6.QtGui import QColor
from nss3ui.ui.icons import file_icon, icon_folder
from nss3ui.config import get_theme

COLUMNS = ["Name", "Size", "Modified", "Storage Class", "Type"]
COL_NAME = 0
COL_SIZE = 1
COL_MODIFIED = 2
COL_STORAGE = 3
COL_TYPE = 4


class S3ObjectItem:
    """Unified representation of a folder prefix or an object."""

    __slots__ = ("key", "display_name", "size", "modified", "storage_class", "is_folder")

    def __init__(
        self,
        key: str,
        display_name: str,
        size: int = 0,
        modified: Optional[datetime] = None,
        storage_class: str = "",
        is_folder: bool = False,
    ):
        self.key = key
        self.display_name = display_name
        self.size = size
        self.modified = modified
        self.storage_class = storage_class
        self.is_folder = is_folder


class ObjectTableModel(QAbstractTableModel):
    """Model for the main object browser table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[S3ObjectItem] = []

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self._items[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(item, col)

        if role == Qt.ItemDataRole.DecorationRole and col == COL_NAME:
            return icon_folder() if item.is_folder else file_icon(item.key)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_NAME and get_theme() == "light":
                return QColor("#000000")
            if item.is_folder and get_theme() != "light":
                return QColor("#dcb67a")
            if col == COL_SIZE:
                return QColor("#9d9d9d")

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == COL_SIZE:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.UserRole:
            return item  # raw item for context menus etc.

        return None

    # ------------------------------------------------------------------
    # Data manipulation
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def append_page(self, objects: list[dict], prefixes: list[str]) -> None:
        """Append a page of results without full reset."""
        new_items: list[S3ObjectItem] = []
        folder_keys: set[str] = set()

        for prefix in prefixes:
            display = prefix.rstrip("/").rsplit("/", 1)[-1] + "/"
            folder_keys.add(prefix)
            new_items.append(S3ObjectItem(
                key=prefix,
                display_name=display,
                is_folder=True,
            ))

        for obj in objects:
            key: str = obj["Key"]
            # S3 folder markers are real zero-byte objects like "path/to/folder/".
            # Render them as folders and avoid duplicate rows when CommonPrefixes already has them.
            if key.endswith("/") and int(obj.get("Size", 0)) == 0:
                if key in folder_keys:
                    continue
                folder_keys.add(key)
                display = key.rstrip("/").rsplit("/", 1)[-1] + "/"
                new_items.append(S3ObjectItem(
                    key=key,
                    display_name=display,
                    is_folder=True,
                ))
                continue
            display = key.rsplit("/", 1)[-1] if "/" in key else key
            new_items.append(S3ObjectItem(
                key=key,
                display_name=display,
                size=obj.get("Size", 0),
                modified=obj.get("LastModified"),
                storage_class=obj.get("StorageClass", "STANDARD"),
                is_folder=False,
            ))

        if not new_items:
            return

        first = len(self._items)
        last = first + len(new_items) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._items.extend(new_items)
        self.endInsertRows()

    def item_at(self, row: int) -> Optional[S3ObjectItem]:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def selected_items(self, rows: list[int]) -> list[S3ObjectItem]:
        return [self._items[r] for r in rows if 0 <= r < len(self._items)]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _display(self, item: S3ObjectItem, col: int) -> str:
        if col == COL_NAME:
            return item.display_name
        if col == COL_SIZE:
            if item.is_folder:
                return ""
            return humanize.naturalsize(item.size, binary=True)
        if col == COL_MODIFIED:
            if item.modified is None:
                return ""
            dt = item.modified
            if dt.tzinfo is not None:
                dt = dt.astimezone(tz=None).replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d  %H:%M")
        if col == COL_STORAGE:
            return item.storage_class if not item.is_folder else ""
        if col == COL_TYPE:
            if item.is_folder:
                return "Folder"
            ext = item.key.rsplit(".", 1)[-1].upper() if "." in item.key else "File"
            return f"{ext} File"
        return ""


def make_proxy(source: ObjectTableModel) -> QSortFilterProxyModel:
    """Wrap model in a sort/filter proxy."""
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    proxy.setFilterKeyColumn(COL_NAME)
    proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    return proxy
