"""Settings dialog — theme selection and other preferences."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton, QDialogButtonBox,
    QGroupBox, QWidget, QSpinBox
)
from PySide6.QtCore import Qt, Signal
from nss3ui.config import get_theme, set_theme, get_transfer_tuning, set_transfer_tuning


class SettingsDialog(QDialog):
    theme_changed = Signal(str)   # "dark" or "light"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(360)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Appearance group
        appearance = QGroupBox("Appearance")
        form = QFormLayout(appearance)
        form.setSpacing(10)

        self._theme_combo = QComboBox()
        self._theme_combo.addItem("🌙  Dark", "dark")
        self._theme_combo.addItem("☀️  Light", "light")

        current = get_theme()
        idx = self._theme_combo.findData(current)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

        form.addRow("Theme:", self._theme_combo)
        layout.addWidget(appearance)

        transfer = QGroupBox("Transfers")
        tform = QFormLayout(transfer)
        t = get_transfer_tuning()
        self._concurrency = QSpinBox()
        self._concurrency.setRange(1, 64)
        self._concurrency.setValue(int(t["max_concurrency"]))
        self._chunk_mb = QSpinBox()
        self._chunk_mb.setRange(5, 256)
        self._chunk_mb.setValue(int(t["multipart_chunksize_mb"]))
        self._threshold_mb = QSpinBox()
        self._threshold_mb.setRange(5, 256)
        self._threshold_mb.setValue(int(t["multipart_threshold_mb"]))
        tform.addRow("Max concurrency:", self._concurrency)
        tform.addRow("Part size (MB):", self._chunk_mb)
        tform.addRow("Multipart threshold (MB):", self._threshold_mb)
        layout.addWidget(transfer)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        theme = self._theme_combo.currentData()
        set_theme(theme)
        set_transfer_tuning(
            {
                "max_concurrency": int(self._concurrency.value()),
                "multipart_chunksize_mb": int(self._chunk_mb.value()),
                "multipart_threshold_mb": int(self._threshold_mb.value()),
            }
        )
        self.theme_changed.emit(theme)
        self.accept()
