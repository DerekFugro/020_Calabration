"""main_window.py — Application root window.

Hosts the three screens in a QStackedWidget and orchestrates:
  1. SetupScreen  →  DetectionWorker  →  ImageReviewScreen
  2. ImageReviewScreen  →  CalibrationWorker  →  ReportScreen
  3. ReportScreen  →  write_outputs() + calibration_store.publish()
     →  back to SetupScreen

Saving does two things: the working CAL_ files land next to the images, and a
copy of the YAML is published to the shared calibration store
(`H:\\001_Mahine_App_Specs\\Calibrations`, master doc §11) as
`YYYYMMDD_HHMMSS_<Type>\\<ROLE>_<SERIAL>.yaml`, where the Type names the
camera (`PaveIntrinsic` / `ROWIntrinsic`).  Only a PASSING calibration is
published — the store is append-only, so a bad one could never be cleaned out.
A failed publish never costs you the local files.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget

from src.board import BoardConfig
from src.calibrator import CalibrationResult
from src.calibration_store import StoreError, publish, store_path
from src.output_writer import write_outputs
from src.quality import QualityReport
from src.styles import STYLESHEET_MAIN, build_dark_palette
from src.widgets.image_review_screen import ImageReviewScreen
from src.widgets.report_screen import ReportScreen
from src.widgets.setup_screen import SetupScreen
from src.utils import find_images
from src.workers import CalibrationWorker, DetectionWorker

# ── Layout constants ─────────────────────────────────────────────────────────
_WIN_W = 1100
_WIN_H = 780


class MainWindow(QMainWindow):
    """Top-level window — manages screens, workers, and application state."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Application state (flows between screens)
        self._serial:         str                    = ""
        self._role:           str                    = ""
        self._image_folder:   str                    = ""
        self._board_config:   BoardConfig            = BoardConfig()
        self._detections:     list                   = []
        self._filter_results: list                   = []
        self._cal_result:     CalibrationResult | None = None
        self._quality:        QualityReport | None   = None
        self.van:             str                    = ""   # set by AppWindow's van bar
        # Workers (kept alive until replaced)
        self._detection_worker:    DetectionWorker | None    = None
        self._calibration_worker:  CalibrationWorker | None  = None

        self._create_widgets()
        self._create_layouts()
        self._connect_signals()
        self._apply_styles()
        self._load_initial_state()

    # ── Widget Construction ───────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        self.stack          = QStackedWidget()
        self.setup_screen   = SetupScreen()
        self.review_screen  = ImageReviewScreen()
        self.report_screen  = ReportScreen()

    # ── Layout ────────────────────────────────────────────────────────────────
    def _create_layouts(self) -> None:
        self.stack.addWidget(self.setup_screen)   # index 0
        self.stack.addWidget(self.review_screen)  # index 1
        self.stack.addWidget(self.report_screen)  # index 2
        self.setCentralWidget(self.stack)

    # ── Signals & Slots ───────────────────────────────────────────────────────
    def _connect_signals(self) -> None:
        self.setup_screen.run_requested.connect(self._on_run_requested)
        self.review_screen.back_requested.connect(self.go_to_setup)
        self.review_screen.proceed_requested.connect(self._on_proceed_requested)
        self.report_screen.save_requested.connect(self._on_save_requested)
        self.report_screen.new_calibration_requested.connect(
            self._on_new_calibration_requested
        )
        self.report_screen.remove_and_recalibrate_requested.connect(
            self._on_remove_and_recalibrate
        )

    # ── Styling ───────────────────────────────────────────────────────────────
    def _apply_styles(self) -> None:
        self.setStyleSheet(STYLESHEET_MAIN)

    # ── Initial State ─────────────────────────────────────────────────────────
    def _load_initial_state(self) -> None:
        self.setWindowTitle("Calibration")
        self.resize(_WIN_W, _WIN_H)
        self.statusBar().showMessage("Ready.")

    # ── Public helpers (called from child screens) ────────────────────────────
    def go_to_setup(self) -> None:
        self.stack.setCurrentIndex(0)
        self.setup_screen.set_busy(False)

    # ── Detection flow ────────────────────────────────────────────────────────
    def _on_run_requested(
        self,
        folder: str,
        serial: str,
        board_config: BoardConfig,
    ) -> None:
        self._image_folder = folder
        self._serial       = serial
        self._role         = self.setup_screen.camera_role
        self._board_config = board_config

        from src.raw_loader import pending_conversions

        image_paths = find_images(folder)
        pending_raws = pending_conversions(folder)
        if not image_paths and not pending_raws:
            QMessageBox.warning(
                self,
                "No Images Found",
                f"No JPG, PNG, or RAW images were found in:\n{folder}",
            )
            return

        self.setup_screen.set_busy(True)
        raw_note = (
            f" (+{len(pending_raws)} raw to convert)" if pending_raws else ""
        )
        self.statusBar().showMessage(
            f"Starting detection on {len(image_paths)} image(s){raw_note}…"
        )

        self._detection_worker = DetectionWorker(
            image_paths, board_config,
            min_blur=self.setup_screen.min_blur_score,
            raw_folder=folder if pending_raws else None,
            parent=self,
            board_candidates=self.setup_screen.board_candidates,
            move_folder=folder if self.setup_screen.move_unused else None,
        )
        self._detection_worker.progress.connect(self.statusBar().showMessage)
        self._detection_worker.board_resolved.connect(self._on_board_resolved)
        self._detection_worker.finished.connect(self._on_detection_finished)
        self._detection_worker.error.connect(self._on_worker_error)
        self._detection_worker.start()

    def _on_board_resolved(self, board: BoardConfig, summary: str) -> None:
        """Auto-detect picked the board; everything downstream uses it."""
        self._board_config = board
        self.statusBar().showMessage(summary)

    def _on_detection_finished(
        self,
        detections: list,
        filter_results: list,
    ) -> None:
        self._detections     = detections
        self._filter_results = filter_results
        self.review_screen.set_data(detections, filter_results)
        self.stack.setCurrentIndex(1)
        accepted = sum(f.accepted for f in filter_results)
        self.statusBar().showMessage(
            f"Detection complete ({self._board_config.name}) — {accepted} accepted, "
            f"{len(filter_results) - accepted} rejected."
        )

    # ── Calibration flow ──────────────────────────────────────────────────────
    def _on_proceed_requested(self) -> None:
        self.statusBar().showMessage("Running camera calibration…")

        self._calibration_worker = CalibrationWorker(
            self._detections,
            self._filter_results,
            self._board_config,
            parent=self,
        )
        self._calibration_worker.progress.connect(self.statusBar().showMessage)
        self._calibration_worker.finished.connect(self._on_calibration_finished)
        self._calibration_worker.error.connect(self._on_worker_error)
        self._calibration_worker.start()

    def _on_calibration_finished(
        self,
        cal_result: CalibrationResult,
        quality: QualityReport,
    ) -> None:
        self._cal_result = cal_result
        self._quality    = quality
        self.report_screen.set_data(cal_result, quality, self._board_config)
        self.stack.setCurrentIndex(2)
        self.statusBar().showMessage(
            f"Calibration complete — RMS {cal_result.rms:.4f} px  "
            f"({quality.verdict})"
        )

    # ── Save flow ─────────────────────────────────────────────────────────────
    def _on_save_requested(self) -> None:
        if self._cal_result is None or self._quality is None:
            return

        # One datetime for everything: the local CAL_ pair and the store file
        # all carry the same stamp, so a store entry can always be traced back
        # to its working files.
        dt = datetime.now()

        try:
            yaml_path, pdf_path = write_outputs(
                self._cal_result,
                self._quality,
                self._board_config,
                self._serial,
                self._detections,
                self._filter_results,
                self._image_folder,
                dt=dt,
                role=self._role,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Error", str(exc))
            return

        local_note = (
            f"YAML:  {yaml_path.name}\n"
            f"PDF:   {pdf_path.name}\n\n"
            f"Saved to:\n{self._image_folder}"
        )
        local_note += self._export_fleet_formats(dt)

        stored_path, store_error = self._publish_to_store(yaml_path, dt)

        if stored_path is not None:
            QMessageBox.information(
                self,
                "Files Saved",
                f"{local_note}\n\n"
                f"Published to the calibration store:\n"
                f"{stored_path.parent.name}\\{stored_path.name}\n"
                f"{stored_path.parent.parent}",
            )
            self.statusBar().showMessage(
                f"Saved: {yaml_path.name}  ·  published: {stored_path.name}"
            )
        else:
            QMessageBox.warning(
                self,
                "Saved Locally — Not Published",
                f"{local_note}\n\n"
                f"The calibration was NOT published to the store:\n"
                f"{store_error}\n\n"
                f"Store: {store_path()}",
            )
            self.statusBar().showMessage(
                f"Saved: {yaml_path.name}  ·  NOT published to the store", 12000
            )

    def _export_fleet_formats(self, dt: datetime) -> str:
        """Fleet cameras: also write every format (src/export_formats.py)."""
        from src.van_scan import camera_from_name
        cam = camera_from_name(self._role)
        if not cam or cam == "PAVE":
            return ""
        if not self.van:
            return "\n\nOther formats not written: type the van (e.g. ARAN65) in the van bar."
        try:
            from src.export_formats import Intrinsics, export_all
            c = Intrinsics.from_result(self._cal_result, self.van, cam, self._serial,
                                       board=self._board_config.name, date=dt)
            out = Path(self._image_folder) / f"Calibration_{dt:%Y%m%d_%H%M%S}"
            files = export_all(c, out)
            return f"\n\nAll formats ({len(files)} files) in:\n{out}"
        except Exception as exc:  # noqa: BLE001
            return f"\n\nOther formats FAILED: {exc}"

    def _publish_to_store(
        self,
        yaml_path: Path,
        dt: datetime,
    ) -> tuple[Path | None, str]:
        """Copy the YAML into the shared calibration store.

        Returns (path, "") on success, (None, reason) on failure.  A failure
        here is never fatal — the local files are already written.  A failing
        calibration lands here on purpose: it is refused, not published.
        """
        if not self._role:
            return None, (
                "No camera role was set, so the store filename cannot be built. "
                "Pick a role on the setup screen and save again."
            )
        try:
            return publish(
                yaml_path,
                self._role,
                self._serial,
                dt,
                passed=self._publish_passed(),
            ), ""
        except StoreError as exc:
            return None, str(exc)
        except OSError as exc:  # noqa: BLE001 — drive offline, permissions, …
            return None, f"Could not write to the store: {exc}"

    def _publish_passed(self) -> bool | None:
        """The grade decides when there is one (src/grading.py); else the RMS verdict."""
        g = getattr(self._cal_result, "grade", None)
        if g is not None:
            return bool(g.passed)
        return self._quality.pass_verdict if self._quality else None

    # ── Result handed over from the van table ─────────────────────────────────
    def show_result(self, folder, role, serial, board, detections,
                    filter_results, cal_result, quality) -> None:
        """Open the full report for a camera already graded in the van table."""
        self._image_folder, self._role, self._serial = folder, role, serial
        self._board_config = board
        self._detections, self._filter_results = detections, filter_results
        self._cal_result, self._quality = cal_result, quality
        self.setup_screen.set_inputs(folder, role, serial)
        self.report_screen.set_data(cal_result, quality, board)
        self.stack.setCurrentIndex(2)
        self.statusBar().showMessage(f"{role} {serial}: {cal_result.grade.headline}")

    # ── New calibration ───────────────────────────────────────────────────────
    def _on_new_calibration_requested(self) -> None:
        self.go_to_setup()
        self.statusBar().showMessage("Ready for a new calibration run.")
    # ── Remove outliers and recalibrate ──────────────────────────────────
    def _on_remove_and_recalibrate(self, paths_to_remove: list) -> None:
        """Mark flagged images as rejected and re-run calibration."""
        remove_set = set(paths_to_remove)
        n_removed = 0
        for i, det in enumerate(self._detections):
            if det.image_path in remove_set and self._filter_results[i].accepted:
                from src.image_filter import FilterResult
                self._filter_results[i] = FilterResult(
                    accepted=False,
                    reason="Removed: high reprojection error",
                    corner_count=self._filter_results[i].corner_count,
                    blur_score=self._filter_results[i].blur_score,
                )
                n_removed += 1

        self.statusBar().showMessage(
            f"Removed {n_removed} image(s). Re-running calibration…"
        )
        self._on_proceed_requested()
    # ── Worker error ──────────────────────────────────────────────────────────
    def _on_worker_error(self, message: str) -> None:
        self.setup_screen.set_busy(False)
        QMessageBox.critical(self, "Error", message)
        self.statusBar().showMessage(f"Error: {message}", 8000)


