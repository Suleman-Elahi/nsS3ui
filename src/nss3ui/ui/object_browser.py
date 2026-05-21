"""
Object browser: breadcrumb + QTableView with async lazy loading.
All S3 calls happen in worker threads — UI thread never blocks.
"""
from __future__ import annotations
import os
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLabel,
    QPushButton, QLineEdit, QMenu, QMessageBox, QFileDialog,
    QAbstractItemView, QToolButton, QApplication, QScrollBar
)
from PySide6.QtCore import Qt, Signal, QThreadPool
from PySide6.QtGui import QKeySequence, QShortcut
from nss3ui.ui.object_model import ObjectTableModel, make_proxy, S3ObjectItem
from nss3ui.ui.icons import (
    icon_upload, icon_download, icon_delete, icon_refresh, icon_copy_link
)
from nss3ui.workers.async_list_worker import AsyncListObjectsWorker
from nss3ui.workers.transfer_worker import DeleteWorker
from nss3ui.workers.folder_worker import FolderDownloadWorker
from nss3ui.s3client import S3Client
from nss3ui.ui.error_text import short_error

log = logging.getLogger(__name__)


class ObjectBrowser(QWidget):
    """Main file-explorer-like object browser."""

    object_selected = Signal(object)           # S3ObjectItem
    object_deselected = Signal()               # emitted after delete / navigate
    upload_requested = Signal(str, str, str)   # local_path, bucket, key
    download_requested = Signal(str, str, str, int)  # bucket, key, local_path, size
    folder_download_requested = Signal(str, str, str)  # bucket, prefix, zip_path
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: S3Client | None = None
        self._bucket: str = ""
        self._prefix: str = ""
        self._next_token: str = ""
        self._loading = False
        self._setup_ui()
        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar — no inline style; theme CSS handles QWidget#browserToolbar
        toolbar = QWidget()
        toolbar.setObjectName("browserToolbar")
        toolbar.setFixedHeight(40)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(6, 0, 6, 0)
        tb.setSpacing(4)

        self._back_btn = QToolButton()
        self._back_btn.setText("←")
        self._back_btn.setToolTip("Go up (Backspace)")
        self._back_btn.clicked.connect(self._go_up)
        self._back_btn.setFixedSize(28, 28)

        self._breadcrumb = QLineEdit()
        self._breadcrumb.setObjectName("breadcrumb")
        self._breadcrumb.setPlaceholderText("bucket/prefix/")
        self._breadcrumb.setReadOnly(True)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter…")
        self._search.setFixedWidth(180)
        self._search.textChanged.connect(self._on_filter)

        for icon_fn, tip, slot, attr in [
            (icon_upload,   "Upload files (Ctrl+U)",      self._upload_files,    "_upload_btn"),
            (icon_download, "Download selected (Ctrl+D)", self._download_selected, "_download_btn"),
            (icon_delete,   "Delete selected (Del)",      self._delete_selected, "_delete_btn"),
            (icon_refresh,  "Refresh (F5)",               self._refresh,         "_refresh_btn"),
        ]:
            btn = QToolButton()
            btn.setIcon(icon_fn())
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            btn.setFixedSize(28, 28)
            setattr(self, attr, btn)

        tb.addWidget(self._back_btn)
        tb.addWidget(self._breadcrumb, 1)
        tb.addWidget(self._search)
        tb.addWidget(self._upload_btn)
        tb.addWidget(self._download_btn)
        tb.addWidget(self._delete_btn)
        tb.addWidget(self._refresh_btn)

        # Table
        self._model = ObjectTableModel()
        self._proxy = make_proxy(self._model)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll)

        hdr = self._table.horizontalHeader()
        hdr.resizeSection(0, 320)
        hdr.resizeSection(1, 90)
        hdr.resizeSection(2, 140)
        hdr.resizeSection(3, 110)
        hdr.resizeSection(4, 80)

        self._load_more_btn = QPushButton("Load more…")
        self._load_more_btn.setObjectName("loadMoreBtn")
        self._load_more_btn.setVisible(False)
        self._load_more_btn.clicked.connect(self._load_next_page)

        self._empty_label = QLabel("Select a bucket to browse objects")
        self._empty_label.setObjectName("placeholderLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(toolbar)
        layout.addWidget(self._table)
        layout.addWidget(self._load_more_btn)
        layout.addWidget(self._empty_label)

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Delete"), self, self._delete_selected)
        QShortcut(QKeySequence("F5"), self, self._refresh)
        QShortcut(QKeySequence("Backspace"), self, self._go_up)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_client(self, client: S3Client) -> None:
        self._client = client

    def navigate(self, bucket: str, prefix: str = "") -> None:
        self._bucket = bucket
        self._prefix = prefix
        self._next_token = ""
        self._model.clear()
        self._load_more_btn.setVisible(False)
        self._empty_label.setVisible(False)
        self._table.setVisible(True)
        self._update_breadcrumb()
        self._load_page()
        self.object_deselected.emit()

    # ------------------------------------------------------------------
    # Async loading
    # ------------------------------------------------------------------

    def _load_page(self) -> None:
        if not self._client or self._loading:
            return
        self._loading = True
        self.status_message.emit(f"Loading {self._bucket}/{self._prefix}…")

        worker = AsyncListObjectsWorker(
            self._client.async_session_kwargs,
            self._client.async_client_kwargs,
            self._bucket,
            self._prefix,
            continuation_token=self._next_token,
        )
        worker.signals.page_ready.connect(self._on_page_ready)
        worker.signals.finished.connect(self._on_page_finished)
        worker.signals.error.connect(self._on_load_error)
        QThreadPool.globalInstance().start(worker)

    def _on_page_ready(self, objects: list, prefixes: list) -> None:
        self._model.append_page(objects, prefixes)
        count = self._model.rowCount()
        self.status_message.emit(f"{count} items in {self._bucket}/{self._prefix or '/'}")

    def _on_page_finished(self, next_token: str) -> None:
        self._loading = False
        self._next_token = next_token
        self._load_more_btn.setVisible(bool(next_token))
        if self._model.rowCount() == 0:
            self._empty_label.setText("This folder is empty")
            self._empty_label.setVisible(True)

    def _on_load_error(self, msg: str) -> None:
        self._loading = False
        self.status_message.emit(f"Error: {short_error(msg)}")
        log.error("ObjectBrowser load error: %s", msg)

    def _load_next_page(self) -> None:
        if self._next_token:
            self._load_page()

    def _on_scroll(self, value: int) -> None:
        bar: QScrollBar = self._table.verticalScrollBar()
        if self._loading or not self._next_token:
            return
        # Infinite-scroll trigger near bottom.
        if value >= bar.maximum() - 4:
            self._load_page()

    def _refresh(self) -> None:
        if self._bucket:
            self.navigate(self._bucket, self._prefix)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_up(self) -> None:
        if not self._prefix:
            return
        parts = self._prefix.rstrip("/").rsplit("/", 1)
        new_prefix = parts[0] + "/" if len(parts) > 1 else ""
        self.navigate(self._bucket, new_prefix)

    def _update_breadcrumb(self) -> None:
        path = self._bucket
        if self._prefix:
            path += "/" + self._prefix
        self._breadcrumb.setText(path)

    def _on_double_click(self, index) -> None:
        src = self._proxy.mapToSource(index)
        item = self._model.item_at(src.row())
        if item is None:
            return
        if item.is_folder:
            self.navigate(self._bucket, item.key)
        else:
            self.object_selected.emit(item)

    def _on_selection_changed(self) -> None:
        rows = self._selected_source_rows()
        items = self._model.selected_items(rows)
        if len(items) == 1 and not items[0].is_folder:
            self.object_selected.emit(items[0])
        elif not items:
            self.object_deselected.emit()

    def _on_filter(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _upload_files(self) -> None:
        if not self._bucket:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to upload")
        for path in paths:
            key = self._prefix + os.path.basename(path)
            self.upload_requested.emit(path, self._bucket, key)

    def _download_selected(self) -> None:
        """Download selected files; if a folder is selected, offer ZIP download."""
        rows = self._selected_source_rows()
        all_items = self._model.selected_items(rows)
        if not all_items:
            return

        folders = [i for i in all_items if i.is_folder]
        files = [i for i in all_items if not i.is_folder]

        dest = QFileDialog.getExistingDirectory(self, "Select download destination")
        if not dest:
            return

        # Download individual files
        for item in files:
            local_path = os.path.join(dest, item.display_name)
            self.download_requested.emit(self._bucket, item.key, local_path, item.size)

        # Download folders as ZIP
        for folder in folders:
            folder_name = folder.key.rstrip("/").rsplit("/", 1)[-1]
            zip_path = os.path.join(dest, f"{folder_name}.zip")
            self.folder_download_requested.emit(self._bucket, folder.key, zip_path)

    def _delete_selected(self) -> None:
        items = self._get_selected_file_items()
        if not items:
            return
        names = "\n".join(i.display_name for i in items[:5])
        if len(items) > 5:
            names += f"\n… and {len(items) - 5} more"
        reply = QMessageBox.question(
            self, "Delete Objects",
            f"Delete {len(items)} object(s)?\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        keys = [i.key for i in items]
        worker = DeleteWorker(self._client, self._bucket, keys)
        worker.signals.finished.connect(self._on_delete_done)
        worker.signals.error.connect(
            lambda err: QMessageBox.critical(self, "Delete Error", short_error(err))
        )
        QThreadPool.globalInstance().start(worker)

    def _on_delete_done(self, failed: list) -> None:
        if failed:
            QMessageBox.warning(self, "Partial Delete", f"Failed to delete: {', '.join(failed)}")
        # Clear preview before refreshing so stale image is gone
        self.object_deselected.emit()
        self._refresh()

    def _presign_selected(self) -> None:
        items = self._get_selected_file_items()
        if not items or not self._client:
            return
        item = items[0]
        from nss3ui.ui.connect_dialog import PresignDialog
        dlg = PresignDialog(item.display_name, self)
        if dlg.exec() != PresignDialog.DialogCode.Accepted:
            return
        expires = dlg.expires_in()
        try:
            url = self._client.generate_presigned_url(self._bucket, item.key, expires)
            QApplication.clipboard().setText(url)
            self.status_message.emit(
                f"Presigned URL copied (expires in {expires}s) — {item.display_name}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", short_error(str(exc)))

    def _context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        src = self._proxy.mapToSource(index)
        item = self._model.item_at(src.row()) if index.isValid() else None
        menu = QMenu(self)

        if item:
            if item.is_folder:
                open_act = menu.addAction("📂  Open Folder")
                open_act.triggered.connect(lambda: self.navigate(self._bucket, item.key))
                dl_zip = menu.addAction(icon_download(), "Download as ZIP")
                dl_zip.triggered.connect(lambda: self._download_folder_item(item))
            else:
                dl_act = menu.addAction(icon_download(), "Download")
                dl_act.triggered.connect(self._download_selected)
                link_act = menu.addAction(icon_copy_link(), "Copy Presigned URL…")
                link_act.triggered.connect(self._presign_selected)
            menu.addSeparator()
            del_act = menu.addAction(icon_delete(), "Delete")
            del_act.triggered.connect(self._delete_selected)
        else:
            up_act = menu.addAction(icon_upload(), "Upload Files Here")
            up_act.triggered.connect(self._upload_files)

        menu.addSeparator()
        ref_act = menu.addAction(icon_refresh(), "Refresh")
        ref_act.triggered.connect(self._refresh)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _download_folder_item(self, item: S3ObjectItem) -> None:
        dest = QFileDialog.getExistingDirectory(self, "Select download destination")
        if not dest:
            return
        folder_name = item.key.rstrip("/").rsplit("/", 1)[-1]
        zip_path = os.path.join(dest, f"{folder_name}.zip")
        self.folder_download_requested.emit(self._bucket, item.key, zip_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _selected_source_rows(self) -> list[int]:
        rows = set()
        for idx in self._table.selectionModel().selectedRows():
            rows.add(self._proxy.mapToSource(idx).row())
        return sorted(rows)

    def _get_selected_file_items(self) -> list[S3ObjectItem]:
        rows = self._selected_source_rows()
        return [i for i in self._model.selected_items(rows) if not i.is_folder]
