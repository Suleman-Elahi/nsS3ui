"""Left sidebar: account/bucket tree — uses async listing."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QMenu, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QThreadPool, QRunnable
from PySide6.QtGui import QFont
from nss3ui.ui.icons import icon_bucket, icon_refresh
from nss3ui.workers.async_list_worker import AsyncListBucketsWorker
from nss3ui.s3client import S3Client
from nss3ui.workers.signals import WorkerSignals
from nss3ui.ui.error_text import short_error
import logging

log = logging.getLogger(__name__)


class BucketMutateWorker(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.setAutoDelete(True)
        self._fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self._fn()
            self.signals.finished.emit(True)
        except Exception as exc:
            self.signals.error.emit(str(exc))


class BucketPanel(QWidget):
    bucket_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: S3Client | None = None
        self._active_workers: set[QRunnable] = set()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header — styled entirely via theme CSS using objectName
        header = QWidget()
        header.setObjectName("panelHeader")
        header.setFixedHeight(36)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 4, 0)

        title = QLabel("BUCKETS")
        title.setObjectName("panelTitle")
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        title.setFont(font)

        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("iconButton")
        self._refresh_btn.setIcon(icon_refresh())
        self._refresh_btn.setFixedSize(24, 24)
        self._refresh_btn.setFlat(True)
        self._refresh_btn.setToolTip("Refresh buckets")
        self._refresh_btn.clicked.connect(self._load_buckets)

        h_layout.addWidget(title)
        h_layout.addStretch()
        h_layout.addWidget(self._refresh_btn)

        # List — no inline style; theme CSS handles QListWidget
        self._list = QListWidget()
        self._list.setObjectName("bucketList")
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.itemClicked.connect(self._on_item_clicked)

        layout.addWidget(header)
        layout.addWidget(self._list)

    def set_client(self, client: S3Client) -> None:
        self._client = client
        self._load_buckets()

    def _load_buckets(self) -> None:
        if not self._client:
            return
        self._list.clear()
        loading = QListWidgetItem("Loading…")
        loading.setForeground(Qt.GlobalColor.gray)
        self._list.addItem(loading)

        worker = AsyncListBucketsWorker(
            self._client.async_session_kwargs,
            self._client.async_client_kwargs,
        )
        worker.signals.finished.connect(self._on_buckets_loaded)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_buckets_loaded(self, buckets: list) -> None:
        self._list.clear()
        for b in buckets:
            item = QListWidgetItem(icon_bucket(), b["Name"])
            item.setData(Qt.ItemDataRole.UserRole, b["Name"])
            item.setToolTip(f"Created: {b.get('CreationDate', '')}")
            self._list.addItem(item)

    def _on_error(self, msg: str) -> None:
        self._list.clear()
        err = QListWidgetItem(f"⚠ {short_error(msg)}")
        err.setForeground(Qt.GlobalColor.red)
        self._list.addItem(err)
        log.error("BucketPanel error: %s", msg)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self.bucket_selected.emit(name)

    def _context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        menu = QMenu(self)
        if item and item.data(Qt.ItemDataRole.UserRole):
            name = item.data(Qt.ItemDataRole.UserRole)
            open_act = menu.addAction(icon_bucket(), f"Open '{name}'")
            open_act.triggered.connect(lambda: self.bucket_selected.emit(name))
            menu.addSeparator()
            del_act = menu.addAction("🗑  Delete Bucket")
            del_act.triggered.connect(lambda: self._delete_bucket(name))
        else:
            new_act = menu.addAction("➕  Create Bucket")
            new_act.triggered.connect(self._create_bucket)
        menu.addSeparator()
        ref_act = menu.addAction(icon_refresh(), "Refresh")
        ref_act.triggered.connect(self._load_buckets)
        menu.exec(self._list.mapToGlobal(pos))

    def _create_bucket(self) -> None:
        if not self._client:
            return
        name, ok = QInputDialog.getText(self, "Create Bucket", "Bucket name:")
        if ok and name.strip():
            worker = BucketMutateWorker(lambda: self._client.create_bucket(name.strip()))
            self._active_workers.add(worker)
            worker.signals.finished.connect(lambda _: self._active_workers.discard(worker))
            worker.signals.error.connect(lambda _: self._active_workers.discard(worker))
            worker.signals.finished.connect(lambda _: self._load_buckets())
            worker.signals.error.connect(
                lambda err: QMessageBox.critical(self, "Error", short_error(err))
            )
            QThreadPool.globalInstance().start(worker)

    def _delete_bucket(self, name: str) -> None:
        if not self._client:
            return
        reply = QMessageBox.question(
            self, "Delete Bucket",
            f"Delete bucket '{name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            worker = BucketMutateWorker(lambda: self._client.delete_bucket(name))
            self._active_workers.add(worker)
            worker.signals.finished.connect(lambda _: self._active_workers.discard(worker))
            worker.signals.error.connect(lambda _: self._active_workers.discard(worker))
            worker.signals.finished.connect(lambda _: self._load_buckets())
            worker.signals.error.connect(
                lambda err: QMessageBox.critical(self, "Error", short_error(err))
            )
            QThreadPool.globalInstance().start(worker)
