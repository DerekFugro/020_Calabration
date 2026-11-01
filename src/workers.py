"""workers.py — QThread workers for detection and calibration.

Both workers follow the same contract:
  - emit progress(str) for status-bar updates
  - emit finished(...) on success
  - emit error(str) on exception

The slots connected to finished() run on the main (GUI) thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.board import BoardConfig
from src.calibrator import CalibrationResult, calibrate
from src.detector import DetectionResult, detect_images
from src.image_filter import FilterResult, filter_detections
from src.quality import QualityReport, evaluate


# Dot boards: a match needs enough dots for a stable homography.
MIN_DOTS_PER_IMAGE = 12


class DetectionWorker(QThread):
    """Runs board detection + image filtering off the GUI thread.

    board_config=None means Auto-detect: the board is picked from
    board_candidates using sample images (src/auto_detect.py) and reported
    through board_resolved before detection starts.
    """

    progress = Signal(str)
    board_resolved = Signal(object, str)   # BoardConfig, summary text
    finished = Signal(list, list)   # list[DetectionResult], list[FilterResult]
    error    = Signal(str)

    def __init__(
        self,
        image_paths: list[str],
        board_config: BoardConfig | None,
        min_blur: float = 20.0,
        raw_folder: str | None = None,
        parent=None,
        board_candidates: list[BoardConfig] | None = None,
    ) -> None:
        super().__init__(parent)
        self._image_paths = image_paths
        self._board_config = board_config
        self._board_candidates = board_candidates or []
        self._min_blur = min_blur
        self._raw_folder = raw_folder  # when set: convert .raw → .png first

    def run(self) -> None:  # executes on the worker thread
        try:
            if self._raw_folder is not None:
                from src.raw_loader import convert_folder
                from src.utils import find_images

                converted, failed = convert_folder(
                    self._raw_folder, progress_cb=self.progress.emit
                )
                if converted or failed:
                    self.progress.emit(
                        f"Raw conversion: {len(converted)} converted"
                        + (f", {len(failed)} FAILED" if failed else "")
                    )
                if converted:
                    # Re-scan so the new PNGs join the detection batch.
                    self._image_paths = find_images(self._raw_folder)
            n = len(self._image_paths)
            if self._board_config is None:
                from src.auto_detect import auto_detect_board
                res = auto_detect_board(
                    self._image_paths, self._board_candidates,
                    progress_cb=self.progress.emit,
                )
                if res.board is None:
                    raise RuntimeError(
                        res.summary() + ".  Pick the board from the Board "
                        "list and run again."
                    )
                self._board_config = res.board
                self.board_resolved.emit(res.board, res.summary())
            self.progress.emit(
                f"Detecting {self._board_config.name} in {n} image(s)…"
            )
            detections = detect_images(
                self._image_paths, self._board_config, verbose=False,
                progress_cb=self.progress.emit,
            )
            self.progress.emit("Applying image filters…")
            if self._board_config.is_dots:
                # No blur filter for dot boards: the Laplacian blur score is
                # 5-15 even on sharp dot photos (few edges), so the chessboard
                # limit of 20 threw out good sets.  Blurry dot photos show up
                # as high per-photo error instead (grading lists them).
                filter_results = filter_detections(
                    detections, min_corners=MIN_DOTS_PER_IMAGE, min_blur=0.0,
                )
            else:
                filter_results = filter_detections(detections, min_blur=self._min_blur)
            accepted = sum(f.accepted for f in filter_results)
            self.progress.emit(
                f"Detection complete — {accepted} accepted, "
                f"{n - accepted} rejected out of {n} images."
            )
            self.finished.emit(detections, filter_results)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class CalibrationWorker(QThread):
    """Runs camera calibration off the GUI thread."""

    progress = Signal(str)
    finished = Signal(object, object)   # CalibrationResult, QualityReport
    error    = Signal(str)

    def __init__(
        self,
        detections: list[DetectionResult],
        filter_results: list[FilterResult],
        board_config: BoardConfig,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._detections = detections
        self._filter_results = filter_results
        self._board_config = board_config

    def run(self) -> None:
        try:
            self.progress.emit("Running camera calibration…")
            cal_result = calibrate(
                self._detections, self._filter_results, self._board_config
            )
            self.progress.emit("Evaluating calibration quality…")
            quality = evaluate(cal_result)
            self.progress.emit("Grading: coverage and repeatability…")
            from src.grading import grade
            cal_result.grade = grade(cal_result)
            self.progress.emit(
                f"Calibration complete — RMS {cal_result.rms:.4f} px  "
                f"({quality.verdict})"
            )
            self.finished.emit(cal_result, quality)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class VanIntrinsicWorker(QThread):
    """Grades every camera folder of a van, one after the other.

    jobs: list of (row, folder, filed_xml).  Emits row_started(row, text),
    row_progress(row, text) and row_finished(row, FolderRun).
    """

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
        import cv2
        boards = list_boards()
        try:
            cv2.setNumThreads(0)
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
