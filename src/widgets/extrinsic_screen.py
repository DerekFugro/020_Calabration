"""extrinsic_screen.py — Load Extrinsic, one camera at a time.

Pick ONE camera's Old School folder (…\\Old School\\ForwardLeft) and its lens file.
The lens comes from this session's Load Intrinsic result for the same camera when it
passed, or from a CAL_*.yaml / *_intrinsic_cal.xml file.  Solve finds every target,
works out the camera's angles, height and lever arms, and Save writes every format.

Camera and serial come from the bar on top (Derek, 2026-11-10: one camera end to end).
The lens made on Load Intrinsic for that camera this session is used straight away, no
loading it twice.  The lens and the Old School folder are checked against the bar before
the solve (lens check), and where the camera points after it.  Warnings only, never a stop.
Changing the camera in the bar clears this tab (new_camera).

Buttons (View photos, Solve, Save all formats, Open report) sit in the top bar row, shown
only on this tab (self.actions; Derek, 2026-11-11).  A camera folder that was solved and
saved before says so: open the saved results, or solve again.  Save moves the earlier
Extrinsic_<date> folders into Superseded (src/superseded.py): one current result.
"""

from __future__ import annotations

import html
import os
from dataclasses import replace

from pathlib import Path

import cv2
import yaml
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
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

    def __init__(self, bar, intrinsic_provider=None, parent=None):
        super().__init__(parent)
        self.bar = bar                 # van, camera, serial (shared bar on top)
        self._provider = intrinsic_provider or (lambda: None)
        self._cs = None            # CameraSetups
        self._folder_cam = ""      # camera in the Old School folder name
        self._loaded = None        # (Extrinsic_<date> folder, its saved data) when showing saved results
        self._report_pdf = None    # the PDF of the result on screen, once saved
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
        self.solve_btn = QPushButton("Solve"); self.solve_btn.setObjectName("primary_button")
        self.save_btn = QPushButton("Save all formats")
        # Pop-up photo check (src/viewer): each setup's targets from its .targets.json
        self.view_btn = QPushButton("View photos...")
        self.view_btn.clicked.connect(self._open_viewer)
        self.report_btn = QPushButton("Open report")
        self.report_btn.setToolTip("The PDF of the result on screen (after Save, or an earlier saved result)")
        self.report_btn.clicked.connect(self._open_report)
        # These buttons live in the top bar row (app_window puts self.actions there).
        self.actions = QWidget()
        al = QHBoxLayout(self.actions); al.setContentsMargins(0, 0, 0, 0)
        for b in (self.view_btn, self.solve_btn, self.save_btn, self.report_btn):
            al.addWidget(b)

        box = QGroupBox("Camera")
        f = QFormLayout(box)
        r1 = QHBoxLayout(); r1.addWidget(self.folder, 1); r1.addWidget(fb)
        r2 = QHBoxLayout(); r2.addWidget(self.lens, 1); r2.addWidget(lb)
        f.addRow("Old School folder:", r1)
        f.addRow("Camera:", self.camera_lbl)
        f.addRow("Lens:", r2)
        # Is this the right lens file?  Plain words and dates, never a stop.
        self.lens_info = QLabel(""); self.lens_info.setWordWrap(True)
        self.lens_info.setTextFormat(Qt.TextFormat.RichText); self.lens_info.hide()
        self.lens_info.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        f.addRow("Lens check:", self.lens_info)
        info = QLabel(f"Control: {self.site.name} tennis-ball survey ({len(self.site.ids)} targets); the revised "
                      "control file is never used.  Old EOP files are never read: the app finds the targets.")
        info.setStyleSheet(_DIM); info.setWordWrap(True)
        f.addRow(info)

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
        ul.addWidget(top_scroll, 1)
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
        self.bar.changed.connect(self._bar_changed)
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
        self._loaded, self._report_pdf = None, None
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
        self.refresh_lens()
        self._lens_checks()
        self.status.emit(f"{self._cs.camera}: {len(self._cs.setups)} setups.")
        self._buttons()
        self._ask_about_saved()

    # ── solved before? (Derek, 2026-11-11) ───────────────────────────────────
    @staticmethod
    def _saved_data(folder: Path):
        """(data, pdf) from an Extrinsic_<date> folder, or (None, None)."""
        y = next((p for p in sorted(folder.glob("*_extrinsic.yaml"))), None)
        try:
            data = yaml.safe_load(y.read_text(encoding="utf-8")) if y else None
        except (OSError, ValueError, yaml.YAMLError):
            data = None
        return data, next((p for p in sorted(folder.glob("*_extrinsic.pdf"))), None)

    def _ask_about_saved(self):
        from src.superseded import extrinsic_results
        saved = extrinsic_results(self._cs.folder) if self._cs else []
        if not saved:
            return
        last = saved[-1]
        data, pdf = self._saved_data(last)
        g = (data or {}).get("grade") or {}
        when = last.name.replace("Extrinsic_", "")
        when = f"{when[:4]}-{when[4:6]}-{when[6:8]} {when[9:11]}:{when[11:13]}" if len(when) >= 13 else when
        what = (f"{data.get('camera', '?')} serial {data.get('serial', '?')}: "
                f"{'PASS' if g.get('passed') else 'NOT PASSED'}") if data else "(the saved files can't be read)"
        box = QMessageBox(self)
        box.setWindowTitle("Already solved")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"This camera was already solved and saved:\n{when}, {what}")
        box.setInformativeText("Open the saved results, or solve again?  (Saving a new result moves this one "
                               "into Superseded.)")
        open_btn = box.addButton("Open results", QMessageBox.ButtonRole.AcceptRole) if data else None
        pdf_btn = box.addButton("Open PDF", QMessageBox.ButtonRole.ActionRole) if pdf else None
        redo_btn = box.addButton("Solve again", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(open_btn or redo_btn)
        box.exec()
        clicked = box.clickedButton()
        if open_btn is not None and clicked is open_btn:
            self._show_saved(last, data, pdf)
        elif pdf_btn is not None and clicked is pdf_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf)))
        elif clicked is redo_btn:
            if self.solve_btn.isEnabled():
                self._solve()
            else:
                self.status.emit("Pick the lens (and the camera at the top), then Solve.")

    def _show_saved(self, folder: Path, data: dict, pdf):
        """Show a saved result from its files: banner, setups, and each setup's saved overlay."""
        self._res = None
        self._loaded, self._report_pdf = (folder, data), pdf
        g = data.get("grade") or {}
        ok = bool(g.get("passed"))
        pt = data.get("pointing_deg") or {}
        lv = data.get("lever_arm_m") or {}
        txt = f"<span style='font-size:16pt; font-weight:bold'>{'PASS' if ok else 'NOT PASSED'}</span>"
        txt += f"<br>Saved {html.escape(folder.name)}"
        if pt.get("pan_right") is not None:
            txt += (f"<br>Pan {pt['pan_right']:.2f}°, tilt {pt.get('tilt_up', 0):.2f}°, roll {pt.get('roll_cw', 0):.2f}°"
                    f"  ·  height {lv.get('up_above_pavement') or 0:.3f} m  ·  forward {lv.get('forward') or 0:.2f} m, "
                    f"right {lv.get('right') or 0:.2f} m (rough, GPS)")
        txt += "".join(f"<br>&bull; {html.escape(str(r))}" for r in g.get("reasons") or [])
        cam, ser = str(data.get("camera", "")), str(data.get("serial", ""))
        if (self.bar.camera and cam and cam != self.bar.camera) or (self.bar.serial and ser and ser != self.bar.serial):
            txt += (f"<br><span style='color:#e0b050'>&#9888; Saved for {html.escape(cam)} serial {html.escape(ser)}; "
                    f"the top bar says {html.escape(self.bar.camera)} serial {html.escape(self.bar.serial)}.</span>")
        fg, bg = ("#3cc83c", "#1b3a1f") if ok else ("#ff6b6b", "#4a1c1c")
        self.result.setText(txt)
        self.result.setStyleSheet(f"color: {fg}; background: {bg}; border: 1px solid {fg}; border-radius: 6px; padding: 8px;")
        self.result.show(); self._fit_top()
        self.setups.clear()
        for s in data.get("setups") or []:
            why = f"{s.get('targets', 0)} targets" if s.get("passed") else ((s.get("problems") or ["not used"])[0])
            self.setups.addItem(f"{'✓' if s.get('passed') else '✗'} {s.get('name', '')}  {why}")
        self.details.setPlainText("\n".join([str(g.get("headline", ""))] + [f"  - {x}" for x in g.get("reasons") or []]
                                            + [f"  ! {x}" for x in g.get("warnings") or []]))
        self.status.emit(f"Opened the saved result {folder.name}.")
        self._buttons()

    def _open_report(self):
        if self._report_pdf and Path(self._report_pdf).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._report_pdf)))
            self.status.emit(f"Opened {Path(self._report_pdf).name}")

    @property
    def van(self) -> str:
        return self.bar.van

    def _camera_text(self):
        """Camera line: what the top bar says, and the Old School folder if it disagrees."""
        cam, ser = self.bar.camera, self.bar.serial
        txt = (f"{cam}, serial {ser or '?'}  (top bar)" if cam else "Pick the camera and serial at the top")
        if self._cs is not None:
            if self._folder_cam and cam and self._folder_cam != cam:
                txt += f"   ·   the folder says {self._folder_cam}"
            txt += f"   ·   {len(self._cs.setups)} setups" + (f"   ·   {self._cs.van}" if self._cs.van else "")
        self.camera_lbl.setText(txt)

    def _bar_changed(self):
        self._camera_text(); self._lens_checks(); self._buttons()

    def refresh_lens(self):
        """Use this session's Load Intrinsic lens for the bar's camera, unless a lens file was picked."""
        if self._intr is not None and not self._intr.source.startswith("Load Intrinsic this session"):
            return
        got = self._provider()
        if got is not None:
            self._set_lens(got)

    def new_camera(self):
        """The camera changed in the top bar: start over (no folder, lens or result from the last camera)."""
        if self._worker is not None and self._worker.isRunning():
            return
        self._cs, self._intr, self._res, self._folder_cam = None, None, None, ""
        self._loaded, self._report_pdf = None, None
        self.folder.clear(); self.lens.clear(); self.setups.clear(); self.details.clear()
        self.result.hide(); self.lens_info.hide(); self.view.set_bgr(None)
        self._camera_text(); self._buttons()

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
        # A wrong lens shows up in the lens check: camera and serial against the top bar.
        self._intr = intr
        self.lens.setText(intr.source)
        self._camera_text()
        self._lens_checks()
        self._buttons()

    def _lens_checks(self):
        """Right lens file?  One line per check, a tick or a warning sign, plain words."""
        from src.extrinsic.lens_check import OK, lens_checks
        if self._intr is None:
            self.lens_info.hide(); return []
        cks = lens_checks(self._intr, self._cs.setups if self._cs else [], self.bar.camera, self.bar.serial,
                          self._folder_cam)
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
        cs = replace(self._cs, camera=self.bar.camera)      # results named after the top bar's camera
        self._worker = _Worker(cs, self.site, self._intr, self)
        self._worker.progress.connect(self.status.emit)
        self._worker.done.connect(self._done)
        self._worker.start(); self._buttons(busy=True)

    def _done(self, res):
        self._buttons(busy=False)
        if isinstance(res, Exception):
            QMessageBox.critical(self, "Solve", str(res)); self.status.emit(str(res)); return
        self._res = res
        self._loaded, self._report_pdf = None, None      # a new result: its report comes with Save
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
        if res is None and self._loaded is not None:
            self._show_saved_setup(i); return
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

    def _show_saved_setup(self, i):
        folder, data = self._loaded
        setups = data.get("setups") or []
        if i < 0 or i >= len(setups):
            return
        s = setups[i]
        pngs = sorted((folder / str(s.get("name", ""))).glob("*_targets.png"))
        img = cv2.imread(str(pngs[0])) if pngs else (cv2.imread(s["photo"]) if s.get("photo") and os.path.exists(s["photo"]) else None)
        self.view.set_bgr(img)
        L = [f"{s.get('name')}   seed: {s.get('seed') or '-'}   photo: {s.get('photo')}"]
        if s.get("pointing_deg"):
            p = s["pointing_deg"]; lf = s.get("lever_forward_right_m") or [0, 0]
            L.append(f"{s.get('targets')} targets ({s.get('tennis_balls_used')} balls), miss {s.get('miss_rms_mm')} mm RMS at "
                     f"{s.get('range_m')} m.  Pan {p[0]:.2f}, tilt {p[1]:.2f}, roll {p[2]:.2f} deg.  "
                     f"Forward {lf[0]:.2f}, right {lf[1]:.2f} m (VBS), up {s.get('up_above_pavement_m')} m above the pavement.")
        L += [f"  - {p}" for p in s.get("problems") or []]
        self.details.setPlainText("\n".join(L))

    # ── save ─────────────────────────────────────────────────────────────────
    def _save(self):
        res = self._res
        if res is None or res.R_bc is None:
            return
        serial = self.bar.serial
        if not serial:
            QMessageBox.warning(self, "Save", "Type the camera serial at the top."); return
        from src.extrinsic.outputs import export_camera
        from src.superseded import extrinsic_results, move_to_superseded
        earlier = extrinsic_results(res.folder)          # moved to Superseded once the new result is written
        view = "0" if res.camera == "ROW" else ""
        out = export_camera(res, self.site, serial, self._intr.source, camera_view=view, intrinsic=self._intr,
                            beside_photos=True)
        self._report_pdf = next(iter(sorted(Path(out).glob("*_extrinsic.pdf"))), None)
        msg = f"Wrote:\n{out}"
        written_eops, old_eops = getattr(res, "eops_beside_photos", ([], []))
        msg += f"\n\nEOP beside each photo (as the old Old School program did): {len(written_eops)} written."
        if old_eops:
            msg += f"  {len(old_eops)} earlier EOP(s) moved to Superseded."
        moved = move_to_superseded(earlier, res.folder)
        if moved:
            msg += f"\n\nThe earlier result ({', '.join(p.name for p in moved)}) moved to Superseded."
        if not res.passed:
            msg += "\n\nNot passed: files are named NOT_PASSED_."
        QMessageBox.information(self, "Saved", msg)
        self.status.emit(f"Saved: {out}")
        self._buttons()

    def _open_viewer(self):
        from src.viewer import open_viewer
        open_viewer(self.folder.text().strip(), parent=self)

    def _buttons(self, busy=None):
        if busy is None:
            busy = bool(self._worker and self._worker.isRunning())
        self.solve_btn.setEnabled(self._cs is not None and self._intr is not None and bool(self.bar.camera)
                                  and not busy)
        self.save_btn.setEnabled(self._res is not None and self._res.R_bc is not None and not busy)
        self.report_btn.setEnabled(bool(self._report_pdf) and not busy)
