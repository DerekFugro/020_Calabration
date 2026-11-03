"""workers.py — background thread for Load Intrinsic: runs src/pipeline.run_folder on one folder."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class FolderWorker(QThread):
    progress = Signal(str)
    done = Signal(object)              # FolderRun (check .error)

    def __init__(self, folder: str, board=None, parent=None) -> None:
        super().__init__(parent)
        self._folder, self._board = folder, board

    def run(self) -> None:
        from src.pipeline import run_folder
        self.done.emit(run_folder(self._folder, board=self._board,
                                      progress_cb=self.progress.emit))
