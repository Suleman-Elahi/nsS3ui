"""Custom item delegates for table views."""
from PySide6.QtWidgets import (
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QApplication,
    QStyle,
    QStyleOptionButton,
)
from PySide6.QtCore import QModelIndex, Qt, QRect, Signal, QSize, QEvent
from PySide6.QtGui import QPainter, QColor
from nss3ui.transfer_manager import TransferStatus, TransferDirection


class ProgressBarDelegate(QStyledItemDelegate):
    """Renders a progress bar in the Progress column of the transfer table."""

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple):
            super().paint(painter, option, index)
            return

        done, total = data
        if total <= 0:
            super().paint(painter, option, index)
            return

        pct = int(done / total * 100)

        # Draw selection background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#094771"))

        # Draw progress bar
        bar_rect = option.rect.adjusted(4, 6, -4, -6)
        opt = QStyleOptionProgressBar()
        opt.rect = bar_rect
        opt.minimum = 0
        opt.maximum = 100
        opt.progress = pct
        opt.text = f"{pct}%"
        opt.textVisible = True
        opt.textAlignment = Qt.AlignmentFlag.AlignCenter
        QApplication.style().drawControl(QStyle.ControlElement.CE_ProgressBar, opt, painter)

    def sizeHint(self, option, index: QModelIndex):
        sh = super().sizeHint(option, index)
        return sh.__class__(max(sh.width(), 120), max(sh.height(), 28))


class ActionButtonsDelegate(QStyledItemDelegate):
    """Paint lightweight action buttons and emit click events without index widgets."""

    action_requested = Signal(str, str)  # action, transfer_id

    def _actions_for(self, item) -> list[str]:
        if item.status == TransferStatus.RUNNING:
            return ["Pause", "Cancel"]
        if item.status == TransferStatus.PAUSED:
            return ["Resume", "Cancel"]
        if item.status in (TransferStatus.FAILED, TransferStatus.CANCELLED):
            return ["Retry"]
        if item.status == TransferStatus.COMPLETED and item.direction == TransferDirection.DOWNLOAD:
            return ["Show Folder"]
        return []

    def _button_rects(self, option, labels: list[str]) -> list[tuple[str, QRect]]:
        if not labels:
            return []
        style = QApplication.style()
        x = option.rect.left() + 4
        y = option.rect.top() + 3
        h = max(20, option.rect.height() - 6)
        out: list[tuple[str, QRect]] = []
        for label in labels:
            w = max(56, option.fontMetrics.horizontalAdvance(label) + 20)
            r = QRect(x, y, w, h)
            out.append((label, r))
            x += w + 4
            if x > option.rect.right():
                break
        return out

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            return super().paint(painter, option, index)

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        labels = self._actions_for(item)
        style = QApplication.style()
        for label, rect in self._button_rects(option, labels):
            btn = QStyleOptionButton()
            btn.rect = rect
            btn.text = label
            btn.state = QStyle.StateFlag.State_Enabled
            style.drawControl(QStyle.ControlElement.CE_PushButton, btn, painter)

    def editorEvent(self, event, model, option, index: QModelIndex) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            return False
        for label, rect in self._button_rects(option, self._actions_for(item)):
            if rect.contains(event.pos()):
                self.action_requested.emit(label, item.id)
                return True
        return False

    def sizeHint(self, option, index: QModelIndex):
        sh = super().sizeHint(option, index)
        return QSize(max(sh.width(), 180), max(sh.height(), 28))
