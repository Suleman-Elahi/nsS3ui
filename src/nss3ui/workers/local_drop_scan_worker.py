"""Background scanner for dropped local files/folders."""
from __future__ import annotations

import os
from PySide6.QtCore import QRunnable
from nss3ui.workers.signals import WorkerSignals


class LocalDropScanWorker(QRunnable):
    """
    Expand dropped local paths into upload tasks without blocking the UI.
    Emits finished with list[(local_path, key)].
    """

    def __init__(self, paths: list[str], prefix: str):
        super().__init__()
        self.setAutoDelete(True)
        self._paths = paths
        self._prefix = prefix or ""
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            tasks: list[tuple[str, str]] = []
            for path in self._paths:
                if not os.path.exists(path):
                    continue
                if os.path.isfile(path):
                    key = self._prefix + os.path.basename(path)
                    tasks.append((path, key))
                    continue
                root_name = os.path.basename(path.rstrip("/\\"))
                key_root = self._prefix + root_name + "/"
                for dirpath, _dirnames, filenames in os.walk(path):
                    for filename in filenames:
                        local_path = os.path.join(dirpath, filename)
                        rel_path = os.path.relpath(local_path, path).replace("\\", "/")
                        tasks.append((local_path, key_root + rel_path))
            self.signals.finished.emit(tasks)
        except Exception as exc:
            self.signals.error.emit(str(exc))

