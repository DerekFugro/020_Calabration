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
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from src.output_writer import write_outputs
from src.widgets.report_screen import ReportScreen
from src.widgets.setup_screen import SetupScreen


class OneCameraScreen(QWidget):
    status = Signal(str)

    def __init__(self, bar, parent=None) -> None:
        super().__init__(parent)
        self.bar = bar                 # van, camera, serial (shared bar on top)
        self._run = None               # FolderRun on show
        self._role = self._serial = ""
        self._worker = None

        self.setup_screen = SetupScreen(bar)
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
        self.report_screen.check_requested.connect(self._check)

        # Buttons in the top bar row, like Load Extrinsic (Derek, 2026-11-11); each shows only when it applies.
        self._report_pdf = None
        self.report_btn = QPushButton("Open report")
        self.report_btn.setToolTip("The PDF of the result on screen (after Save, or an earlier saved result)")
        self.report_btn.clicked.connect(self._open_report)
        r, s = self.report_screen, self.setup_screen
        self.actions = QWidget()
        al = QHBoxLayout(self.actions); al.setContentsMargins(0, 0, 0, 0)
        for b in (r.new_cal_button, r.view_button, r.check_button, s.run_button, r.save_button, self.report_btn):
            al.addWidget(b)
        self.stack.currentChanged.connect(lambda _i: self._sync_buttons())
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        """Which bar buttons apply: the report on screen, an earlier result opened, a PDF to open."""
        on_report = self.stack.currentWidget() is self.report_screen
        r = self.report_screen
        r.new_cal_button.setVisible(on_report)
        r.view_button.setVisible(on_report)
        r.save_button.setVisible(on_report)
        self.setup_screen.run_button.setVisible(not on_report)   # with a report: New Calibration / Check by re-running
        if not on_report:
            r.check_button.hide()
        self.report_btn.setEnabled(bool(self._report_pdf) and Path(self._report_pdf).exists())

    def _open_report(self) -> None:
        if self._report_pdf and Path(self._report_pdf).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._report_pdf)))
            self.status.emit(f"Opened {Path(self._report_pdf).name}")

    # ── Run ───────────────────────────────────────────────────────────────────
    def _on_run_requested(self, folder: str, serial: str, board) -> None:
        if not self._ask_about_previous(folder):
            return
        self._role, self._serial = self.setup_screen.camera_role, serial
        self.setup_screen.set_busy(True)
        from src.van_scan import camera_from_name, van_from_computer, van_from_path
        if self.van:
            van, van_from = self.van, ("computer name" if self.van == van_from_computer() else "typed in the van box")
        else:
            van = van_from_path(folder)
            van_from = "folder path" if van else "not known"
        db = self.bar.db_res
        inputs = {"van": van, "van_from": van_from,
                  "camera": camera_from_name(self._role) or self._role, "camera_from": "picked in the top bar",
                  "serial": serial, "serial_from": self.bar.serial_from,
                  "van_database": None if db is None else
                  {"where": db.where if not db.error else "", "error": db.error,
                   "cameras": {c.camera: c.serial for c in db.cameras.values()}},
                  "board_picked": getattr(board, "name", None) or "auto-detect"}
        from src.workers import FolderWorker
        self._worker = FolderWorker(folder, board, parent=self, inputs=inputs)
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
        loaded = getattr(run, "loaded_from", "")
        pdf = Path(loaded).with_suffix(".pdf") if loaded else None
        self._report_pdf = pdf if pdf is not None and pdf.exists() else None
        from src.van_scan import camera_from_name, van_from_path
        self.report_screen.set_loaded(getattr(run, "loaded_note", ""))
        self.report_screen.set_data(run.cal, run.board, run.folder,
                                    van=self.van or van_from_path(run.folder),
                                    camera=camera_from_name(self._role) or self._role, serial=self._serial)
        self.stack.setCurrentWidget(self.report_screen)
        self._sync_buttons()

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
        pdf_btn = box.addButton("Open PDF", QMessageBox.ButtonRole.ActionRole)
        redo_btn = box.addButton("Reprocess", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(open_btn)
        box.exec()
        if box.clickedButton() is redo_btn:
            return True
        if box.clickedButton() is open_btn:
            self._load_previous(last.yaml_path)
            return False
        if box.clickedButton() is pdf_btn:
            target = last.pdf_path or last.yaml_path
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            self.status.emit(f"Opened {target.name}")
        return False

    @property
    def van(self) -> str:
        return self.bar.van

    def new_camera(self) -> None:
        """The camera changed in the top bar: start over (no folder, no result from the last camera)."""
        if self._worker is not None and self._worker.isRunning():
            return                         # the bar is locked while a calibration runs
        self._run = None
        self._role = self._serial = ""
        self._report_pdf = None
        self.setup_screen.clear_folder()
        self.stack.setCurrentWidget(self.setup_screen)
        self.setup_screen.set_busy(False)

    # ── Loaded results: check each other's work ────────────────────────────
    def _load_previous(self, yaml_path) -> None:
        """Show a saved calibration in the report, as if it had just been processed."""
        from src.load_saved import load_saved
        try:
            run = load_saved(yaml_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Open results", f"Could not load {Path(yaml_path).name}:\n{exc}")
            return
        self._role, self._serial = run.saved_role, run.saved_serial
        self._show(run)
        self.status.emit(f"Loaded {Path(yaml_path).name} - Check by re-running compares it with today's app.")

    def _check(self) -> None:
        run = self._run
        if run is None or not getattr(run, "loaded_from", ""):
            return
        from src.workers import FolderWorker
        self.report_screen.check_button.setEnabled(False)
        self._check_worker = FolderWorker(run.folder, run.board, parent=self, change_folder=False)
        self._check_worker.progress.connect(lambda m: self.status.emit(f"Check: {m}"))
        self._check_worker.done.connect(self._check_done)
        self._check_worker.start()
        self.status.emit("Checking: processing the photos again (nothing in the folder changes)...")

    def _check_done(self, new_run) -> None:
        from src.load_saved import compare, record_check
        self.report_screen.check_button.setEnabled(True)
        agrees, text = compare(self._run, new_run)
        if getattr(self._run, "run_log", ""):
            try:
                record_check(self._run.run_log, agrees, text)
                text += f"\n\nRecorded in {Path(self._run.run_log).name}."
            except Exception:  # noqa: BLE001
                pass
        (QMessageBox.information if agrees else QMessageBox.warning)(self, "Check by re-running", text)
        self.status.emit(text.splitlines()[0])

    # ── Save ──────────────────────────────────────────────────────────────────
    def _save(self) -> None:
        run = self._run
        if run is None:
            return
        dt = datetime.now()
        from src.superseded import intrinsic_results, move_to_superseded
        earlier = intrinsic_results(run.folder)       # moved to Superseded once the new result is written
        try:
            yaml_path, pdf_path = write_outputs(run.cal, run.board, self._serial, run.detections,
                                                run.filter_results, run.folder, dt=dt, role=self._role,
                                                run_id=getattr(run, "run_id", ""))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        note = (f"YAML:  {yaml_path.name}\nPDF:   {pdf_path.name}\nDots:  <photo>.dots.json beside each photo "
                f"(written by every run)\n\nSaved next to the photos:\n{run.folder}")
        self._export_dir = ""
        note += self._export_fleet_formats(dt)
        moved = move_to_superseded(earlier, run.folder)
        if moved:
            note += f"\n\n{len(moved)} earlier result file(s)/folder(s) moved to {Path(run.folder).name}\\Superseded."
        if getattr(run, "run_log", ""):
            try:
                from src.run_log import record_save
                from src.van_scan import camera_from_name, van_from_path
                record_save(run.run_log, cal_yaml=yaml_path.name, cal_pdf=pdf_path.name,
                            formats_folder=self._export_dir or None,
                            van=self.van or van_from_path(run.folder),
                            camera=camera_from_name(self._role) or self._role, serial=self._serial)
                note += f"\nRun log: {Path(run.run_log).name}"
            except Exception:  # noqa: BLE001 - the save itself already worked
                pass
        self._report_pdf = pdf_path
        self._sync_buttons()
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
            n = len(export_all(c, out))
            self._export_dir = out.name
            return f"\n\nAll formats ({n} files) in:\n{out}"
        except Exception as exc:  # noqa: BLE001
            return f"\n\nOther formats FAILED: {exc}"
