"""
FolderDownloadWorker — downloads all objects under a prefix as a ZIP file.
Runs entirely in a QRunnable thread, never touches the UI.
"""
from __future__ import annotations
import os
import threading
import time
import zipfile
import logging
from PySide6.QtCore import QRunnable
from nss3ui.workers.signals import WorkerSignals
from nss3ui.s3client import S3Client

log = logging.getLogger(__name__)

_THROTTLE = 0.15


class FolderDownloadWorker(QRunnable):
    """
    Lists all objects under `prefix`, downloads them into a ZIP at `zip_path`.
    Emits progress(bytes_done, bytes_total) and finished(zip_path).
    """

    def __init__(
        self,
        client: S3Client,
        bucket: str,
        prefix: str,
        zip_path: str,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self._client = client.spawn()
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/"
        self._zip_path = zip_path
        self.signals = WorkerSignals()
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            self.signals.started.emit()

            # Phase 1: collect all keys and sizes
            all_objects = list(self._client.list_all_objects(self._bucket, self._prefix))
            if not all_objects:
                self.signals.error.emit("Folder is empty — nothing to download.")
                return

            total_bytes = sum(o.get("Size", 0) for o in all_objects)
            bytes_done = 0
            last_emit = 0.0
            last_bytes = 0
            last_time = time.monotonic()

            os.makedirs(os.path.dirname(self._zip_path) or ".", exist_ok=True)

            with zipfile.ZipFile(self._zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                for obj in all_objects:
                    if self._cancelled.is_set():
                        self.signals.cancelled.emit()
                        return

                    key: str = obj["Key"]
                    # Archive name = path relative to the prefix
                    arc_name = key[len(self._prefix):]
                    if not arc_name:
                        continue  # skip the "folder" placeholder object

                    resp = self._client.raw.get_object(Bucket=self._bucket, Key=key)
                    body = resp["Body"]
                    chunk_size = 1024 * 1024  # 1 MB chunks
                    with zf.open(arc_name, "w") as out:
                        while True:
                            if self._cancelled.is_set():
                                self.signals.cancelled.emit()
                                return
                            chunk = body.read(chunk_size)
                            if not chunk:
                                break
                            out.write(chunk)
                            bytes_done += len(chunk)
                            now = time.monotonic()
                            if now - last_emit >= _THROTTLE:
                                elapsed = now - last_time if last_time else 1
                                speed = (bytes_done - last_bytes) / max(elapsed, 0.001)
                                self.signals.progress.emit(bytes_done, total_bytes)
                                self.signals.speed.emit(speed)
                                last_emit = now
                                last_bytes = bytes_done
                                last_time = now

            self.signals.progress.emit(total_bytes, total_bytes)
            self.signals.finished.emit(self._zip_path)

        except Exception as exc:
            log.exception("FolderDownloadWorker failed")
            self.signals.error.emit(str(exc))
