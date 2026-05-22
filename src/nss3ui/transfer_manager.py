"""
TransferManager — central queue for uploads and downloads.
Runs workers via QThreadPool. Never touches the UI directly.
"""
from __future__ import annotations
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
from PySide6.QtCore import QObject, QThreadPool, Signal
from nss3ui.workers.transfer_worker import UploadWorker, DownloadWorker
from nss3ui.s3client import S3Client
from nss3ui.local_cache import LocalCache

log = logging.getLogger(__name__)

MAX_UPLOAD_WORKERS = 4
MAX_DOWNLOAD_WORKERS = 4


class TransferStatus(Enum):
    QUEUED = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class TransferDirection(Enum):
    UPLOAD = "Upload"
    DOWNLOAD = "Download"


@dataclass
class TransferItem:
    id: str
    direction: TransferDirection
    filename: str
    bucket: str
    key: str
    local_path: str
    total_bytes: int = 0
    bytes_done: int = 0
    speed: float = 0.0
    status: TransferStatus = TransferStatus.QUEUED
    error: str = ""
    resume_state: dict = field(default_factory=dict)
    cancel_requested: bool = False
    pause_requested: bool = False
    worker: Optional[object] = field(default=None, repr=False)


class TransferManager(QObject):
    """
    Manages upload/download queue.
    Signals are emitted from worker threads via Qt's queued connection — safe.
    """

    transfer_added = Signal(str)          # transfer_id
    transfer_updated = Signal(str)        # transfer_id
    transfer_finished = Signal(str)       # transfer_id
    transfer_failed = Signal(str, str)    # transfer_id, error
    transfer_cancelled = Signal(str)      # transfer_id
    transfer_checkpoint = Signal(str)     # transfer_id

    def __init__(self, client: S3Client, parent=None):
        super().__init__(parent)
        self._client = client
        # Dedicated pool keeps heavy transfers from starving UI/listing workers.
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(MAX_UPLOAD_WORKERS + MAX_DOWNLOAD_WORKERS + 4)
        self._transfers: dict[str, TransferItem] = {}
        self._pending_pause: set[str] = set()
        self._cache = LocalCache()
        self._load_cached_transfers()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue_upload(self, local_path: str, bucket: str, key: str) -> str:
        tid = str(uuid.uuid4())
        import os
        size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        item = TransferItem(
            id=tid,
            direction=TransferDirection.UPLOAD,
            filename=os.path.basename(local_path),
            bucket=bucket,
            key=key,
            local_path=local_path,
            total_bytes=size,
        )
        self._transfers[tid] = item
        self.transfer_added.emit(tid)
        self._start_upload(item)
        return tid

    def enqueue_download(self, bucket: str, key: str, local_path: str, total_bytes: int = 0) -> str:
        tid = str(uuid.uuid4())
        import os
        item = TransferItem(
            id=tid,
            direction=TransferDirection.DOWNLOAD,
            filename=os.path.basename(key),
            bucket=bucket,
            key=key,
            local_path=local_path,
            total_bytes=total_bytes,
        )
        self._transfers[tid] = item
        self.transfer_added.emit(tid)
        self._start_download(item)
        return tid

    def enqueue_folder_zip(
        self, bucket: str, prefix: str, zip_path: str, worker=None
    ) -> str:
        """Register a folder-zip download in the transfer list and start the worker."""
        import os
        tid = str(uuid.uuid4())
        folder_name = prefix.rstrip("/").rsplit("/", 1)[-1]
        item = TransferItem(
            id=tid,
            direction=TransferDirection.DOWNLOAD,
            filename=f"{folder_name}.zip",
            bucket=bucket,
            key=prefix,
            local_path=zip_path,
            total_bytes=0,
        )
        self._transfers[tid] = item
        self.transfer_added.emit(tid)
        self._persist_item(item)

        if worker is not None:
            item.worker = worker
            item.status = TransferStatus.RUNNING
            worker.signals.progress.connect(
                lambda done, total, t=tid: self._on_progress(t, done, total)
            )
            worker.signals.speed.connect(lambda spd, t=tid: self._on_speed(t, spd))
            worker.signals.finished.connect(lambda _path, t=tid: self._on_finished(t))
            worker.signals.error.connect(lambda err, t=tid: self._on_error(t, err))
            worker.signals.cancelled.connect(lambda t=tid: self._on_cancelled(t))
            self._pool.start(worker)
        return tid

    def cancel(self, transfer_id: str) -> None:
        item = self._transfers.get(transfer_id)
        if not item:
            return
        was_paused = item.status == TransferStatus.PAUSED
        item.cancel_requested = True
        item.pause_requested = False
        item.status = TransferStatus.CANCELLED
        self._persist_item(item)
        self.transfer_updated.emit(transfer_id)
        if was_paused:
            self.transfer_cancelled.emit(transfer_id)
            return
        if item.worker:
            item.worker.cancel()

    def pause(self, transfer_id: str) -> None:
        item = self._transfers.get(transfer_id)
        if not item or item.status != TransferStatus.RUNNING:
            return
        item.pause_requested = True
        item.cancel_requested = False
        item.status = TransferStatus.PAUSED
        self._persist_item(item)
        self.transfer_updated.emit(transfer_id)
        self._pending_pause.add(transfer_id)
        if item.worker:
            item.worker.cancel()

    def resume(self, transfer_id: str) -> None:
        item = self._transfers.get(transfer_id)
        if not item or item.status != TransferStatus.PAUSED:
            return
        item.bytes_done = 0
        item.speed = 0.0
        item.error = ""
        item.cancel_requested = False
        item.pause_requested = False
        item.status = TransferStatus.QUEUED
        if item.direction == TransferDirection.UPLOAD:
            self._start_upload(item)
        else:
            self._start_download(item)
        self._persist_item(item)
        self.transfer_updated.emit(transfer_id)

    def retry(self, transfer_id: str) -> None:
        item = self._transfers.get(transfer_id)
        if not item or item.status not in (TransferStatus.FAILED, TransferStatus.CANCELLED):
            return
        item.bytes_done = 0
        item.speed = 0.0
        item.error = ""
        item.cancel_requested = False
        item.pause_requested = False
        item.status = TransferStatus.QUEUED
        if item.direction == TransferDirection.UPLOAD:
            self._start_upload(item)
        else:
            self._start_download(item)
        self._persist_item(item)
        self.transfer_updated.emit(transfer_id)

    def get_item(self, transfer_id: str) -> Optional[TransferItem]:
        return self._transfers.get(transfer_id)

    def all_items(self) -> list[TransferItem]:
        return list(self._transfers.values())

    def clear_terminal(self) -> None:
        remove_ids = [
            tid for tid, item in self._transfers.items()
            if item.status in (TransferStatus.COMPLETED, TransferStatus.FAILED, TransferStatus.CANCELLED)
        ]
        for tid in remove_ids:
            self._transfers.pop(tid, None)
        self._cache.delete_transfer_ids(remove_ids)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_upload(self, item: TransferItem) -> None:
        worker = UploadWorker(
            self._client, item.local_path, item.bucket, item.key, item.id, item.resume_state
        )
        item.worker = worker  # keeps the worker alive until we release it
        item.cancel_requested = False
        item.pause_requested = False
        item.status = TransferStatus.RUNNING
        worker.signals.progress.connect(lambda done, total, tid=item.id: self._on_progress(tid, done, total))
        worker.signals.speed.connect(lambda spd, tid=item.id: self._on_speed(tid, spd))
        worker.signals.checkpoint.connect(lambda state, tid=item.id: self._on_checkpoint(tid, state))
        worker.signals.finished.connect(lambda tid: self._on_finished(tid))
        worker.signals.error.connect(lambda err, tid=item.id: self._on_error(tid, err))
        worker.signals.cancelled.connect(lambda tid=item.id: self._on_cancelled(tid))
        self._pool.start(worker)
        self._persist_item(item)

    def _start_download(self, item: TransferItem) -> None:
        worker = DownloadWorker(
            self._client, item.bucket, item.key, item.local_path, item.total_bytes, item.id, item.resume_state
        )
        item.worker = worker  # keeps the worker alive until we release it
        item.cancel_requested = False
        item.pause_requested = False
        item.status = TransferStatus.RUNNING
        worker.signals.progress.connect(lambda done, total, tid=item.id: self._on_progress(tid, done, total))
        worker.signals.speed.connect(lambda spd, tid=item.id: self._on_speed(tid, spd))
        worker.signals.checkpoint.connect(lambda state, tid=item.id: self._on_checkpoint(tid, state))
        worker.signals.finished.connect(lambda tid: self._on_finished(tid))
        worker.signals.error.connect(lambda err, tid=item.id: self._on_error(tid, err))
        worker.signals.cancelled.connect(lambda tid=item.id: self._on_cancelled(tid))
        self._pool.start(worker)
        self._persist_item(item)

    def _on_progress(self, tid: str, done: int, total: int) -> None:
        item = self._transfers.get(tid)
        if item:
            item.bytes_done = done
            item.total_bytes = total
            self._persist_item(item)
            self.transfer_updated.emit(tid)

    def _on_speed(self, tid: str, speed: float) -> None:
        item = self._transfers.get(tid)
        if item:
            item.speed = speed
            self._persist_item(item)
            self.transfer_updated.emit(tid)

    def _on_finished(self, tid: str) -> None:
        item = self._transfers.get(tid)
        if item:
            if item.cancel_requested:
                item.status = TransferStatus.CANCELLED
                item.worker = None
                self._persist_item(item)
                self.transfer_cancelled.emit(tid)
                return
            if item.pause_requested:
                item.status = TransferStatus.PAUSED
                item.worker = None
                self._persist_item(item)
                self.transfer_updated.emit(tid)
                return
            item.status = TransferStatus.COMPLETED
            item.bytes_done = item.total_bytes
            item.resume_state = {}
            item.worker = None
            self._persist_item(item)
            self.transfer_finished.emit(tid)

    def _on_error(self, tid: str, error: str) -> None:
        item = self._transfers.get(tid)
        if item:
            item.status = TransferStatus.FAILED
            item.error = error
            item.worker = None
            self._persist_item(item)
            self.transfer_failed.emit(tid, error)

    def _on_cancelled(self, tid: str) -> None:
        item = self._transfers.get(tid)
        if item:
            if tid in self._pending_pause:
                self._pending_pause.discard(tid)
                item.status = TransferStatus.PAUSED
            else:
                item.status = TransferStatus.CANCELLED
            item.worker = None
            self._persist_item(item)
            self.transfer_cancelled.emit(tid)

    def _on_checkpoint(self, tid: str, state: dict) -> None:
        item = self._transfers.get(tid)
        if item:
            item.resume_state = state or {}
            self._persist_item(item)
            self.transfer_checkpoint.emit(tid)

    def _persist_item(self, item: TransferItem) -> None:
        self._cache.upsert_transfer(
            {
                "id": item.id,
                "direction": item.direction.value,
                "filename": item.filename,
                "bucket": item.bucket,
                "key_name": item.key,
                "local_path": item.local_path,
                "total_bytes": item.total_bytes,
                "bytes_done": item.bytes_done,
                "speed": item.speed,
                "status": item.status.name,
                "error": item.error,
                "resume_state": item.resume_state,
            }
        )

    def _load_cached_transfers(self) -> None:
        # Do not resurrect old transfer history on startup.
        # Stale RUNNING/QUEUED rows from previous sessions should not be shown.
        self._cache.delete_transfers_by_status(
            [
                TransferStatus.COMPLETED.name,
                TransferStatus.FAILED.name,
                TransferStatus.CANCELLED.name,
                TransferStatus.RUNNING.name,
                TransferStatus.QUEUED.name,
            ]
        )
        status_map = {s.name: s for s in TransferStatus}
        dir_map = {d.value: d for d in TransferDirection}
        for row in self._cache.load_transfers():
            try:
                item = TransferItem(
                    id=row["id"],
                    direction=dir_map[row["direction"]],
                    filename=row["filename"],
                    bucket=row["bucket"],
                    key=row["key_name"],
                    local_path=row["local_path"],
                    total_bytes=int(row["total_bytes"]),
                    bytes_done=int(row["bytes_done"]),
                    speed=float(row["speed"]),
                    status=status_map.get(row["status"], TransferStatus.CANCELLED),
                    error=row["error"],
                    resume_state=row.get("resume_state", {}),
                )
                if item.status in (TransferStatus.RUNNING, TransferStatus.QUEUED):
                    item.status = TransferStatus.CANCELLED
                self._transfers[item.id] = item
            except Exception:
                continue
