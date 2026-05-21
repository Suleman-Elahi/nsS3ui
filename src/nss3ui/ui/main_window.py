"""
MainWindow — top-level application window.
Wires together all panels, transfer manager, settings, and theme switching.
"""
from __future__ import annotations
import logging
from botocore.exceptions import ProfileNotFound
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout,
    QStatusBar, QToolBar, QLabel, QSizePolicy, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, QSize, QThreadPool
from PySide6.QtGui import QAction, QKeySequence

from nss3ui.ui.theme import get_stylesheet
from nss3ui.ui.bucket_panel import BucketPanel
from nss3ui.ui.object_browser import ObjectBrowser
from nss3ui.ui.preview_panel import PreviewPanel
from nss3ui.ui.transfer_panel import TransferPanel
from nss3ui.ui.connect_dialog import ConnectDialog
from nss3ui.ui.settings_dialog import SettingsDialog
from nss3ui.ui.icons import (
    icon_upload, icon_download, icon_refresh, icon_account
)
from nss3ui.s3client import S3Client
from nss3ui.transfer_manager import TransferManager, TransferDirection, TransferStatus
from nss3ui.workers.folder_worker import FolderDownloadWorker
from nss3ui.state import AppStateManager
from nss3ui.config import get_theme
from nss3ui.app_controller import AppController
from nss3ui.ui.error_text import short_error

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AWS S3 UI")
        self.resize(1280, 800)

        self._client: S3Client | None = None
        self._manager: TransferManager | None = None
        self._controller = AppController(self)
        self._state = AppStateManager(self)
        self._current_theme = get_theme()

        self._apply_theme(self._current_theme)
        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()

        self._connect_to_s3()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self, theme: str) -> None:
        self._current_theme = theme
        self.setStyleSheet(get_stylesheet(theme))

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._bucket_panel = BucketPanel()
        self._bucket_panel.setMinimumWidth(160)
        self._bucket_panel.setMaximumWidth(280)

        self._object_browser = ObjectBrowser()

        self._preview_panel = PreviewPanel()
        self._preview_panel.setMinimumWidth(200)
        self._preview_panel.setMaximumWidth(400)

        self._h_splitter.addWidget(self._bucket_panel)
        self._h_splitter.addWidget(self._object_browser)
        self._h_splitter.addWidget(self._preview_panel)
        self._h_splitter.setStretchFactor(0, 0)
        self._h_splitter.setStretchFactor(1, 1)
        self._h_splitter.setStretchFactor(2, 0)
        self._h_splitter.setSizes([200, 800, 280])

        self._v_splitter = QSplitter(Qt.Orientation.Vertical)
        self._v_splitter.addWidget(self._h_splitter)

        self._transfer_placeholder = QWidget()
        self._transfer_placeholder.setFixedHeight(0)
        self._v_splitter.addWidget(self._transfer_placeholder)
        self._v_splitter.setStretchFactor(0, 1)
        self._v_splitter.setStretchFactor(1, 0)

        root_layout.addWidget(self._v_splitter)

    def _setup_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        self._connect_action = QAction(icon_account(), "Connect", self)
        self._connect_action.setToolTip("Connect to S3 / switch profile")
        self._connect_action.triggered.connect(self._connect_to_s3)
        tb.addAction(self._connect_action)

        tb.addSeparator()

        self._upload_action = QAction(icon_upload(), "Upload", self)
        self._upload_action.setShortcut(QKeySequence("Ctrl+U"))
        self._upload_action.triggered.connect(self._object_browser._upload_files)
        self._upload_action.setEnabled(False)
        tb.addAction(self._upload_action)

        self._download_action = QAction(icon_download(), "Download", self)
        self._download_action.setShortcut(QKeySequence("Ctrl+D"))
        self._download_action.triggered.connect(self._object_browser._download_selected)
        self._download_action.setEnabled(False)
        tb.addAction(self._download_action)

        tb.addSeparator()

        self._refresh_action = QAction(icon_refresh(), "Refresh", self)
        self._refresh_action.setShortcut(QKeySequence("F5"))
        self._refresh_action.triggered.connect(self._object_browser._refresh)
        self._refresh_action.setEnabled(False)
        tb.addAction(self._refresh_action)

        # Settings button (right-aligned)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self._settings_action = QAction("⚙  Settings", self)
        self._settings_action.triggered.connect(self._open_settings)
        tb.addAction(self._settings_action)

        self._profile_label = QLabel("Not connected")
        self._profile_label.setStyleSheet("color: #9d9d9d; padding-right: 8px;")
        tb.addWidget(self._profile_label)

    def _setup_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._status_label = QLabel("Ready")
        self._statusbar.addWidget(self._status_label)

    def _connect_signals(self) -> None:
        self._bucket_panel.bucket_selected.connect(self._on_bucket_selected)
        self._object_browser.object_selected.connect(self._on_object_selected)
        self._object_browser.object_deselected.connect(self._preview_panel.clear)
        self._object_browser.status_message.connect(self._set_status)
        self._object_browser.upload_requested.connect(self._on_upload_requested)
        self._object_browser.download_requested.connect(self._on_download_requested)
        self._object_browser.folder_download_requested.connect(self._on_folder_download_requested)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.theme_changed.connect(self._apply_theme)
        dlg.exec()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect_to_s3(self) -> None:
        dlg = ConnectDialog(self)
        if dlg.exec() != ConnectDialog.DialogCode.Accepted:
            return
        cfg = dlg.get_config()
        try:
            if cfg["mode"] == "profile":
                self._controller.connect_profile(
                    profile=cfg["profile"],
                    region=cfg["region"],
                    endpoint_url=cfg.get("endpoint_url"),
                )
                self._profile_label.setText(f"Profile: {cfg['profile']}")
            else:
                self._controller.connect_keys(
                    region=cfg["region"],
                    endpoint_url=cfg.get("endpoint_url"),
                    access_key=cfg["access_key"],
                    secret_key=cfg["secret_key"],
                    session_token=cfg.get("session_token"),
                )
                self._profile_label.setText("Access Keys")

            self._client = self._controller.client
            self._manager = self._controller.manager

            self._bucket_panel.set_client(self._client)
            self._object_browser.set_client(self._client)
            self._preview_panel.set_client(self._client)

            self._setup_transfer_panel()

            self._upload_action.setEnabled(True)
            self._download_action.setEnabled(True)
            self._refresh_action.setEnabled(True)

            self._set_status("Connected")
        except ProfileNotFound as exc:
            self._handle_connection_error(
                "Profile Not Found",
                "The selected AWS profile was not found. "
                "Create it in ~/.aws/config or connect using Access Keys.",
                exc,
            )
        except Exception as exc:
            self._handle_connection_error("Connection Error", short_error(str(exc)), exc)

    def _handle_connection_error(self, title: str, message: str, exc: Exception) -> None:
        self._controller.disconnect()
        self._client = None
        self._manager = None
        self._profile_label.setText("Not connected")
        self._upload_action.setEnabled(False)
        self._download_action.setEnabled(False)
        self._refresh_action.setEnabled(False)
        self._set_status("Connection failed")
        QMessageBox.critical(self, title, message)
        log.warning("Connection failed: %s", exc)

    def _setup_transfer_panel(self) -> None:
        if self._manager is None:
            return
        self._transfer_placeholder.setParent(None)
        self._transfer_panel = TransferPanel(self._manager)
        self._manager.transfer_finished.connect(self._on_transfer_finished)
        self._transfer_panel.setMaximumHeight(200)
        self._transfer_panel.setMinimumHeight(120)
        self._v_splitter.addWidget(self._transfer_panel)
        self._v_splitter.setSizes([600, 160])

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_bucket_selected(self, bucket: str) -> None:
        self._state.set_bucket(bucket)
        self._object_browser.navigate(bucket, "")
        self._preview_panel.clear()
        self._set_status(f"Opened bucket: {bucket}")

    def _on_object_selected(self, item) -> None:
        if self._client:
            self._preview_panel.show_item(item, self._state.state.current_bucket or "")

    def _on_upload_requested(self, local_path: str, bucket: str, key: str) -> None:
        if self._manager:
            self._manager.enqueue_upload(local_path, bucket, key)
            self._set_status(f"Uploading: {key}")

    def _on_download_requested(self, bucket: str, key: str, local_path: str, size: int) -> None:
        if self._manager:
            self._manager.enqueue_download(bucket, key, local_path, size)
            self._set_status(f"Downloading: {key}")

    def _on_folder_download_requested(self, bucket: str, prefix: str, zip_path: str) -> None:
        """Download an entire S3 folder as a ZIP in a background worker."""
        if not self._client:
            return
        folder_name = prefix.rstrip("/").rsplit("/", 1)[-1]
        self._set_status(f"Zipping folder: {folder_name}…")

        from nss3ui.workers.signals import WorkerSignals
        worker = FolderDownloadWorker(self._client, bucket, prefix, zip_path)
        worker.signals.finished.connect(
            lambda path: self._on_folder_download_done(path)
        )
        worker.signals.error.connect(
            lambda err: QMessageBox.critical(self, "Folder Download Error", short_error(err))
        )
        # Wire to transfer panel if available
        if self._manager:
            tid = self._manager.enqueue_folder_zip(bucket, prefix, zip_path, worker)
        else:
            QThreadPool.globalInstance().start(worker)

    def _on_folder_download_done(self, zip_path: str) -> None:
        self._set_status(f"Folder saved: {zip_path}")

    def _on_transfer_finished(self, transfer_id: str) -> None:
        if not self._manager:
            return
        item = self._manager.get_item(transfer_id)
        if not item or item.direction != TransferDirection.UPLOAD or item.status != TransferStatus.COMPLETED:
            return
        uploads_active = any(
            t.direction == TransferDirection.UPLOAD
            and t.status in (TransferStatus.QUEUED, TransferStatus.RUNNING, TransferStatus.PAUSED)
            for t in self._manager.all_items()
        )
        if not uploads_active and self._state.state.current_bucket == item.bucket:
            self._object_browser._refresh()

    def _set_status(self, msg: str) -> None:
        self._status_label.setText(msg)
