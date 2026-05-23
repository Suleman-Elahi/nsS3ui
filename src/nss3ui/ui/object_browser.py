"""
Object browser: breadcrumb + QTableView with async lazy loading.
All S3 calls happen in worker threads — UI thread never blocks.
"""
from __future__ import annotations
import os
import logging
from collections import deque
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLabel,
    QPushButton, QLineEdit, QMenu, QMessageBox, QFileDialog, QInputDialog,
    QAbstractItemView, QToolButton, QApplication, QScrollBar
)
from PySide6.QtCore import Qt, Signal, QThreadPool, QTimer, QEvent
from PySide6.QtGui import QKeySequence, QShortcut
from nss3ui.ui.object_model import ObjectTableModel, make_proxy, S3ObjectItem
from nss3ui.ui.icons import (
    icon_upload, icon_download, icon_folder, icon_delete, icon_refresh, icon_copy_link, icon_new_folder,
    icon_tag, icon_lock
)
from nss3ui.workers.async_list_worker import AsyncListObjectsWorker
from nss3ui.workers.transfer_worker import DeleteWorker
from nss3ui.workers.prefix_move_worker import PrefixMoveWorker
from nss3ui.workers.local_drop_scan_worker import LocalDropScanWorker
from nss3ui.s3client import S3Client
from nss3ui.ui.error_text import short_error
from nss3ui.ui.object_ops import prompt_for_tags, prompt_for_acl, prompt_for_destination_prefix

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
        self._pending_uploads: deque[tuple[str, str, str]] = deque()
        self._pending_drop_tasks: deque[tuple[str, str]] = deque()
        self._pending_download_files: deque[tuple[str, str, str, int]] = deque()
        self._pending_download_folders: deque[tuple[str, str, str]] = deque()
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
            (icon_upload,   "Upload File(s) (Ctrl+U)",    self._upload_files,    "_upload_btn"),
            (icon_folder,   "Upload Folder",              self._upload_folder,   "_upload_folder_btn"),
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
        tb.addWidget(self._upload_folder_btn)
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
        self._table.setAcceptDrops(True)
        self._table.viewport().setAcceptDrops(True)
        self._table.viewport().installEventFilter(self)

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
        if self._prefix:
            # Hide the current folder marker object (e.g., "path/current/") from its own listing.
            objects = [o for o in objects if o.get("Key") != self._prefix]
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
        pretty = short_error(msg)
        low = (msg or "").lower()
        if "accessdenied" in low and "listbucket" in low and self._bucket:
            pretty += (
                f" Ask your AWS admin to allow `s3:ListBucket` on "
                f"`arn:aws:s3:::{self._bucket}`."
            )
        self.status_message.emit(f"Error: {pretty}")
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

    def eventFilter(self, watched, event) -> bool:
        if watched is self._table.viewport():
            et = event.type()
            if et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                if self._accept_drop_event(event):
                    event.acceptProposedAction()
                else:
                    event.ignore()
                return True
            if et == QEvent.Type.Drop:
                self._handle_drop_event(event)
                return True
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _upload_files(self) -> None:
        if not self._bucket:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to upload")
        for path in paths:
            key = self._prefix + os.path.basename(path)
            self._pending_uploads.append((path, self._bucket, key))
        if self._pending_uploads:
            self.status_message.emit(f"Queueing {len(self._pending_uploads)} upload(s)…")
            QTimer.singleShot(0, self._drain_upload_queue)

    def _upload_folder(self) -> None:
        if not self._bucket:
            return
        folder = QFileDialog.getExistingDirectory(self, "Select folder to upload")
        if not folder:
            return

        root_name = os.path.basename(folder.rstrip("/\\"))
        key_root = self._prefix + root_name + "/"
        queued = 0
        for dirpath, _dirnames, filenames in os.walk(folder):
            for filename in filenames:
                local_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(local_path, folder).replace("\\", "/")
                key = key_root + rel_path
                self._pending_uploads.append((local_path, self._bucket, key))
                queued += 1
        self.status_message.emit(f"Queueing {queued} file(s) from folder: {root_name}…")
        if queued > 0:
            QTimer.singleShot(0, self._drain_upload_queue)

    def _drain_upload_queue(self) -> None:
        """Emit uploads in chunks so large selections do not block the UI."""
        chunk_size = 25
        sent = 0
        while sent < chunk_size and self._pending_uploads:
            local_path, bucket, key = self._pending_uploads.popleft()
            self.upload_requested.emit(local_path, bucket, key)
            sent += 1
        if self._pending_uploads:
            QTimer.singleShot(0, self._drain_upload_queue)

    def _accept_drop_event(self, event) -> bool:
        if not self._bucket:
            return False
        md = event.mimeData()
        return bool(md and md.hasUrls() and any(u.isLocalFile() for u in md.urls()))

    def _handle_drop_event(self, event) -> None:
        if not self._accept_drop_event(event):
            event.ignore()
            return
        local_paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        local_paths = [p for p in local_paths if p]
        if not local_paths:
            event.ignore()
            return
        self.status_message.emit(f"Scanning dropped items ({len(local_paths)})…")
        worker = LocalDropScanWorker(local_paths, self._prefix)
        worker.signals.finished.connect(self._on_drop_scan_finished)
        worker.signals.error.connect(
            lambda err: QMessageBox.critical(self, "Drop Upload Error", short_error(err))
        )
        QThreadPool.globalInstance().start(worker)
        event.acceptProposedAction()

    def _on_drop_scan_finished(self, payload: object) -> None:
        tasks = payload if isinstance(payload, list) else []
        for task in tasks:
            if not isinstance(task, (tuple, list)) or len(task) != 2:
                continue
            local_path, key = task
            self._pending_drop_tasks.append((str(local_path), str(key)))
        if self._pending_drop_tasks:
            self.status_message.emit(f"Queueing {len(self._pending_drop_tasks)} dropped upload(s)…")
            QTimer.singleShot(0, self._drain_drop_tasks)
        else:
            self.status_message.emit("No uploadable files found in drop.")

    def _drain_drop_tasks(self) -> None:
        """
        Move scanned drop tasks into upload queue in chunks to keep UI responsive.
        """
        chunk_size = 200
        moved = 0
        while moved < chunk_size and self._pending_drop_tasks:
            local_path, key = self._pending_drop_tasks.popleft()
            self._pending_uploads.append((local_path, self._bucket, key))
            moved += 1
        if self._pending_uploads:
            QTimer.singleShot(0, self._drain_upload_queue)
        if self._pending_drop_tasks:
            QTimer.singleShot(0, self._drain_drop_tasks)

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

        # Queue individual file downloads
        for item in files:
            local_path = os.path.join(dest, item.display_name)
            self._pending_download_files.append((self._bucket, item.key, local_path, item.size))

        # Queue folder ZIP downloads
        for folder in folders:
            folder_name = folder.key.rstrip("/").rsplit("/", 1)[-1]
            zip_path = os.path.join(dest, f"{folder_name}.zip")
            self._pending_download_folders.append((self._bucket, folder.key, zip_path))

        total = len(self._pending_download_files) + len(self._pending_download_folders)
        if total > 0:
            self.status_message.emit(f"Queueing {total} download(s)…")
            QTimer.singleShot(0, self._drain_download_queue)

    def _drain_download_queue(self) -> None:
        """
        Emit downloads in chunks so large mixed selections do not block
        the Qt main event loop.
        """
        chunk_size = 25
        sent = 0
        while sent < chunk_size and self._pending_download_files:
            bucket, key, local_path, size = self._pending_download_files.popleft()
            self.download_requested.emit(bucket, key, local_path, size)
            sent += 1
        while sent < chunk_size and self._pending_download_folders:
            bucket, prefix, zip_path = self._pending_download_folders.popleft()
            self.folder_download_requested.emit(bucket, prefix, zip_path)
            sent += 1

        if self._pending_download_files or self._pending_download_folders:
            QTimer.singleShot(0, self._drain_download_queue)

    def _delete_selected(self) -> None:
        if not self._client or not self._bucket:
            return
        items = self._get_selected_items()
        if not items:
            return
        file_items = [i for i in items if not i.is_folder]
        folder_items = [i for i in items if i.is_folder]
        names = "\n".join(i.display_name for i in items[:5])
        if len(items) > 5:
            names += f"\n… and {len(items) - 5} more"
        target_kind = "item(s)"
        if folder_items and not file_items:
            target_kind = "folder(s)"
        elif file_items and not folder_items:
            target_kind = "object(s)"
        reply = QMessageBox.question(
            self, "Delete Objects",
            f"Delete {len(items)} {target_kind}?\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        keys: set[str] = {i.key for i in file_items}
        for folder in folder_items:
            keys.add(folder.key)
            for obj in self._client.list_all_objects(self._bucket, folder.key):
                key = obj.get("Key")
                if key:
                    keys.add(key)
        if not keys:
            return
        worker = DeleteWorker(self._client, self._bucket, list(keys))
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
        menu.setToolTipsVisible(True)
        target_prefix = item.key if item and item.is_folder else self._prefix

        if item:
            if item.is_folder:
                open_act = menu.addAction(icon_folder(), "Open Folder")
                open_act.triggered.connect(lambda: self.navigate(self._bucket, item.key))
                new_folder_act = menu.addAction(icon_new_folder(), "New Folder Here...")
                new_folder_act.triggered.connect(
                    lambda _=False, p=target_prefix: self._create_folder_at(p)
                )
                dl_zip = menu.addAction(icon_download(), "Download as ZIP")
                dl_zip.triggered.connect(lambda: self._download_folder_item(item))
                move_folder_act = menu.addAction("Rename/Move Folder...")
                move_folder_act.triggered.connect(lambda _=False, it=item: self._rename_move_folder(it))
            else:
                new_folder_act = menu.addAction(icon_new_folder(), "New Folder Here...")
                new_folder_act.triggered.connect(
                    lambda _=False, p=target_prefix: self._create_folder_at(p)
                )
                dl_act = menu.addAction(icon_download(), "Download")
                dl_act.triggered.connect(self._download_selected)
                link_act = menu.addAction(icon_copy_link(), "Copy Presigned URL…")
                link_act.triggered.connect(self._presign_selected)
                menu.addSeparator()
                tag_act = menu.addAction(icon_tag(), "Object Tags...")
                tag_act.triggered.connect(lambda _=False, it=item: self._put_object_tagging(it))
                acl_act = menu.addAction(icon_lock(), "Object ACL...")
                acl_act.triggered.connect(lambda _=False, it=item: self._put_object_acl(it))
            menu.addSeparator()
            del_act = menu.addAction(icon_delete(), "Delete")
            del_act.triggered.connect(self._delete_selected)
        else:
            new_folder_act = menu.addAction(icon_new_folder(), "New Folder Here...")
            new_folder_act.triggered.connect(
                lambda _=False, p=target_prefix: self._create_folder_at(p)
            )
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

    def _create_folder_at(self, target_prefix: str) -> None:
        if not self._client or not self._bucket:
            return

        name, ok = QInputDialog.getText(
            self,
            "Create Folder",
            f"Folder name under s3://{self._bucket}/{target_prefix}",
        )
        if not ok:
            return

        rel = (name or "").strip().strip("/")
        if not rel:
            return

        base = target_prefix if not target_prefix or target_prefix.endswith("/") else target_prefix + "/"
        key = base + rel.rstrip("/") + "/"
        try:
            self._client.raw.put_object(Bucket=self._bucket, Key=key, Body=b"")
            self.status_message.emit(f"Created folder: s3://{self._bucket}/{key}")
            self._refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Create Folder Error", short_error(str(exc)))

    def _put_object_tagging(self, item: S3ObjectItem) -> None:
        if not self._client or not self._bucket or item.is_folder:
            return
        tags = prompt_for_tags(self, self._bucket, item.key)
        if tags is None:
            return
        try:
            self._client.put_object_tagging(self._bucket, item.key, tags)
            self.status_message.emit(f"Updated tags: {item.display_name}")
        except Exception as exc:
            QMessageBox.critical(self, "PutObjectTagging Error", short_error(str(exc)))

    def _put_object_acl(self, item: S3ObjectItem) -> None:
        if not self._client or not self._bucket or item.is_folder:
            return
        acl = prompt_for_acl(self, self._bucket, item.key)
        if not acl:
            return
        try:
            self._client.put_object_acl(self._bucket, item.key, acl)
            self.status_message.emit(f"Updated ACL ({acl}): {item.display_name}")
        except Exception as exc:
            QMessageBox.critical(self, "PutObjectAcl Error", short_error(str(exc)))

    def _rename_move_folder(self, item: S3ObjectItem) -> None:
        if not self._client or not self._bucket or not item.is_folder:
            return
        src_prefix = item.key
        dst_prefix_raw = prompt_for_destination_prefix(self, self._bucket, src_prefix)
        if not dst_prefix_raw:
            return
        # If user enters just a folder name, keep it under the same parent prefix.
        raw = dst_prefix_raw.strip().lstrip("/").rstrip("/")
        if "/" not in raw:
            parent = src_prefix.rstrip("/").rsplit("/", 1)[0]
            dst_prefix = (parent + "/" if parent else "") + raw + "/"
        else:
            dst_prefix = raw + "/"
        if dst_prefix == src_prefix:
            return
        if dst_prefix.startswith(src_prefix):
            QMessageBox.warning(self, "Invalid Destination", "Destination cannot be inside the source folder.")
            return

        reply = QMessageBox.question(
            self,
            "Rename/Move Folder",
            f"Move s3://{self._bucket}/{src_prefix}\n-> s3://{self._bucket}/{dst_prefix}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        worker = PrefixMoveWorker(self._client, self._bucket, src_prefix, dst_prefix)
        worker.signals.started.connect(
            lambda: self.status_message.emit(f"Moving folder: {src_prefix} -> {dst_prefix}")
        )
        worker.signals.progress.connect(
            lambda done, total: self.status_message.emit(f"Moving folder objects: {done}/{total}")
        )
        worker.signals.finished.connect(self._on_move_folder_done)
        worker.signals.error.connect(
            lambda err: QMessageBox.critical(self, "Rename/Move Folder Error", short_error(err))
        )
        QThreadPool.globalInstance().start(worker)

    def _on_move_folder_done(self, result: object) -> None:
        data = result if isinstance(result, dict) else {}
        moved = int(data.get("moved_count", 0))
        failed = int(data.get("failed_delete_count", 0))
        dst_prefix = str(data.get("dst_prefix", ""))
        self.status_message.emit(f"Moved {moved} object(s) to {dst_prefix}")
        if failed:
            QMessageBox.warning(self, "Move Completed With Warnings", f"Failed to delete {failed} source object(s).")
        self._refresh()

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

    def _get_selected_items(self) -> list[S3ObjectItem]:
        rows = self._selected_source_rows()
        return self._model.selected_items(rows)
