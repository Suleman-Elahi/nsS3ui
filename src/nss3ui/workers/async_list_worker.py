"""
Async listing worker using aioboto3 + asyncio in a dedicated thread.
Keeps the Qt event loop completely free during S3 list operations.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional
from PySide6.QtCore import QRunnable, QObject, Signal
import aioboto3
from botocore.config import Config

log = logging.getLogger(__name__)

PAGE_SIZE = 1000


class AsyncListSignals(QObject):
    page_ready = Signal(list, list)   # objects, common_prefixes
    finished = Signal(str)            # next_continuation_token or ""
    error = Signal(str)


class AsyncBucketSignals(QObject):
    finished = Signal(list)
    error = Signal(str)


class AsyncListObjectsWorker(QRunnable):
    """
    Lists one page of S3 objects using aioboto3.
    Runs its own asyncio event loop in the thread pool.
    """

    def __init__(
        self,
        session_kwargs: dict,
        client_kwargs: dict,
        bucket: str,
        prefix: str = "",
        delimiter: str = "/",
        continuation_token: str = "",
    ):
        super().__init__()
        self.setAutoDelete(True)
        self._session_kwargs = session_kwargs
        self._client_kwargs = client_kwargs
        self._bucket = bucket
        self._prefix = prefix
        self._delimiter = delimiter
        self._token = continuation_token or None
        self.signals = AsyncListSignals()

    def run(self) -> None:
        try:
            asyncio.run(self._async_run())
        except Exception as exc:
            log.exception("AsyncListObjectsWorker failed")
            self._emit_safe(self.signals.error, str(exc))

    @staticmethod
    def _emit_safe(signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    async def _async_run(self) -> None:
        session = aioboto3.Session(**self._session_kwargs)
        async with session.client(**self._client_kwargs) as s3:
            kwargs: dict = {
                "Bucket": self._bucket,
                "Prefix": self._prefix,
                "Delimiter": self._delimiter,
                "MaxKeys": PAGE_SIZE,
            }
            if self._token:
                kwargs["ContinuationToken"] = self._token

            resp = await s3.list_objects_v2(**kwargs)
            objects = resp.get("Contents", [])
            prefixes = [p["Prefix"] for p in resp.get("CommonPrefixes", [])]
            next_token = resp.get("NextContinuationToken", "")
            self._emit_safe(self.signals.page_ready, objects, prefixes)
            self._emit_safe(self.signals.finished, next_token)


class AsyncListBucketsWorker(QRunnable):
    """Lists all buckets using aioboto3."""

    def __init__(self, session_kwargs: dict, client_kwargs: dict):
        super().__init__()
        self.setAutoDelete(True)
        self._session_kwargs = session_kwargs
        self._client_kwargs = client_kwargs
        self.signals = AsyncBucketSignals()

    def run(self) -> None:
        try:
            asyncio.run(self._async_run())
        except Exception as exc:
            log.exception("AsyncListBucketsWorker failed")
            self._emit_safe(self.signals.error, str(exc))

    @staticmethod
    def _emit_safe(signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    async def _async_run(self) -> None:
        session = aioboto3.Session(**self._session_kwargs)
        async with session.client(**self._client_kwargs) as s3:
            resp = await s3.list_buckets()
            self._emit_safe(self.signals.finished, resp.get("Buckets", []))
