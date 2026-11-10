"""extrinsic_screen.py — Load Extrinsic, one camera at a time.

Pick ONE camera's Old School folder (…\\Old School\\ForwardLeft) and its lens file.
The lens comes from this session's Load Intrinsic result for the same camera when it
passed, or from a CAL_*.yaml / *_intrinsic_cal.xml file.  Solve finds every target,
works out the camera's angles, height and lever arms, and Save writes every format.

Camera and serial come from the lens (Derek, 2026-11-10), read only.  The Old School
folder name and the van database check them before the solve (lens check), and where
the camera points checks them after it.  Warnings only, never a stop.
"""

from __future__ import annotations

import html
import os
from dataclasses import replace

import cv2
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

_DIM = "color: rgb(140,140,140); font-size: 8pt;"


class _Worker(QThread):
    progress = Signal(str)
    done = Signal(object)            # CameraResult or Exception

    def __init__(self, cs, site, intr, parent=None):
        super().__init__(parent)
        self.cs, self.site, self.intr = cs, site, intr

    def run(self):
        from datetime import datetime
        from src.extrinsic.run import run_camera
        try:
            res = run_camera(self.cs, self.site, self.intr.K, self.intr.D, progress_cb=self.progress.emit)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(exc); return
        # Every Solve leaves <photo>.targets.json beside each Old School photo, saved or not
        # (src/extrinsic/target_files.py).  Logging never costs the solve.
        res.run_id = f"SOLVE_{datetime.now():%Y%m%d_%H%M%S}"
        try:
            from src.extrinsic.target_files import write_target_files
            write_target_files(res, self.site, run_id=res.run_id)
        except Exception:  # noqa: BLE001
            pass
        self.done.emit(res)


class ExtrinsicScreen(QWidget):
    status = Signal(str)

    def __init__(self, intrinsic_provider=None, parent=None):
        super().__init__(parent)
        self._provider = intrinsic_provider or (lambda cam: None)
        self._cs = None            # CameraSetups
        self._folder_cam = ""      # camera in the Old School folder name
        self._intr = None          # Intrinsic
        self._db = None            # camera_db.DbResult for the van (checks the lens serial)
        self._db_worker = None
        self.van = ""              # from the van bar
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
        self.serial = QLineEdit(); self.serial.setReadOnly(True)
        self.serial.setPlaceholderText("From the lens")
        self.solve_btn = QPushButton("Solve"); self.solve_btn.setObjectName("primary_button")
        self.save_btn = QPushButton("Save all formats")
        # Pop-up photo check (src/viewer): each setup's targets from its .targets.json
        self.view_btn = QPushButton("View photos...")
        self.view_btn.clicked.connect(self._open_viewer)

        box = QGroupBox("Camera")
        f = QFormLayout(box)
        r1 = QHBoxLayout(); r1.addWidget(self.folder, 1); r1.addWidget(fb)
        r2 = QHBoxLayout(); r2.addWidget(self.lens, 1); r2.addWidget(lb)
        f.addRow("Old School folder:", r1)
        f.addRow("Camera:", self.camera_lbl)
        f.addRow("Lens:", r2)
        f.addRow("Serial:", self.serial)
        # Is this the right lens file?  Plain words and dates, never a stop.
        self.lens_info = QLabel(""); self.lens_info.setWordWrap(True)
        self.lens_info.setTextFormat(Qt.TextFormat.RichText); self.lens_info.hide()
        self.lens_info.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        f.addRow("Lens check:", self.lens_info)
        info = QLabel(f"Control: {self.site.name} tennis-ball survey ({len(self.site.ids)} targets); the revised "
                      "control file is never used.  Old EOP files are never read: the app finds the targets.")
        info.setStyleSheet(_DIM); info.setWordWrap(True)
        f.addRow(info)
        btns = QHBoxLayout(); btns.addStretch(1); btns.addWidget(self.view_btn); btns.addWidget(self.solve_btn); btns.addWidget(self.save_btn)

        self.result = QLabel(""); self.result.setWordWrap(True)
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter); self.result.hide()

        self.setups = QListWidget(); self.setups.setMaximumWidth(300)
        from src.widgets.zoom_view import ZoomView
        self.view = ZoomView(); self.view.setMinimumHeight(160)
        legend = QLabel("<span style='color:#3cc83c'>■ found and used</span> &nbsp; "
                        "<span style='color:#ff5050'>■ found but left out</span> &nbsp; "
                        "<span style='color:#ffb428'>■ should be in view, not found</span> &nbsp; "
                        "Wheel = zoom, drag = move, double-click = whole picture")
        legend.setStyleSheet("font-size: 8pt;")
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(170)
        self.details.setMinimumHeight(48)
        lower = QSplitter(Qt.Orientation.Horizontal)
        lw = QWidget(); ll = QVBoxLayout(lw); ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Setups")); ll.addWidget(self.setups)
        rw = QWidget(); rl = QVBoxLayout(rw); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(legend); rl.addWidget(self.view, 1); rl.addWidget(self.details)
        lower.addWidget(lw); lower.addWidget(rw); lower.setSizes([280, 900])

        # The top part scrolls inside a splitter, so a long lens check can never make the
        # window taller than the screen.  Drag the splitter bar to give either part more room.
        # (Window-height fix from another session, 2026-11-05.)  The Solve / Save buttons sit
        # under the scrolling part, so they are always in view, and the top grows to show the
        # whole lens check when it can (_fit_top).
        self._top = top = QWidget(); tl = QVBoxLayout(top); tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(box); tl.addWidget(self.result); tl.addStretch(1)
        top_scroll = QScrollArea(); top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QFrame.Shape.NoFrame); top_scroll.setWidget(top)
        top_scroll.setMinimumHeight(120)
        upper = QWidget(); ul = QVBoxLayout(upper); ul.setContentsMargins(0, 0, 0, 0)
        ul.addWidget(top_scroll, 1); ul.addLayout(btns)
        self._split = split = QSplitter(Qt.Orientation.Vertical); split.setChildrenCollapsible(False)
        split.addWidget(upper); split.addWidget(lower)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setSizes([380, 470])
        lay = QVBoxLayout(self)
        lay.addWidget(split, 1)

        fb.clicked.connect(self._browse)
        self.folder.returnPressed.connect(self._load_folder)
        lb.clicked.connect(self._pick_lens)
        self.solve_btn.clicked.connect(self._solve)
        self.save_btn.clicked.connect(self._save)
        self.setups.currentRowChanged.connect(self._show_setup)
        self.serial.textChanged.connect(lambda _t: self._lens_checks())
        self._buttons()

    # ── folder / lens ────────────────────────────────────────────────────────
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "One camera's Old School folder", self.folder.text())
        if d:
            self.folder.setText(d); self._load_folder()

    def _load_folder(self):
        from src.extrinsic.oldschool import scan_old_school
        root = self.folder.text().strip()
        self._cs, self._res, self._folder_cam = None, None, ""
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
        self._folder_cam = self._cs.camera
        self._camera_text()
        for s in self._cs.setups:
            self.setups.addItem(f"{s.name}  {'(no van pose)' if s.van is None else ''}")
        got = self._provider(self._folder_cam)
        if got is not None:
            self._set_lens(got)
        self._look_up_van()
        self._lens_checks()
        self.status.emit(f"{self._cs.camera}: {len(self._cs.setups)} setups.")
        self._buttons()

    def _camera_text(self):
        """Camera line: the lens' camera (or the folder's when the lens doesn't say)."""
        if self._cs is None:
            self.camera_lbl.setText("—"); return
        from src.extrinsic.lens_check import camera_used
        lens_cam = getattr(self._intr, "camera", "") if self._intr else ""
        cam = camera_used(self._intr, self._folder_cam)
        where = ("from the lens" if lens_cam else "from the folder name" if cam else "")
        txt = (f"{cam} ({where})" if cam else "? (not in the lens or the folder name)")
        if lens_cam and self._folder_cam and lens_cam != self._folder_cam:
            txt += f"  ·  the folder says {self._folder_cam}"
        txt += f"   ·   {len(self._cs.setups)} setups" + (f"   ·   {self._cs.van}" if self._cs.van else "")
        self.camera_lbl.setText(txt)

    def _look_up_van(self):
        """The van's cameras from its database, in the background; the lens check uses them."""
        van = self.van or (self._cs.van if self._cs else "")
        self._db = None
        if not van:
            return
        from src.widgets.db_worker import DbWorker
        self._db_worker = DbWorker(van, self)
        self._db_worker.done.connect(self._db_done)
        self._db_worker.start()

    def _db_done(self, van, res):
        if van != (self.van or (self._cs.van if self._cs else "")):
            return                           # the van changed while looking
        self._db = res
        if res.error:
            self.status.emit(res.error[:200])
        self._lens_checks()

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
        # The serial and camera come from the lens (2026-11-10).  A wrong lens shows up in the
        # lens check: folder name, van database serial, and where the camera points.
        self._intr = intr
        self.lens.setText(intr.source)
        # Camera and serial come from the lens.  A lens file without a serial: type it.
        self.serial.setText(intr.serial or "")
        self.serial.setReadOnly(bool(intr.serial))
        self.serial.setPlaceholderText("From the lens" if intr.serial else "The lens file has no serial: type it")
        self._camera_text()
        self._lens_checks()
        self._buttons()

    def _lens_checks(self):
        """Right lens file?  One line per check, a tick or a warning sign, plain words."""
        from src.extrinsic.lens_check import OK, lens_checks
        if self._intr is None:
            self.lens_info.hide(); return []
        cks = lens_checks(self._intr, self._cs.setups if self._cs else [], self._folder_cam, self._db)
        rows = []
        for s, t, d in cks:
            col, sym = ("#3cc83c", "&#10003;") if s == OK else ("#e0b050", "&#9888;")
            rows.append(f"<div style='margin:2px 0'><span style='color:{col}; font-weight:bold'>{sym} {html.escape(t)}</span>"
                        + (f"<br><span style='color:#b8c0c8'>{html.escape(d)}</span>" if d else "") + "</div>")
        self.lens_info.setText("".join(rows)); self.lens_info.show()
        self._fit_lens_info()
        return cks

    def _fit_lens_info(self):
        # A word-wrapped rich-text label is often given one line too few; size it for its width.
        w = max(self.lens_info.width(), self.width() - 260, 400)
        self.lens_info.setMinimumHeight(self.lens_info.heightForWidth(w) + self.lens_info.fontMetrics().lineSpacing() + 4)
        self._fit_top()

    def _fit_top(self, share: float = 0.65):
        """Give the top part the room it needs to show everything (up to 65% of the height);
        the photos get the rest.  The splitter can still be dragged."""
        sizes = self._split.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        need = self._top.sizeHint().height() + 50          # + the Solve / Save row
        top = max(200, min(need, int(share * total)))
        self._split.setSizes([top, total - top])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.lens_info.isVisible():
            self._fit_lens_info()

    # ── solve ────────────────────────────────────────────────────────────────
    def _solve(self):
        if self._cs is None or self._intr is None:
            return
        from src.extrinsic.lens_check import camera_used
        cs = replace(self._cs, camera=camera_used(self._intr, self._folder_cam))   # results named after the lens' camera
        self._worker = _Worker(cs, self.site, self._intr, self)
        self._worker.progress.connect(self.status.emit)
        self._worker.done.connect(self._done)
        self._worker.start(); self._buttons(busy=True)

    def _done(self, res):
        self._buttons(busy=False)
        if isinstance(res, Exception):
            QMessageBox.critical(self, "Solve", str(res)); self.status.emit(str(res)); return
        self._res = res
        from src.extrinsic.lens_check import warnings_text
        cks = self._lens_checks()
        res.lens_checks = cks                       # the office page shows the same checks
        lens_warn = warnings_text(cks)
        res.warnings[:0] = lens_warn
        ok = res.passed
        txt = f"<span style='font-size:16pt; font-weight:bold'>{'PASS' if ok else 'NOT PASSED'}</span>"
        if res.R_bc is not None:
            pan, tilt, roll = res.pan_tilt_roll
            txt += (f"<br>Pan {pan:.2f}°, tilt {tilt:.2f}°, roll {roll:.2f}° (setups agree within "
                    f"{res.angle_spread_deg:.2f}°)  ·  height {res.up_ground_m:.3f} m  ·  forward "
                    f"{res.lever_frd[0]:.2f} m, right {res.lever_frd[1]:.2f} m (rough, GPS)")
        txt += "".join(f"<br>&bull; {r}" for r in res.reasons)
        for w in lens_warn:
            txt += f"<br><span style='color:#e0b050'>&#9888; {html.escape(w.split('. ')[0])} (see Lens check above)</span>"
        fg, bg = ("#3cc83c", "#1b3a1f") if ok else ("#ff6b6b", "#4a1c1c")
        self.result.setText(txt)
        self._fit_top()
        self.result.setStyleSheet(f"color: {fg}; background: {bg}; border: 1px solid {fg}; border-radius: 6px; padding: 8px;")
        self.result.show()
        self.setups.clear()
        for sr in res.setups:
            n = sr.solve.n_points if sr.solve else 0
            if sr.passed:
                why = (f"{n} targets, {sr.ground_targets} balls"
                       + (" (direction" + (", height)" if sr.counts_for_height else ")")
                          if getattr(sr, "counts_for_direction", False)
                          else (" (height)" if sr.counts_for_height else " (not for direction: weak)")))
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
            QMessageBox.warning(self, "Save", "The lens file has no serial: type the camera serial."); return
        from src.extrinsic.outputs import export_camera
        view = "0" if res.camera == "ROW" else ""
        out = export_camera(res, self.site, serial, self._intr.source, camera_view=view, intrinsic=self._intr)
        msg = f"Wrote:\n{out}"
        if not res.passed:
            msg += "\n\nNot passed: files are named NOT_PASSED_."
        QMessageBox.information(self, "Saved", msg)
        self.status.emit(f"Saved: {out}")

    def _open_viewer(self):
        from src.viewer import open_viewer
        open_viewer(self.folder.text().strip(), parent=self)

    def _buttons(self, busy=None):
        if busy is None:
            busy = bool(self._worker and self._worker.isRunning())
        self.solve_btn.setEnabled(self._cs is not None and self._intr is not None and not busy)
        self.save_btn.setEnabled(self._res is not None and self._res.R_bc is not None and not busy)
