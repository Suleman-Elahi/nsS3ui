"""QAbstractTableModel for the transfer queue panel."""
from __future__ import annotations
import humanize
from typing import Any
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from nss3ui.transfer_manager import TransferItem, TransferStatus, TransferDirection

COLUMNS = ["File", "Direction", "Progress", "Speed", "ETA", "Status", "Actions"]
COL_FILE = 0
COL_DIR = 1
COL_PROGRESS = 2
COL_SPEED = 3
COL_ETA = 4
COL_STATUS = 5
COL_ACTIONS = 6

STATUS_COLORS = {
    TransferStatus.QUEUED: "#9d9d9d",
    TransferStatus.RUNNING: "#4ec9b0",
    TransferStatus.COMPLETED: "#89d185",
    TransferStatus.FAILED: "#f48771",
    TransferStatus.CANCELLED: "#ce9178",
    TransferStatus.PAUSED: "#dcdcaa",
}


class TransferTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[TransferItem] = []
        self._id_to_row: dict[str, int] = {}

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

        if role == Qt.ItemDataRole.ForegroundRole and col == COL_STATUS:
            return QColor(STATUS_COLORS.get(item.status, "#d4d4d4"))

        if role == Qt.ItemDataRole.UserRole:
            if col == COL_PROGRESS:
                # Return (done, total) for delegate
                return (item.bytes_done, item.total_bytes)
            return item

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_PROGRESS, COL_SPEED, COL_ETA):
                return Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None

    def add_transfer(self, item: TransferItem) -> None:
        row = 0
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.insert(0, item)
        self._id_to_row = {it.id: idx for idx, it in enumerate(self._items)}
        self.endInsertRows()

    def update_transfer(self, transfer_id: str) -> None:
        row = self._id_to_row.get(transfer_id)
        if row is not None:
            self.dataChanged.emit(
                self.index(row, 0),
                self.index(row, len(COLUMNS) - 1),
            )

    def _display(self, item: TransferItem, col: int) -> str:
        if col == COL_FILE:
            return item.filename
        if col == COL_DIR:
            return item.direction.value
        if col == COL_PROGRESS:
            if item.total_bytes > 0:
                pct = int(item.bytes_done / item.total_bytes * 100)
                return f"{pct}%"
            return "—"
        if col == COL_SPEED:
            if item.status == TransferStatus.RUNNING and item.speed > 0:
                return humanize.naturalsize(item.speed, binary=True) + "/s"
            return "—"
        if col == COL_ETA:
            if item.status == TransferStatus.RUNNING and item.speed > 0 and item.total_bytes > 0:
                remaining = item.total_bytes - item.bytes_done
                secs = remaining / item.speed
                return _format_eta(secs)
            return "—"
        if col == COL_STATUS:
            return item.status.name.capitalize()
        return ""


def _format_eta(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h {(secs % 3600) // 60}m"
