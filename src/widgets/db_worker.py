"""db_worker.py - look a van's cameras up in its database without freezing the window."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class DbWorker(QThread):
    done = Signal(str, object)          # van, camera_db.DbResult

    def __init__(self, van: str, parent=None) -> None:
        super().__init__(parent)
        self._van = van

    def run(self) -> None:
        from src.camera_db import lookup_cached
        self.done.emit(self._van, lookup_cached(self._van))
