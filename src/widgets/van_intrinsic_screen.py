"""van_intrinsic_screen.py — Load Intrinsic > Whole van.

Pick a van's Intrinsic folder (or any folder above it).  Every camera folder is
found, named and given its serial (src/van_scan.py), then graded one after the
other (VanIntrinsicWorker).  One row per camera: grade, error at 10 m, change
from the filed calibration, and what to shoot next.

A row that does not pass can still be exported (files get a NOT_PASSED_
prefix), the same rule as the single-camera Save: warn, save locally, block
publishing.  Unusable photos always go to NotUsed (src/pipeline.py).
"""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.van_scan import CAMERAS, scan

COLS = ["Camera", "Serial", "Van", "Photos", "Board", "RMS px", "Blur px",
        "Error @10 m", "vs filed @10 m", "Grade", "What to do", "Folder"]
C_CAM, C_SER, C_VAN, C_PH, C_BRD, C_RMS, C_BLUR, C_ERR, C_FILED, C_GRADE, C_TODO, C_DIR = range(len(COLS))

GREEN = QColor(60, 140, 70)
AMBER = QColor(170, 120, 30)     # blur warning only
RED = QColor(160, 50, 50)


def _item(text, editable=False):
    it = QTableWidgetItem(str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return it


class VanIntrinsicScreen(QWidget):
    open_requested = Signal(object, str, str)   # FolderRun, role, serial
    van_changed = Signal(str)
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._found = []          # CameraFolder per row
        self._runs = {}           # row -> FolderRun
        self._worker = None
        self._build()

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Van Intrinsic folder (or any folder above it)…")
        self.browse_btn = QPushButton("Browse…")
        self.scan_btn = QPushButton("Find cameras")
        top = QHBoxLayout()
        top.addWidget(self.folder_edit, 1); top.addWidget(self.browse_btn); top.addWidget(self.scan_btn)

        self.max_spin = QSpinBox(); self.max_spin.setRange(0, 2000); self.max_spin.setValue(0)
        self.max_spin.setSpecialValueText("all"); self.max_spin.setSuffix(" photos")
        self.max_spin.setToolTip("Use at most this many photos per camera, evenly spaced. "
                                 "'all' is the real result; fewer is only for a quick look.")
        self.grade_all_btn = QPushButton("Grade all")
        self.grade_sel_btn = QPushButton("Grade selected")
        self.stop_btn = QPushButton("Stop"); self.stop_btn.setEnabled(False)
        run = QHBoxLayout()
        run.addWidget(QLabel("Use")); run.addWidget(self.max_spin); run.addWidget(QLabel("per camera"))
        run.addSpacing(20); run.addWidget(QLabel("Unusable photos go to NotUsed"))
        run.addStretch(1)
        run.addWidget(self.grade_all_btn); run.addWidget(self.grade_sel_btn); run.addWidget(self.stop_btn)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        for c in range(len(COLS)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(C_TODO, QHeaderView.ResizeMode.Stretch)

        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setPlaceholderText("Pick a row to see the full grade and what to shoot next.")

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table); split.addWidget(self.details)
        split.setSizes([380, 200])

        self.open_btn = QPushButton("Open full report (3x3 grid, photos)")
        self.export_btn = QPushButton("Export all formats")
        self.export_btn.setToolTip("Fleet XML, PG RWC, OpenCV, ROS, Kalibr, COLMAP, "
                                   "Metashape, JSON, CSV.  Saved in a Calibration_<date> "
                                   "folder next to each camera's photos.")
        self.hint = QLabel("Camera and serial come from folder and file names; "
                           "double-click a cell to fix them before grading.")
        self.hint.setStyleSheet("color: rgb(140,140,140); font-size: 8pt;")
        bottom = QHBoxLayout()
        bottom.addWidget(self.hint, 1); bottom.addWidget(self.open_btn); bottom.addWidget(self.export_btn)

        lay = QVBoxLayout(self)
        lay.addLayout(top); lay.addLayout(run); lay.addWidget(split, 1); lay.addLayout(bottom)

        self.browse_btn.clicked.connect(self._browse)
        self.scan_btn.clicked.connect(self._scan)
        self.folder_edit.returnPressed.connect(self._scan)
        self.grade_all_btn.clicked.connect(lambda: self._grade(all_rows=True))
        self.grade_sel_btn.clicked.connect(lambda: self._grade(all_rows=False))
        self.stop_btn.clicked.connect(self._stop)
        self.table.itemSelectionChanged.connect(self._show_details)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.open_btn.clicked.connect(self._open)
        self.export_btn.clicked.connect(self._export)
        self._update_buttons()

    # ── Scan ─────────────────────────────────────────────────────────────────
    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Van Intrinsic folder", self.folder_edit.text())
        if d:
            self.folder_edit.setText(d); self._scan()

    def _scan(self) -> None:
        root = self.folder_edit.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.warning(self, "Folder", "Pick a folder that exists."); return
        self._found = scan(root)
        self._runs = {}
        self.table.setRowCount(0)
        for cf in self._found:
            r = self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r, C_CAM, _item(cf.camera or "?", editable=True))
            self.table.setItem(r, C_SER, _item(cf.serial, editable=True))
            self.table.setItem(r, C_VAN, _item(cf.van, editable=True))
            self.table.setItem(r, C_PH, _item(cf.images))
            for c in (C_BRD, C_RMS, C_BLUR, C_ERR, C_FILED, C_GRADE):
                self.table.setItem(r, c, _item(""))
            self.table.setItem(r, C_TODO, _item("; ".join(cf.notes) or "not graded yet"))
            self.table.setItem(r, C_DIR, _item(os.path.relpath(cf.folder, root)))
        vans = sorted({cf.van for cf in self._found if cf.van})
        if len(vans) == 1:
            self.van_changed.emit(vans[0])
        self.status.emit(f"Found {len(self._found)} camera folder(s)"
                         + (f" for {', '.join(vans)}" if vans else ""))
        self._update_buttons()

    def _cell(self, r, c) -> str:
        it = self.table.item(r, c)
        return it.text().strip() if it else ""

    # ── Grade ────────────────────────────────────────────────────────────────
    def _grade(self, all_rows: bool) -> None:
        rows = (range(self.table.rowCount()) if all_rows
                else sorted({i.row() for i in self.table.selectedIndexes()}))
        jobs = [(r, self._found[r].folder, self._found[r].filed_xml) for r in rows]
        if not jobs:
            return
        from src.workers import VanIntrinsicWorker
        self._worker = VanIntrinsicWorker(jobs, self.max_spin.value(), parent=self)
        self._worker.row_started.connect(lambda r, t: self._set_grade_cell(r, "working…", None))
        self._worker.row_progress.connect(lambda r, t: self._set_grade_cell(r, t + "…", None))
        self._worker.row_finished.connect(self._row_done)
        self._worker.all_done.connect(self._all_done)
        self._worker.start()
        self._update_buttons(busy=True)
        self.status.emit(f"Grading {len(jobs)} camera(s)… this can take a few minutes each.")

    def _stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self.status.emit("Stopping after the current camera…")

    def _set_grade_cell(self, r, text, colour) -> None:
        it = _item(text)
        if colour is not None:
            it.setBackground(colour)
        self.table.setItem(r, C_GRADE, it)

    def _row_done(self, r: int, run) -> None:
        self._runs[r] = run
        if run.error:
            self._set_grade_cell(r, "ERROR", RED)
            self.table.setItem(r, C_TODO, _item(run.error))
            return
        g = run.grade
        self.table.setItem(r, C_BRD, _item(run.board.name))
        self.table.setItem(r, C_RMS, _item(f"{run.cal.rms:.2f}"))
        bl = g.blur_median_px
        bi = _item("—" if bl != bl else f"{bl:.1f}")
        from src.grading import BLUR_MAX_PX, BLUR_SOFT_PX
        if bl == bl and bl > BLUR_MAX_PX:
            bi.setBackground(RED)
        elif bl == bl and bl > BLUR_SOFT_PX:
            bi.setBackground(AMBER)
        self.table.setItem(r, C_BLUR, bi)
        rp = g.repeatability
        self.table.setItem(r, C_ERR, _item("—" if rp is None else f"{rp.at_10m_mm:.0f} mm"))
        self.table.setItem(r, C_FILED, _item("—" if run.vs_filed_10m_mm is None
                                             else f"{run.vs_filed_10m_mm:.0f} mm"))
        self._set_grade_cell(r, "PASS" if g.passed else "NOT PASSED", GREEN if g.passed else RED)
        todo = g.coaching[0] if g.coaching else ("—" if g.passed else g.headline)
        if run.move_note:
            todo = f"{todo}   [{run.move_note}]"
        self.table.setItem(r, C_TODO, _item(todo))
        if r in {i.row() for i in self.table.selectedIndexes()}:
            self._show_details()

    def _all_done(self) -> None:
        self._update_buttons(busy=False)
        done = [r for r in self._runs.values() if not r.error and r.grade]
        n_pass = sum(r.grade.passed for r in done)
        self.status.emit(f"Done: {n_pass} of {len(done)} graded camera(s) passed.")

    # ── Details / open / export ──────────────────────────────────────────────
    def _selected_row(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return rows[0] if rows else None

    def _show_details(self) -> None:
        r = self._selected_row()
        self._update_buttons()
        if r is None:
            return
        cf = self._found[r]
        lines = [f"{self._cell(r, C_VAN)}  {self._cell(r, C_CAM)}  serial {self._cell(r, C_SER)}",
                 cf.folder, f"{cf.images} photos"]
        if cf.filed_xml:
            lines.append(f"Filed calibration: {os.path.basename(cf.filed_xml)}")
        run = self._runs.get(r)
        if run is None:
            lines.append("\nNot graded yet.")
        elif run.error:
            lines.append(f"\nERROR: {run.error}")
        else:
            K = run.cal.camera_matrix
            lines += ["", run.grade.as_text(), "",
                      f"fx {K[0,0]:.2f}  fy {K[1,1]:.2f}  cx {K[0,2]:.2f}  cy {K[1,2]:.2f}",
                      "dist " + "  ".join(f"{v:.6f}" for v in run.cal.dist_coeffs.ravel()),
                      f"{run.cal.image_count_used} photos used, {run.cal.point_count_used} points"]
            if run.move_note:
                lines.append("")
                lines.append(run.move_note + (":" if run.moved else ""))
                lines += [f"  {n}  — {why}" for n, why in run.moved]
            if run.vs_filed_10m_mm is not None:
                lines.append(f"Differs from the filed calibration by {run.vs_filed_10m_mm:.0f} mm "
                             "at 10 m (95% of the image).")
        self.details.setPlainText("\n".join(lines))

    def _on_double_click(self, r, c) -> None:
        if c in (C_CAM, C_SER, C_VAN):
            return  # editing
        if r in self._runs and not self._runs[r].error:
            self._open()

    def _open(self) -> None:
        r = self._selected_row()
        run = self._runs.get(r) if r is not None else None
        if run is None or run.error:
            return
        self.open_requested.emit(run, self._cell(r, C_CAM), self._cell(r, C_SER))

    def _export(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or list(self._runs)
        rows = [r for r in rows if r in self._runs and not self._runs[r].error]
        if not rows:
            QMessageBox.information(self, "Export", "Grade the cameras first."); return
        missing = [self._cell(r, C_CAM) for r in rows if not self._cell(r, C_SER) or not self._cell(r, C_VAN)
                   or self._cell(r, C_CAM) not in CAMERAS]
        if missing:
            QMessageBox.warning(self, "Export", "Fill in camera, serial and van for: "
                                + ", ".join(missing)); return
        failed = [self._cell(r, C_CAM) for r in rows if not self._runs[r].grade.passed]
        if failed and QMessageBox.question(
                self, "Not passed",
                "These did not pass: " + ", ".join(failed) + ".\n\nTheir files will be saved "
                "with a NOT_PASSED_ prefix and must not be used.  Continue?") \
                != QMessageBox.StandardButton.Yes:
            return
        from src.export_formats import Intrinsics, export_all
        dt = datetime.now()
        out_dirs = []
        for r in rows:
            run = self._runs[r]
            c = Intrinsics.from_result(run.cal, self._cell(r, C_VAN), self._cell(r, C_CAM),
                                       self._cell(r, C_SER), board=run.board.name, date=dt,
                                       image_folder=run.folder)
            out = os.path.join(run.folder, f"Calibration_{dt:%Y%m%d_%H%M%S}")
            export_all(c, out)
            out_dirs.append(out)
        QMessageBox.information(self, "Exported", "Wrote every format to:\n\n" + "\n".join(out_dirs))
        self.status.emit(f"Exported {len(out_dirs)} camera(s).")

    # ── Used by the main window ──────────────────────────────────────────────
    def graded(self) -> list[tuple[str, str, object]]:
        """(camera, serial, FolderRun) for every row graded without an error."""
        return [(self._cell(r, C_CAM), self._cell(r, C_SER), run)
                for r, run in sorted(self._runs.items()) if not run.error]

    def summary_text(self) -> str:
        parts = [f"{self._cell(r, C_CAM)} "
                 f"{'ERROR' if run.error else ('PASS' if run.passed else 'NOT PASSED')}"
                 for r, run in sorted(self._runs.items())]
        return "Intrinsic: " + (",  ".join(parts) if parts else "not graded")

    def _update_buttons(self, busy: bool | None = None) -> None:
        if busy is None:
            busy = bool(self._worker and self._worker.isRunning())
        has_rows = self.table.rowCount() > 0
        r = self._selected_row()
        graded = r is not None and r in self._runs and not self._runs[r].error
        self.grade_all_btn.setEnabled(has_rows and not busy)
        self.grade_sel_btn.setEnabled(r is not None and not busy)
        self.stop_btn.setEnabled(busy)
        self.scan_btn.setEnabled(not busy)
        self.open_btn.setEnabled(graded and not busy)
        self.export_btn.setEnabled(bool(self._runs) and not busy)
