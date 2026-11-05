"""one_camera_screen.py — Load Intrinsic > One camera.

  Setup (folder, camera, serial)  ->  FolderWorker (src/pipeline.run_folder)  ->  Report

Saving writes everything next to the photos: the working CAL_ files, and every
other format into Calibration_<date> (fleet cameras).  Nothing is saved anywhere
else (Derek, 2026-11-05: the app is now a generic calibration tool; there is no
shared calibration store).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from src.output_writer import write_outputs
from src.widgets.report_screen import ReportScreen
from src.widgets.setup_screen import SetupScreen


class OneCameraScreen(QWidget):
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.van = ""                  # set from the van bar
        self._run = None               # FolderRun on show
        self._role = self._serial = ""
        self._worker = None

        self.setup_screen = SetupScreen()
        self.report_screen = ReportScreen()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.setup_screen)
        self.stack.addWidget(self.report_screen)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        self.setup_screen.run_requested.connect(self._on_run_requested)
        self.report_screen.save_requested.connect(self._save)
        self.report_screen.new_calibration_requested.connect(self._back_to_setup)

    # ── Run ───────────────────────────────────────────────────────────────────
    def _on_run_requested(self, folder: str, serial: str, board) -> None:
        if not self._ask_about_previous(folder):
            return
        self._role, self._serial = self.setup_screen.camera_role, serial
        self.setup_screen.set_busy(True)
        from src.workers import FolderWorker
        self._worker = FolderWorker(folder, board, parent=self)
        self._worker.progress.connect(self.status.emit)
        self._worker.done.connect(self._on_finished)
        self._worker.start()
        self.status.emit("Starting…")

    def _on_finished(self, run) -> None:
        self.setup_screen.set_busy(False)
        if run.error:
            QMessageBox.critical(self, "Calibration", run.error)
            self.status.emit(f"Error: {run.error}")
            return
        self._show(run)
        self.status.emit(f"Calibration complete — {run.grade.headline}")

    def _show(self, run) -> None:
        self._run = run
        from src.van_scan import camera_from_name, van_from_path
        self.report_screen.set_data(run.cal, run.board, run.folder,
                                    van=self.van or van_from_path(run.folder),
                                    camera=camera_from_name(self._role) or self._role, serial=self._serial)
        self.stack.setCurrentWidget(self.report_screen)

    # Used by Load Extrinsic: the lens just calibrated here.
    @property
    def last_run(self):
        return self._run

    @property
    def last_role(self) -> str:
        return self._role

    @property
    def last_serial(self) -> str:
        return self._serial

    def _back_to_setup(self) -> None:
        self.stack.setCurrentWidget(self.setup_screen)
        self.setup_screen.set_busy(False)
        self.status.emit("Ready for a new calibration.")

    # ── Already calibrated? ───────────────────────────────────────────────────
    def _ask_about_previous(self, folder: str) -> bool:
        """True = go ahead and process.  An earlier result can be opened instead."""
        from src.previous_runs import find_previous
        prev = find_previous(folder)
        if not prev:
            return True
        last = prev[0]
        box = QMessageBox(self)
        box.setWindowTitle("Already calibrated")
        box.setIcon(QMessageBox.Icon.Question)
        more = f"\n({len(prev)} earlier results in this folder.)" if len(prev) > 1 else ""
        box.setText(f"This folder was already calibrated:\n{last.text()}{more}")
        box.setInformativeText("Open the saved results, or process the photos again?")
        open_btn = box.addButton("Open results", QMessageBox.ButtonRole.AcceptRole)
        redo_btn = box.addButton("Reprocess", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(open_btn)
        box.exec()
        if box.clickedButton() is redo_btn:
            return True
        if box.clickedButton() is open_btn:
            target = last.pdf_path or last.yaml_path
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            self.status.emit(f"Opened {target.name}")
        return False

    # ── Save ──────────────────────────────────────────────────────────────────
    def _save(self) -> None:
        run = self._run
        if run is None:
            return
        dt = datetime.now()
        try:
            yaml_path, pdf_path = write_outputs(run.cal, run.board, self._serial, run.detections,
                                                run.filter_results, run.folder, dt=dt, role=self._role)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        note = f"YAML:  {yaml_path.name}\nPDF:   {pdf_path.name}\n\nSaved next to the photos:\n{run.folder}"
        note += self._export_fleet_formats(dt)
        QMessageBox.information(self, "Files Saved", note)
        self.status.emit(f"Saved next to the photos: {yaml_path.name}")

    def _export_fleet_formats(self, dt: datetime) -> str:
        """Fleet cameras: also write every format (src/export_formats.py)."""
        from src.van_scan import camera_from_name
        cam = camera_from_name(self._role)
        if not cam or cam == "PAVE":
            return ""
        run = self._run
        # Always write them locally (Derek, 2026-11-03).  The van comes from the van bar, else
        # from the folder path (…ARAN62…), else the user is asked.
        from src.van_scan import van_from_path
        van = self.van or van_from_path(run.folder)
        if not van:
            from PySide6.QtWidgets import QInputDialog
            van, ok = QInputDialog.getText(self, "Van", "Which van is this camera on? (e.g. ARAN65)\n"
                                           "Needed to name the intrinsic_cal.xml and the other files.")
            van = van.strip().upper().replace(" ", "") if ok else ""
        if not van:
            return "\n\nOther formats NOT written: no van given."
        try:
            from src.export_formats import Intrinsics, export_all
            c = Intrinsics.from_result(run.cal, van, cam, self._serial, board=run.board.name,
                                       date=dt, image_folder=run.folder)
            out = Path(run.folder) / f"Calibration_{dt:%Y%m%d_%H%M%S}"
            return f"\n\nAll formats ({len(export_all(c, out))} files) in:\n{out}"
        except Exception as exc:  # noqa: BLE001
            return f"\n\nOther formats FAILED: {exc}"
