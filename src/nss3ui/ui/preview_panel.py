"""
Preview panel — shows image/text/metadata preview.
All fetching happens in worker threads.
Clears automatically when the current item is deleted or deselected.
No inline setStyleSheet — all styling via theme CSS.
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QStackedWidget, QLabel,
    QPlainTextEdit, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QPixmap, QFont, QImage
from nss3ui.workers.transfer_worker import PreviewWorker
from nss3ui.ui.object_model import S3ObjectItem
from nss3ui.s3client import S3Client
import humanize

log = logging.getLogger(__name__)

IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "ico", "tiff"}
TEXT_EXTS = {
    "txt", "md", "rst", "log", "csv", "json", "yaml", "yml",
    "xml", "toml", "ini", "cfg", "py", "js", "ts", "html", "css",
}
MAX_IMAGE_PREVIEW_BYTES = 8 * 1024 * 1024
TEXT_PREVIEW_MAX_BYTES = 32 * 1024
TEXT_PREVIEW_MAX_LINES = 5


class PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: S3Client | None = None
        self._current_item: S3ObjectItem | None = None
        self._current_bucket: str = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header — styled via theme CSS using objectName
        header = QWidget()
        header.setObjectName("panelHeader")
        header.setFixedHeight(36)
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 8, 0)
        h_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._title = QLabel("PREVIEW")
        self._title.setObjectName("panelTitle")
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self._title.setFont(font)
        h_layout.addWidget(self._title)

        # Stack
        self._stack = QStackedWidget()

        # Page 0: placeholder
        self._placeholder = QLabel("Select a file to preview")
        self._placeholder.setObjectName("placeholderLabel")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(self._placeholder)

        # Page 1: image
        self._img_scroll = QScrollArea()
        self._img_scroll.setWidgetResizable(True)
        self._img_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._img_scroll.setWidget(self._img_label)
        self._stack.addWidget(self._img_scroll)

        # Page 2: text
        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._stack.addWidget(self._text_edit)

        # Page 3: metadata
        self._meta_label = QLabel()
        self._meta_label.setObjectName("metaLabel")
        self._meta_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._meta_label.setWordWrap(True)
        meta_scroll = QScrollArea()
        meta_scroll.setWidget(self._meta_label)
        meta_scroll.setWidgetResizable(True)
        self._stack.addWidget(meta_scroll)

        layout.addWidget(header)
        layout.addWidget(self._stack)

    def set_client(self, client: S3Client) -> None:
        self._client = client

    def show_item(self, item: S3ObjectItem, bucket: str) -> None:
        self._current_item = item
        self._current_bucket = bucket
        # Safety mode: metadata-only preview to avoid native crashes in decode/render paths.
        self._show_metadata(item)

    def _show_loading(self, msg: str) -> None:
        self._placeholder.setText(msg)
        self._stack.setCurrentIndex(0)

    def _fetch_preview(self, bucket: str, key: str, max_bytes: int, mode: str) -> None:
        if not self._client:
            return
        worker = PreviewWorker(self._client, bucket, key, max_bytes)
        worker.signals.finished.connect(
            lambda data, k=key: self._on_data(data, mode, k)
        )
        worker.signals.error.connect(
            lambda err, k=key: self._on_preview_error(err, k)
        )
        QThreadPool.globalInstance().start(worker)

    def _on_data(self, data: bytes, mode: str, key: str) -> None:
        if self._current_item is None or self._current_item.key != key:
            return
        if mode == "image":
            img = QImage.fromData(data)
            if img.isNull():
                self._show_loading("Cannot render image")
                return
            px = QPixmap.fromImage(img)
            target = self._img_label.size()
            if target.width() > 1 and target.height() > 1:
                px = px.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._img_label.setPixmap(px)
            self._stack.setCurrentIndex(1)
        elif mode == "text":
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                text = repr(data[:200])
            lines = text.splitlines()
            shown = lines[:TEXT_PREVIEW_MAX_LINES]
            out = "\n".join(shown)
            if len(lines) > TEXT_PREVIEW_MAX_LINES or len(data) >= TEXT_PREVIEW_MAX_BYTES:
                out += "\n\n[Preview truncated]"
            self._text_edit.setPlainText(out)
            self._stack.setCurrentIndex(2)

    def _on_preview_error(self, err: str, key: str) -> None:
        if self._current_item is None or self._current_item.key != key:
            return
        self._show_loading(f"Preview unavailable: {err}")

    def _show_metadata(self, item: S3ObjectItem) -> None:
        lines = [
            f"<b>Name:</b> {item.display_name}",
            f"<b>Key:</b> {item.key}",
            f"<b>Size:</b> {humanize.naturalsize(item.size, binary=True)} ({item.size:,} bytes)",
            f"<b>Modified:</b> {item.modified or '—'}",
            f"<b>Storage Class:</b> {item.storage_class or 'STANDARD'}",
        ]
        self._meta_label.setText("<br>".join(lines))
        self._stack.setCurrentIndex(3)

    def clear(self) -> None:
        self._current_item = None
        self._current_bucket = ""
        self._img_label.clear()
        self._text_edit.clear()
        self._placeholder.setText("Select a file to preview")
        self._stack.setCurrentIndex(0)
