"""Worker to rename/move a folder prefix by copy + delete."""
from __future__ import annotations

import logging
from PySide6.QtCore import QRunnable
from nss3ui.s3client import S3Client
from nss3ui.workers.signals import WorkerSignals

log = logging.getLogger(__name__)


class PrefixMoveWorker(QRunnable):
    """Move all objects from one prefix to another within the same bucket."""

    def __init__(self, client: S3Client, bucket: str, src_prefix: str, dst_prefix: str):
        super().__init__()
        self.setAutoDelete(True)
        self._client = client.spawn()
        self._bucket = bucket
        self._src_prefix = src_prefix
        self._dst_prefix = dst_prefix
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.started.emit()
            if self._src_prefix == self._dst_prefix:
                self.signals.error.emit("Source and destination prefixes are the same.")
                return

            objects = list(self._client.list_all_objects(self._bucket, self._src_prefix))
            total = len(objects)
            if total == 0:
                self.signals.error.emit("Folder is empty — nothing to move.")
                return

            old_keys: list[str] = []
            for idx, obj in enumerate(objects, start=1):
                src_key = obj.get("Key")
                if not src_key:
                    continue
                suffix = src_key[len(self._src_prefix):]
                dst_key = self._dst_prefix + suffix
                self._client.copy_object(self._bucket, src_key, self._bucket, dst_key)
                old_keys.append(src_key)
                self.signals.progress.emit(idx, total)

            failed_delete: list[str] = []
            chunk_size = 1000
            for i in range(0, len(old_keys), chunk_size):
                failed_delete.extend(
                    self._client.delete_objects(self._bucket, old_keys[i:i + chunk_size])
                )

            self.signals.finished.emit(
                {
                    "moved_count": len(old_keys),
                    "failed_delete_count": len(failed_delete),
                    "failed_delete": failed_delete,
                    "dst_prefix": self._dst_prefix,
                }
            )
        except Exception as exc:
            log.exception("PrefixMoveWorker failed")
            self.signals.error.emit(str(exc))

