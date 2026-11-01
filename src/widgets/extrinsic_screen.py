"""extrinsic_screen.py — Load Extrinsic: Old School setups -> camera angles and lever arms."""

from __future__ import annotations

import math
import os

import cv2
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

COLS = ["Camera", "Setups", "Serial", "Intrinsic", "Grade", "Pan °", "Tilt °", "Roll °",
        "Spread °", "Forward m", "Right m", "Up m"]
GREEN, AMBER, RED = QColor(60, 140, 70), QColor(170, 120, 30), QColor(160, 50, 50)


def _it(t, edit=False):
    i = QTableWidgetItem(str(t))
    if not edit:
        i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return i


class _Worker(QThread):
    progress = Signal(str)
    done_one = Signal(int, object)
    all_done = Signal()

    def __init__(self, jobs, site, parent=None):
        super().__init__(parent)
        self.jobs, self.site = jobs, site

    def run(self):
        from src.extrinsic.run import run_camera
        for row, cs, intr in self.jobs:
            try:
                res = run_camera(cs, self.site, intr.K, intr.D, progress_cb=self.progress.emit)
            except Exception as exc:  # noqa: BLE001
                res = exc
            self.done_one.emit(row, res)
        self.all_done.emit()


class ExtrinsicScreen(QWidget):
    status = Signal(str)

    def __init__(self, intrinsic_provider=None, parent=None):
        super().__init__(parent)
        self._provider = intrinsic_provider or (lambda cam: None)
        self._cams, self._intr, self._res = [], {}, {}
        self._worker = None
        from src.extrinsic.control import load_site
        self.site = load_site()
        self._build()

    def _build(self):
        self.folder = QLineEdit(); self.folder.setPlaceholderText("The van's Old School folder…")
        b = QPushButton("Browse…"); f = QPushButton("Find cameras")
        top = QHBoxLayout(); top.addWidget(self.folder, 1); top.addWidget(b); top.addWidget(f)
        self.load_btn = QPushButton("Use intrinsic file for selected camera…")
        self.solve_btn = QPushButton("Solve all")
        self.save_btn = QPushButton("Save all formats")
        info = QLabel(f"Control: {self.site.name} tennis-ball survey ({len(self.site.ids)} targets). "
                      "The revised control file is never used.")
        info.setStyleSheet("color: rgb(140,140,140); font-size: 8pt;")
        row2 = QHBoxLayout(); row2.addWidget(info, 1)
        row2.addWidget(self.load_btn); row2.addWidget(self.solve_btn); row2.addWidget(self.save_btn)
        self.table = QTableWidget(0, len(COLS)); self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        for c in range(len(COLS)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.setups = QListWidget(); self.setups.setMaximumWidth(260)
        from src.widgets.zoom_view import ZoomView
        self.view = ZoomView(); self.view.setMinimumHeight(320)
        self.legend = QLabel("<span style='color:#3cc83c'>■ found and used</span> &nbsp; "
                             "<span style='color:#ff5050'>■ found but left out</span> &nbsp; "
                             "<span style='color:#ffb428'>■ should be in view, not found</span> &nbsp; "
                             "Wheel = zoom, drag = move, double-click = whole picture")
        self.legend.setStyleSheet("font-size: 8pt;")
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(170)
        lower = QSplitter(Qt.Orientation.Horizontal)
        lw = QWidget(); ll = QVBoxLayout(lw); ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Setups")); ll.addWidget(self.setups)
        rw = QWidget(); rl = QVBoxLayout(rw); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.legend); rl.addWidget(self.view, 1); rl.addWidget(self.details)
        lower.addWidget(lw); lower.addWidget(rw); lower.setSizes([240, 900])
        split = QSplitter(Qt.Orientation.Vertical); split.addWidget(self.table); split.addWidget(lower)
        split.setSizes([200, 520])
        lay = QVBoxLayout(self); lay.addLayout(top); lay.addLayout(row2); lay.addWidget(split, 1)
        b.clicked.connect(self._browse); f.clicked.connect(self._scan); self.folder.returnPressed.connect(self._scan)
        self.load_btn.clicked.connect(self._load_intrinsic); self.solve_btn.clicked.connect(self._solve)
        self.save_btn.clicked.connect(self._save)
        self.table.itemSelectionChanged.connect(self._show_camera)
        self.setups.currentRowChanged.connect(self._show_setup)
        self._buttons()

    # ── scan / intrinsic ─────────────────────────────────────────────────────
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Old School folder", self.folder.text())
        if d:
            self.folder.setText(d); self._scan()

    def _scan(self):
        from src.extrinsic.oldschool import scan_old_school
        root = self.folder.text().strip()
        if not os.path.isdir(root):
            QMessageBox.warning(self, "Folder", "Pick a folder that exists."); return
        self._cams = scan_old_school(root); self._intr = {}; self._res = {}
        self.table.setRowCount(0)
        for r, cs in enumerate(self._cams):
            self.table.insertRow(r)
            intr = self._provider(cs.camera)
            if intr is not None:
                self._intr[r] = intr
            vals = [cs.camera or "?", len(cs.setups), intr.serial if intr else "",
                    intr.source if intr else "none: run Load Intrinsic, or pick a file", "", "", "", "", "", "", "", ""]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, _it(v, edit=(c == 2)))
        self.status.emit(f"Found {len(self._cams)} camera(s) with {sum(len(c.setups) for c in self._cams)} setups.")
        self._buttons()

    def _row(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return rows[0] if rows else None

    def _load_intrinsic(self):
        r = self._row()
        if r is None:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Intrinsic for " + self._cams[r].camera, self.folder.text(),
                                           "Intrinsic (*.yaml *.yml *.xml)")
        if not p:
            return
        from src.extrinsic.intrinsic_source import from_file
        try:
            intr = from_file(p)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Intrinsic", str(exc)); return
        self._intr[r] = intr
        self.table.setItem(r, 2, _it(intr.serial, edit=True)); self.table.setItem(r, 3, _it(intr.source))
        self._buttons()

    # ── solve ────────────────────────────────────────────────────────────────
    def _solve(self):
        jobs = [(r, cs, self._intr[r]) for r, cs in enumerate(self._cams) if r in self._intr]
        if not jobs:
            QMessageBox.information(self, "Solve", "No camera has an intrinsic yet."); return
        self._worker = _Worker(jobs, self.site, self)
        self._worker.progress.connect(self.status.emit)
        self._worker.done_one.connect(self._done_one)
        self._worker.all_done.connect(lambda: (self._buttons(), self.status.emit("Solved.")))
        self._worker.start(); self._buttons(busy=True)

    def _done_one(self, r, res):
        if isinstance(res, Exception):
            g = _it("ERROR"); g.setBackground(RED); self.table.setItem(r, 4, g)
            self.status.emit(str(res)); return
        self._res[r] = res
        g = _it("PASS" if res.passed else ("FAIL" if res.R_bc is None else "NOT GOOD ENOUGH"))
        g.setBackground(GREEN if res.passed else (RED if res.R_bc is None else AMBER))
        self.table.setItem(r, 4, g)
        if res.R_bc is not None:
            pan, tilt, roll = res.pan_tilt_roll
            vals = [f"{pan:.2f}", f"{tilt:.2f}", f"{roll:.2f}", f"{res.angle_spread_deg:.2f}",
                    f"{res.lever_frd[0]:.2f} (rough)", f"{res.lever_frd[1]:.2f} (rough)", f"{res.up_ground_m:.3f}"]
            for c, v in zip(range(5, 12), vals):
                self.table.setItem(r, c, _it(v))
        if r == self._row():
            self._show_camera()

    # ── show ─────────────────────────────────────────────────────────────────
    def _show_camera(self):
        self._buttons()
        r = self._row()
        self.setups.clear()
        if r is None:
            return
        res = self._res.get(r)
        cs = self._cams[r]
        if res is None:
            for s in cs.setups:
                self.setups.addItem(f"{s.name}  {'(no van pose)' if s.van is None else ''}")
            self.details.setPlainText(f"{cs.folder}\n{len(cs.setups)} setups.  Not solved yet.")
            return
        for sr in res.setups:
            n = sr.solve.n_points if sr.solve else 0
            if sr.passed:
                why = f"{n} targets"
            else:
                main = [p for p in sr.problems if not p.startswith("target ")]
                why = main[0] if main else "not used"
            self.setups.addItem(f"{'✓' if sr.passed else '✗'} {sr.setup.name}  {why}")
        lines = [res.headline] + [f"  - {x}" for x in res.reasons] + [f"  ! {x}" for x in res.warnings]
        self.details.setPlainText("\n".join(lines))

    def _show_setup(self, i):
        r = self._row(); res = self._res.get(r) if r is not None else None
        if res is None or i < 0 or i >= len(res.setups):
            return
        sr = res.setups[i]
        from src.extrinsic.outputs import overlay
        img = overlay(sr, self.site, res.K, res.D)
        if img is None and sr.setup.photo:
            img = cv2.imread(sr.setup.photo)
        self.view.set_bgr(img)
        L = [f"{sr.setup.name}   seed: {sr.seed or '-'}   photo: {sr.setup.photo}"]
        if sr.solve:
            from src.extrinsic.solve import pointing
            p = pointing(sr.solve.R_bc)
            L.append(f"{sr.solve.n_points} targets, miss {sr.solve.loo_rms_mm:.1f} mm RMS at "
                     f"{float(sr.solve.range_m.mean()):.1f} m.  Pan {p[0]:.2f}, tilt {p[1]:.2f}, roll {p[2]:.2f} deg.  "
                     f"Forward {sr.solve.lever_frd[0]:.2f}, right {sr.solve.lever_frd[1]:.2f} m (VBS), "
                     f"up {sr.solve.up_ground_m:.3f} m above the pavement.")
        if sr.setup.van:
            v = sr.setup.van
            L.append(f"Van: heading {v.heading:.2f} (true), pitch {v.pitch:.2f}, roll {v.roll:.2f}, GPS {v.gps_status}, "
                     f"moved {v.spread_deg:.2f} deg while parked.")
        L += [f"  - {p}" for p in sr.problems] + [f"  ? target {p}: {t}" for p, t in sr.label_checks]
        self.details.setPlainText("\n".join(L))

    # ── save ─────────────────────────────────────────────────────────────────
    def _save(self):
        if not self._res:
            return
        from src.extrinsic.outputs import export_camera
        outs, failed = [], []
        for r, res in self._res.items():
            if res.R_bc is None:
                continue
            serial = self.table.item(r, 2).text().strip() if self.table.item(r, 2) else ""
            if not serial:
                QMessageBox.warning(self, "Save", f"Type the serial for {res.camera}."); return
            if not res.passed:
                failed.append(res.camera)
            view = "0" if res.camera == "ROW" else ""
            outs.append(str(export_camera(res, self.site, serial, self._intr[r].source, camera_view=view,
                                           intrinsic=self._intr[r])))
        msg = "Wrote:\n" + "\n".join(outs)
        if failed:
            msg += "\n\nNot passed (files named NOT_PASSED_): " + ", ".join(failed)
        QMessageBox.information(self, "Saved", msg)

    def _buttons(self, busy=None):
        if busy is None:
            busy = bool(self._worker and self._worker.isRunning())
        self.solve_btn.setEnabled(bool(self._intr) and not busy)
        self.save_btn.setEnabled(bool(self._res) and not busy)
        self.load_btn.setEnabled(self._row() is not None and not busy)
