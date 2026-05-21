"""Custom item delegates for table views."""
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionProgressBar, QApplication, QStyle
from PySide6.QtCore import QModelIndex, Qt, QRect
from PySide6.QtGui import QPainter, QColor


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
