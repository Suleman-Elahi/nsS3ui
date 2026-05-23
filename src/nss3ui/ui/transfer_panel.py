"""Transfer queue panel — shows active/completed transfers."""
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLabel,
    QPushButton, QAbstractItemView, QMenu
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtCore import QUrl
from nss3ui.ui.transfer_model import TransferTableModel, COL_PROGRESS, COL_ACTIONS
from nss3ui.ui.delegates import ProgressBarDelegate, ActionButtonsDelegate
from nss3ui.transfer_manager import TransferManager, TransferStatus, TransferDirection


class TransferPanel(QWidget):
    def __init__(self, manager: TransferManager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._model = TransferTableModel()
        self._setup_ui()
        self._connect_manager()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header — no inline style; theme CSS via objectName
        header = QWidget()
        header.setObjectName("panelHeader")
        header.setFixedHeight(32)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 8, 0)

        title = QLabel("TRANSFERS")
        title.setObjectName("panelTitle")
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        title.setFont(font)

        self._clear_btn = QPushButton("Clear Completed")
        self._clear_btn.setObjectName("clearBtn")
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.clicked.connect(self._clear_completed)

        h_layout.addWidget(title)
        h_layout.addStretch()
        h_layout.addWidget(self._clear_btn)

        # Table
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setItemDelegateForColumn(COL_PROGRESS, ProgressBarDelegate(self._table))
        self._actions_delegate = ActionButtonsDelegate(self._table)
        self._actions_delegate.action_requested.connect(self._on_action_requested)
        self._table.setItemDelegateForColumn(COL_ACTIONS, self._actions_delegate)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)

        hv = self._table.horizontalHeader()
        hv.resizeSection(0, 200)
        hv.resizeSection(1, 80)
        hv.resizeSection(2, 130)
        hv.resizeSection(3, 100)
        hv.resizeSection(4, 80)
        hv.resizeSection(5, 90)
        hv.resizeSection(6, 180)

        layout.addWidget(header)
        layout.addWidget(self._table)

    def _connect_manager(self) -> None:
        self._manager.transfer_added.connect(self._on_transfer_added)
        self._manager.transfer_updated.connect(self._on_transfer_updated)
        self._manager.transfer_finished.connect(self._on_transfer_updated)
        self._manager.transfer_failed.connect(lambda tid, _: self._on_transfer_updated(tid))
        self._manager.transfer_cancelled.connect(self._on_transfer_updated)
        for item in self._manager.all_items():
            self._model.add_transfer(item)

    def _on_transfer_added(self, tid: str) -> None:
        item = self._manager.get_item(tid)
        if item:
            self._model.add_transfer(item)

    def _on_transfer_updated(self, tid: str) -> None:
        self._model.update_transfer(tid)

    def _clear_completed(self) -> None:
        self._manager.clear_terminal()
        active = [
            i for i in self._manager.all_items()
            if i.status in (TransferStatus.QUEUED, TransferStatus.RUNNING, TransferStatus.PAUSED)
        ]
        self._model.beginResetModel()
        self._model._items = active
        self._model._id_to_row = {i.id: idx for idx, i in enumerate(active)}
        self._model.endResetModel()

    def _context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        item = self._model._items[index.row()]
        menu = QMenu(self)
        if item.status == TransferStatus.RUNNING:
            pause = menu.addAction("Pause")
            pause.triggered.connect(lambda: self._manager.pause(item.id))
            cancel = menu.addAction("Cancel")
            cancel.triggered.connect(lambda: self._manager.cancel(item.id))
        elif item.status == TransferStatus.PAUSED:
            resume = menu.addAction("Resume")
            resume.triggered.connect(lambda: self._manager.resume(item.id))
            cancel = menu.addAction("Cancel")
            cancel.triggered.connect(lambda: self._manager.cancel(item.id))
        elif item.status in (TransferStatus.FAILED, TransferStatus.CANCELLED):
            retry = menu.addAction("Retry")
            retry.triggered.connect(lambda: self._manager.retry(item.id))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_action_requested(self, action: str, transfer_id: str) -> None:
        if action == "Pause":
            self._manager.pause(transfer_id)
        elif action == "Cancel":
            self._manager.cancel(transfer_id)
        elif action == "Resume":
            self._manager.resume(transfer_id)
        elif action == "Retry":
            self._manager.retry(transfer_id)
        elif action == "Show Folder":
            item = self._manager.get_item(transfer_id)
            if item:
                self._open_containing_folder(item.local_path)

    def _open_containing_folder(self, path: str) -> None:
        folder = os.path.dirname(path) or path
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
