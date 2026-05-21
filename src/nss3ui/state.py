"""Centralized application state."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from PySide6.QtCore import QObject, Signal


@dataclass
class AppState:
    """Mutable application state shared across components."""
    current_profile: str = "default"
    current_bucket: Optional[str] = None
    current_prefix: str = ""
    current_region: str = "us-east-1"
    endpoint_url: Optional[str] = None
    selected_keys: list[str] = field(default_factory=list)


class AppStateManager(QObject):
    """Qt-aware wrapper that emits signals on state changes."""

    bucket_changed = Signal(str)          # bucket name
    prefix_changed = Signal(str)          # prefix / path
    profile_changed = Signal(str)         # profile name
    selection_changed = Signal(list)      # list of selected keys

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()

    @property
    def state(self) -> AppState:
        return self._state

    def set_bucket(self, bucket: str, prefix: str = "") -> None:
        self._state.current_bucket = bucket
        self._state.current_prefix = prefix
        self.bucket_changed.emit(bucket)
        self.prefix_changed.emit(prefix)

    def set_prefix(self, prefix: str) -> None:
        self._state.current_prefix = prefix
        self.prefix_changed.emit(prefix)

    def set_profile(self, profile: str) -> None:
        self._state.current_profile = profile
        self.profile_changed.emit(profile)

    def set_selection(self, keys: list[str]) -> None:
        self._state.selected_keys = keys
        self.selection_changed.emit(keys)
