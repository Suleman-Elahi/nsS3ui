"""
Upload and download workers.

CRITICAL DESIGN NOTES:
- boto3 transfer manager may invoke progress callbacks from multiple internal
  threads; callbacks must therefore be thread-safe.
- setAutoDelete(False) keeps worker lifetime explicit while boto3 finishes.
- progress emits are throttled to keep UI updates smooth under heavy throughput.
"""
from __future__ import annotations
import os
import time
import threading
import logging
import mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QRunnable
from nss3ui.workers.signals import WorkerSignals
from nss3ui.s3client import S3Client
from nss3ui.config import get_transfer_tuning

log = logging.getLogger(__name__)

_THROTTLE_INTERVAL = 0.20  # seconds between UI progress updates


class UploadWorker(QRunnable):
    """Upload a single local file to S3."""

    def __init__(
        self,
        client: S3Client,
        local_path: str,
        bucket: str,
        key: str,
        transfer_id: str,
        resume_state: dict | None = None,
    ):
        super().__init__()
        self.setAutoDelete(False)   # we manage lifetime explicitly
        self._client = client.spawn()
        self._local_path = local_path
        self._bucket = bucket
        self._key = key
        self.transfer_id = transfer_id
        self.signals = WorkerSignals()
        self._cancel_flag = threading.Event()
        self._lock = threading.Lock()
        self._bytes_done = 0
        self._total = 0
        self._last_emit = 0.0
        self._last_bytes = 0
        self._last_time = 0.0
        self._resume_state = resume_state or {}
        self._executor: ThreadPoolExecutor | None = None

    def cancel(self) -> None:
        self._cancel_flag.set()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _emit(self, name: str, *args) -> None:
        try:
            getattr(self.signals, name).emit(*args)
        except RuntimeError:
            # UI/owner may be gone during shutdown/reconnect.
            pass

    def _progress(self, chunk: int) -> None:
        emit_now = False
        done = total = speed = 0
        with self._lock:
            if self._cancel_flag.is_set():
                raise InterruptedError("Upload cancelled")
            self._bytes_done += chunk
            now = time.monotonic()
            if now - self._last_emit >= _THROTTLE_INTERVAL:
                elapsed = now - self._last_time if self._last_time else 1.0
                speed = (self._bytes_done - self._last_bytes) / max(elapsed, 0.001)
                done, total = self._bytes_done, self._total
                self._last_emit = now
                self._last_bytes = self._bytes_done
                self._last_time = now
                emit_now = True
        if emit_now:
            self._emit("progress", done, total)
            self._emit("speed", speed)

    def run(self) -> None:
        try:
            self._total = os.path.getsize(self._local_path)
            self._last_time = time.monotonic()
            self._emit("started")
            self._upload_resumable_multipart()
            self._emit("finished", self.transfer_id)
        except InterruptedError:
            self._emit("cancelled")
        except Exception as exc:
            log.exception("UploadWorker failed: %s", self._key)
            self._emit("error", str(exc))

    def _upload_resumable_multipart(self) -> None:
        extra_args = self._build_upload_extra_args()
        # Fast path for normal transfers: boto3 managed transfer is fastest.
        # Use custom resumable multipart only when we already have resume state.
        if not self._resume_state or not self._resume_state.get("upload_id"):
            self._client.upload_file(
                self._local_path,
                self._bucket,
                self._key,
                progress_callback=self._progress,
                extra_args=extra_args,
            )
            return
        tune = get_transfer_tuning()
        part_size = int(tune["multipart_chunksize_mb"]) * 1024 * 1024
        max_workers = int(tune["max_concurrency"])

        part_count = (self._total + part_size - 1) // part_size
        state_parts = self._resume_state.get("parts", {})
        upload_id = self._resume_state.get("upload_id")

        # Restore done bytes from known uploaded parts.
        for pnum in state_parts:
            if str(pnum).isdigit():
                pn = int(pnum)
                start = (pn - 1) * part_size
                end = min(self._total, start + part_size)
                self._bytes_done += max(0, end - start)

        to_upload = [pn for pn in range(1, part_count + 1) if str(pn) not in state_parts]
        if self._cancel_flag.is_set():
            raise InterruptedError("Upload cancelled")

        def upload_one(part_number: int) -> tuple[int, str, int]:
            if self._cancel_flag.is_set():
                raise InterruptedError("Upload cancelled")
            start = (part_number - 1) * part_size
            end = min(self._total, start + part_size)
            with open(self._local_path, "rb") as fh:
                fh.seek(start)
                body = fh.read(end - start)
            etag = self._client.upload_part(
                self._bucket, self._key, upload_id, part_number, body
            )
            return part_number, etag, len(body)

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            self._executor = ex
            futures = [ex.submit(upload_one, pn) for pn in to_upload]
            for fut in as_completed(futures):
                if self._cancel_flag.is_set():
                    raise InterruptedError("Upload cancelled")
                part_number, etag, nbytes = fut.result()
                state_parts[str(part_number)] = etag
                self._progress(nbytes)
                self._emit("checkpoint", {"upload_id": upload_id, "parts": state_parts})
        self._executor = None

        parts = [{"PartNumber": pn, "ETag": state_parts[str(pn)]} for pn in range(1, part_count + 1)]
        if self._cancel_flag.is_set():
            self._client.abort_multipart_upload(self._bucket, self._key, upload_id)
            raise InterruptedError("Upload cancelled")
        self._client.complete_multipart_upload(self._bucket, self._key, upload_id, parts)
        self._emit("checkpoint", {})

    def _build_upload_extra_args(self) -> dict:
        """
        Attach best-effort content metadata so browsers/openers handle files correctly.
        """
        content_type, content_encoding = mimetypes.guess_type(self._local_path)
        args = {
            "ContentType": content_type or "application/octet-stream",
        }
        if content_encoding:
            args["ContentEncoding"] = content_encoding
        return args


class DownloadWorker(QRunnable):
    """Download a single S3 object."""

    def __init__(
        self,
        client: S3Client,
        bucket: str,
        key: str,
        local_path: str,
        total_bytes: int,
        transfer_id: str,
        resume_state: dict | None = None,
    ):
        super().__init__()
        self.setAutoDelete(False)   # we manage lifetime explicitly
        self._client = client.spawn()
        self._bucket = bucket
        self._key = key
        self._local_path = local_path
        self._total = total_bytes
        self.transfer_id = transfer_id
        self.signals = WorkerSignals()
        self._cancel_flag = threading.Event()
        self._lock = threading.Lock()
        self._bytes_done = 0
        self._last_emit = 0.0
        self._last_bytes = 0
        self._last_time = 0.0
        self._resume_state = resume_state or {}

    def cancel(self) -> None:
        self._cancel_flag.set()

    def _emit(self, name: str, *args) -> None:
        try:
            getattr(self.signals, name).emit(*args)
        except RuntimeError:
            pass

    def _progress(self, chunk: int) -> None:
        emit_now = False
        done = total = speed = 0
        with self._lock:
            if self._cancel_flag.is_set():
                raise InterruptedError("Download cancelled")
            self._bytes_done += chunk
            now = time.monotonic()
            if now - self._last_emit >= _THROTTLE_INTERVAL:
                elapsed = now - self._last_time if self._last_time else 1.0
                speed = (self._bytes_done - self._last_bytes) / max(elapsed, 0.001)
                done, total = self._bytes_done, self._total
                self._last_emit = now
                self._last_bytes = self._bytes_done
                self._last_time = now
                emit_now = True
        if emit_now:
            self._emit("progress", done, total)
            self._emit("speed", speed)

    def run(self) -> None:
        try:
            # Ensure destination directory exists
            dest_dir = os.path.dirname(self._local_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)

            self._last_time = time.monotonic()
            self._emit("started")
            self._download_resumable()
            self._emit("finished", self.transfer_id)
        except InterruptedError:
            self._emit("cancelled")
        except Exception as exc:
            log.exception("DownloadWorker failed: %s", self._key)
            self._emit("error", str(exc))

    def _download_resumable(self) -> None:
        # Fast path for normal transfers: boto3 managed transfer is fastest.
        # Use range-based resumable flow only when resume state exists.
        if not self._resume_state or not self._resume_state.get("temp_path"):
            self._client.download_file(
                self._bucket,
                self._key,
                self._local_path,
                progress_callback=self._progress,
            )
            self._emit("checkpoint", {})
            return

        temp_path = self._resume_state.get("temp_path") or f"{self._local_path}.part"
        done = 0
        if os.path.exists(temp_path):
            done = os.path.getsize(temp_path)
        self._bytes_done = done
        self._emit("checkpoint", {"temp_path": temp_path})
        if self._total <= 0:
            self._total = self._client.head_object(self._bucket, self._key).get("ContentLength", 0)

        chunk_size = 8 * 1024 * 1024
        with open(temp_path, "ab") as fh:
            offset = done
            while offset < self._total:
                if self._cancel_flag.is_set():
                    raise InterruptedError("Download cancelled")
                end = min(self._total - 1, offset + chunk_size - 1)
                data = self._client.get_object_range(self._bucket, self._key, offset, end)
                if not data:
                    break
                fh.write(data)
                n = len(data)
                offset += n
                self._progress(n)
                self._emit("checkpoint", {"temp_path": temp_path})
        os.replace(temp_path, self._local_path)
        self._emit("checkpoint", {})


class DeleteWorker(QRunnable):
    """Delete one or more S3 objects."""

    def __init__(self, client: S3Client, bucket: str, keys: list[str]):
        super().__init__()
        self.setAutoDelete(True)
        self._client = client.spawn()
        self._bucket = bucket
        self._keys = keys
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            failed: list[str] = []
            chunk_size = 1000  # S3 DeleteObjects API limit
            for i in range(0, len(self._keys), chunk_size):
                chunk = self._keys[i:i + chunk_size]
                failed.extend(self._client.delete_objects(self._bucket, chunk))
            self.signals.finished.emit(failed)
        except Exception as exc:
            log.exception("DeleteWorker failed")
            self.signals.error.emit(str(exc))


class PreviewWorker(QRunnable):
    """Fetch first N bytes of an object for preview."""

    def __init__(self, client: S3Client, bucket: str, key: str, max_bytes: int = 65536):
        super().__init__()
        self.setAutoDelete(True)
        self._client = client.spawn()
        self._bucket = bucket
        self._key = key
        self._max_bytes = max_bytes
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            data = self._client.get_object_partial(self._bucket, self._key, self._max_bytes)
            self.signals.finished.emit(data)
        except Exception as exc:
            log.exception("PreviewWorker failed")
            self.signals.error.emit(str(exc))
