"""extrinsic_screen.py — Load Extrinsic, one camera at a time.

Pick ONE camera's Old School folder (…\\Old School\\ForwardLeft) and its lens file.
The lens comes from this session's Load Intrinsic result for the same camera when it
passed, or from a CAL_*.yaml / *_intrinsic_cal.xml file.  Solve finds every target,
works out the camera's angles, height and lever arms, and Save writes every format.
"""

from __future__ import annotations

import os

import cv2
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

_DIM = "color: rgb(140,140,140); font-size: 8pt;"


class _Worker(QThread):
    progress = Signal(str)
    done = Signal(object)            # CameraResult or Exception

    def __init__(self, cs, site, intr, parent=None):
        super().__init__(parent)
        self.cs, self.site, self.intr = cs, site, intr

    def run(self):
        from src.extrinsic.run import run_camera
        try:
            self.done.emit(run_camera(self.cs, self.site, self.intr.K, self.intr.D, progress_cb=self.progress.emit))
        except Exception as exc:  # noqa: BLE001
            self.done.emit(exc)


class ExtrinsicScreen(QWidget):
    status = Signal(str)

    def __init__(self, intrinsic_provider=None, parent=None):
        super().__init__(parent)
        self._provider = intrinsic_provider or (lambda cam: None)
        self._cs = None            # CameraSetups
        self._intr = None          # Intrinsic
        self._res = None           # CameraResult
        self._worker = None
        from src.extrinsic.control import load_site
        self.site = load_site()
        self._build()

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build(self):
        self.folder = QLineEdit(); self.folder.setPlaceholderText("One camera's Old School folder, e.g. …\\Old School\\ForwardLeft")
        fb = QPushButton("Browse…")
        self.camera_lbl = QLabel("—")
        self.lens = QLineEdit(); self.lens.setReadOnly(True); self.lens.setPlaceholderText("Lens: run Load Intrinsic, or pick a file")
        lb = QPushButton("Lens file…")
        self.serial = QLineEdit(); self.serial.setPlaceholderText("Camera serial")
        self.solve_btn = QPushButton("Solve"); self.solve_btn.setObjectName("primary_button")
        self.save_btn = QPushButton("Save all formats")

        box = QGroupBox("Camera")
        f = QFormLayout(box)
        r1 = QHBoxLayout(); r1.addWidget(self.folder, 1); r1.addWidget(fb)
        r2 = QHBoxLayout(); r2.addWidget(self.lens, 1); r2.addWidget(lb)
        f.addRow("Old School folder:", r1)
        f.addRow("Camera:", self.camera_lbl)
        f.addRow("Lens:", r2)
        f.addRow("Serial:", self.serial)
        info = QLabel(f"Control: {self.site.name} tennis-ball survey ({len(self.site.ids)} targets); the revised "
                      "control file is never used.  Old EOP files are never read: the app finds the targets.")
        info.setStyleSheet(_DIM); info.setWordWrap(True)
        f.addRow(info)
        btns = QHBoxLayout(); btns.addStretch(1); btns.addWidget(self.solve_btn); btns.addWidget(self.save_btn)

        self.result = QLabel(""); self.result.setWordWrap(True)
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter); self.result.hide()

        self.setups = QListWidget(); self.setups.setMaximumWidth(300)
        from src.widgets.zoom_view import ZoomView
        self.view = ZoomView(); self.view.setMinimumHeight(320)
        legend = QLabel("<span style='color:#3cc83c'>■ found and used</span> &nbsp; "
                        "<span style='color:#ff5050'>■ found but left out</span> &nbsp; "
                        "<span style='color:#ffb428'>■ should be in view, not found</span> &nbsp; "
                        "Wheel = zoom, drag = move, double-click = whole picture")
        legend.setStyleSheet("font-size: 8pt;")
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(170)
        lower = QSplitter(Qt.Orientation.Horizontal)
        lw = QWidget(); ll = QVBoxLayout(lw); ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Setups")); ll.addWidget(self.setups)
        rw = QWidget(); rl = QVBoxLayout(rw); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(legend); rl.addWidget(self.view, 1); rl.addWidget(self.details)
        lower.addWidget(lw); lower.addWidget(rw); lower.setSizes([280, 900])

        lay = QVBoxLayout(self)
        lay.addWidget(box); lay.addLayout(btns); lay.addWidget(self.result); lay.addWidget(lower, 1)

        fb.clicked.connect(self._browse)
        self.folder.returnPressed.connect(self._load_folder)
        lb.clicked.connect(self._pick_lens)
        self.solve_btn.clicked.connect(self._solve)
        self.save_btn.clicked.connect(self._save)
        self.setups.currentRowChanged.connect(self._show_setup)
        self._buttons()

    # ── folder / lens ────────────────────────────────────────────────────────
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "One camera's Old School folder", self.folder.text())
        if d:
            self.folder.setText(d); self._load_folder()

    def _load_folder(self):
        from src.extrinsic.oldschool import scan_old_school
        root = self.folder.text().strip()
        self._cs, self._res = None, None
        self.result.hide(); self.setups.clear(); self.details.clear()
        if not os.path.isdir(root):
            QMessageBox.warning(self, "Folder", "Pick a folder that exists."); self._buttons(); return
        cams = scan_old_school(root)
        if not cams:
            QMessageBox.warning(self, "Folder", "No Old School setups here (a photo and the van's csv per setup)."); \
                self._buttons(); return
        if len(cams) > 1:
            QMessageBox.warning(self, "One camera", "This folder holds more than one camera: "
                                + ", ".join(c.camera or os.path.basename(c.folder) for c in cams)
                                + ".\nPick the folder of the camera you want.")
            self._buttons(); return
        self._cs = cams[0]
        self.camera_lbl.setText(f"{self._cs.camera or '? (not in the folder name)'}   ·   {len(self._cs.setups)} setups"
                                + (f"   ·   {self._cs.van}" if self._cs.van else ""))
        for s in self._cs.setups:
            self.setups.addItem(f"{s.name}  {'(no van pose)' if s.van is None else ''}")
        got = self._provider(self._cs.camera)
        if got is not None:
            self._set_lens(got)
        self.status.emit(f"{self._cs.camera}: {len(self._cs.setups)} setups.")
        self._buttons()

    def _pick_lens(self):
        p, _ = QFileDialog.getOpenFileName(self, "Lens file", self.folder.text(), "Lens (*.yaml *.yml *.xml)")
        if not p:
            return
        from src.extrinsic.intrinsic_source import from_file
        try:
            self._set_lens(from_file(p))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Lens", str(exc))

    def _set_lens(self, intr):
        self._intr = intr
        self.lens.setText(intr.source)
        if intr.serial and not self.serial.text().strip():
            self.serial.setText(intr.serial)
        self._buttons()

    # ── solve ────────────────────────────────────────────────────────────────
    def _solve(self):
        if self._cs is None or self._intr is None:
            return
        self._worker = _Worker(self._cs, self.site, self._intr, self)
        self._worker.progress.connect(self.status.emit)
        self._worker.done.connect(self._done)
        self._worker.start(); self._buttons(busy=True)

    def _done(self, res):
        self._buttons(busy=False)
        if isinstance(res, Exception):
            QMessageBox.critical(self, "Solve", str(res)); self.status.emit(str(res)); return
        self._res = res
        ok = res.passed
        txt = f"<span style='font-size:16pt; font-weight:bold'>{'PASS' if ok else 'NOT PASSED'}</span>"
        if res.R_bc is not None:
            pan, tilt, roll = res.pan_tilt_roll
            txt += (f"<br>Pan {pan:.2f}°, tilt {tilt:.2f}°, roll {roll:.2f}° (setups agree within "
                    f"{res.angle_spread_deg:.2f}°)  ·  height {res.up_ground_m:.3f} m  ·  forward "
                    f"{res.lever_frd[0]:.2f} m, right {res.lever_frd[1]:.2f} m (rough, GPS)")
        txt += "".join(f"<br>&bull; {r}" for r in res.reasons)
        fg, bg = ("#3cc83c", "#1b3a1f") if ok else ("#ff6b6b", "#4a1c1c")
        self.result.setText(txt)
        self.result.setStyleSheet(f"color: {fg}; background: {bg}; border: 1px solid {fg}; border-radius: 6px; padding: 8px;")
        self.result.show()
        self.setups.clear()
        for sr in res.setups:
            n = sr.solve.n_points if sr.solve else 0
            if sr.passed:
                why = f"{n} targets, {sr.ground_targets} balls" + (" (height)" if sr.counts_for_height else "")
            else:
                main = [p for p in sr.problems if not p.startswith("target ")]
                why = main[0] if main else "not used"
            self.setups.addItem(f"{'✓' if sr.passed else '✗'} {sr.setup.name}  {why}")
        self.details.setPlainText("\n".join([res.headline] + [f"  - {x}" for x in res.reasons]
                                            + [f"  ! {x}" for x in res.warnings]))
        self.status.emit(res.headline)
        self._buttons(busy=False)

    # ── show ─────────────────────────────────────────────────────────────────
    def _show_setup(self, i):
        res = self._res
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
            L.append(f"{sr.solve.n_points} targets ({sr.ground_targets} balls), miss {sr.solve.loo_rms_mm:.1f} mm RMS at "
                     f"{float(sr.solve.range_m.mean()):.1f} m.  Pan {p[0]:.2f}, tilt {p[1]:.2f}, roll {p[2]:.2f} deg.  "
                     f"Forward {sr.solve.lever_frd[0]:.2f}, right {sr.solve.lever_frd[1]:.2f} m (VBS), "
                     f"up {sr.solve.up_ground_m:.3f} m above the pavement.")
        if sr.setup.van:
            v = sr.setup.van
            L.append(f"Van: heading {v.heading:.2f} (true), pitch {v.pitch:.2f}, roll {v.roll:.2f}, GPS {v.gps_status}, "
                     f"moved {v.spread_deg:.2f} deg while parked.")
        L += [f"  - {p}" for p in sr.problems]
        self.details.setPlainText("\n".join(L))

    # ── save ─────────────────────────────────────────────────────────────────
    def _save(self):
        res = self._res
        if res is None or res.R_bc is None:
            return
        serial = self.serial.text().strip()
        if not serial:
            QMessageBox.warning(self, "Save", "Type the camera serial."); return
        from src.extrinsic.outputs import export_camera
        view = "0" if res.camera == "ROW" else ""
        out = export_camera(res, self.site, serial, self._intr.source, camera_view=view, intrinsic=self._intr)
        msg = f"Wrote:\n{out}"
        if not res.passed:
            msg += "\n\nNot passed: files are named NOT_PASSED_."
        QMessageBox.information(self, "Saved", msg)
        self.status.emit(f"Saved: {out}")

    def _buttons(self, busy=None):
        if busy is None:
            busy = bool(self._worker and self._worker.isRunning())
        self.solve_btn.setEnabled(self._cs is not None and self._intr is not None and not busy)
        self.save_btn.setEnabled(self._res is not None and self._res.R_bc is not None and not busy)
