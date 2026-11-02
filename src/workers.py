"""workers.py — background threads for the GUI.  Both run src/pipeline.run_folder.

FolderWorker        One camera: one folder.
VanIntrinsicWorker  Whole van: every camera folder, one after the other.
"""

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


class VanIntrinsicWorker(QThread):
    """jobs: list of (row, folder, filed_xml).  Emits row_started(row, text),
    row_progress(row, text) and row_finished(row, FolderRun)."""

    row_started  = Signal(int, str)
    row_progress = Signal(int, str)
    row_finished = Signal(int, object)
    all_done     = Signal()

    def __init__(self, jobs, max_images: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._jobs = list(jobs)
        self._max_images = max_images
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from src.boards import list_boards
        from src.pipeline import run_folder
        boards = list_boards()
        try:
            import cv2
            cv2.setNumThreads(0)       # detection runs its own process pool
        except Exception:  # noqa: BLE001
            pass
        for row, folder, filed in self._jobs:
            if self._stop:
                break
            self.row_started.emit(row, "starting")
            res = run_folder(folder, self._max_images, boards=boards, filed_xml=filed,
                             progress_cb=lambda m, r=row: self.row_progress.emit(r, m))
            self.row_finished.emit(row, res)
        self.all_done.emit()
