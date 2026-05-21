"""Shared signal objects for workers (QRunnable cannot inherit QObject directly)."""
from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    """Generic signals emitted by background workers."""
    started = Signal()
    progress = Signal(int, int)      # bytes_done, bytes_total
    speed = Signal(float)            # bytes/sec
    finished = Signal(object)        # result payload
    error = Signal(str)              # error message
    cancelled = Signal()
    checkpoint = Signal(object)      # transfer resume state payload


class ListSignals(QObject):
    """Signals for object listing workers."""
    page_ready = Signal(list, list)  # objects, common_prefixes
    finished = Signal(str)           # continuation token or ""
    error = Signal(str)


class BucketListSignals(QObject):
    finished = Signal(list)          # list of bucket dicts
    error = Signal(str)
