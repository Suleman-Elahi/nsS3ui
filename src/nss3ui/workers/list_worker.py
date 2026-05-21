"""Worker that lists S3 objects one page at a time."""
from __future__ import annotations
import logging
from PySide6.QtCore import QRunnable
from nss3ui.workers.signals import ListSignals, BucketListSignals
from nss3ui.s3client import S3Client

log = logging.getLogger(__name__)


class ListObjectsWorker(QRunnable):
    """Fetch one page of objects and emit page_ready."""

    def __init__(
        self,
        client: S3Client,
        bucket: str,
        prefix: str = "",
        delimiter: str = "/",
        continuation_token: str = "",
    ):
        super().__init__()
        self.setAutoDelete(True)
        self._client = client
        self._bucket = bucket
        self._prefix = prefix
        self._delimiter = delimiter
        self._token = continuation_token or None
        self.signals = ListSignals()

    def run(self) -> None:
        try:
            resp = self._client.list_objects_page(
                self._bucket,
                self._prefix,
                self._delimiter,
                self._token,
            )
            objects = resp.get("Contents", [])
            prefixes = [p["Prefix"] for p in resp.get("CommonPrefixes", [])]
            next_token = resp.get("NextContinuationToken", "")
            self.signals.page_ready.emit(objects, prefixes)
            self.signals.finished.emit(next_token)
        except Exception as exc:
            log.exception("ListObjectsWorker failed")
            self.signals.error.emit(str(exc))


class ListBucketsWorker(QRunnable):
    """Fetch all buckets."""

    def __init__(self, client: S3Client):
        super().__init__()
        self.setAutoDelete(True)
        self._client = client
        self.signals = BucketListSignals()

    def run(self) -> None:
        try:
            buckets = self._client.list_buckets()
            self.signals.finished.emit(buckets)
        except Exception as exc:
            log.exception("ListBucketsWorker failed")
            self.signals.error.emit(str(exc))
