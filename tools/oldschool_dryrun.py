"""oldschool_dryrun.py - the whole Old School process on a made-up Richmond day (Phase 8).

    .venv\\Scripts\\python.exe tools\\oldschool_dryrun.py [--out E:\\DP\\SurveyorTest_OldSchool]

No van, POS or real site is used.  The real apps run with two stand-ins:
  * the camera: a fake input that shows the photo the camera would take at each position
    (tools/oldschool_fake_site.py draws the Richmond targets for a camera at a known place)
  * the POS logger: tests/fake_pos_logger.py, reporting the van pose of each position
Steps (each one the real app code, driven like a crew would):
  1. SurveyorCapture, Old School mode: 5 positions for ROW (Save image at each); position 3
     has the van creeping 0.5 m, so it must be rated NOT PASSED ("the van moved")
  2. the calibration app, Camera position: open the ROW folder, pick the lens, Solve, Save
  3. compare the saved result with the place the camera was really put (TRUTH.json)
Everything goes in <out>\\FullProcess_<date time>\\ (with SUMMARY.txt and screen pictures).
App settings go to a file in that folder, never the registry.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE_POS = ROOT / "tests" / "fake_pos_logger.py"
PORT = "Video (01-0 Pro Capture Dual SDI 4K+)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\DP\SurveyorTest_OldSchool")
    ap.add_argument("--camera", default="ROW")
    ap.add_argument("--serial", default="99000001")
    ap.add_argument("--mark-seconds", type=float, default=10.0, help="POS logging per position (real: 300)")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
    run = Path(a.out) / datetime.now().strftime("FullProcess_%Y%m%d_%H%M%S")
    run.mkdir(parents=True)
    lines: list[str] = []

    def say(*x):
        t = " ".join(str(v) for v in x)
        print(t, flush=True); lines.append(t)

    # settings to a file in the run folder, never the registry (same modules as tests/conftest.py)
    import importlib
    from PySide6.QtCore import QSettings
    (run / "_settings").mkdir()
    for name in ("src.capture.window", "src.widgets.camera_bar", "src.widgets.setup_screen"):
        importlib.import_module(name).QSettings = \
            lambda org="x", app="x", *r: QSettings(str(run / "_settings" / f"{org}_{app}.ini"), QSettings.Format.IniFormat)

    # ── the made-up day ──────────────────────────────────────────────────────
    import cv2
    import numpy as np
    import oldschool_fake_site as fs
    from src.extrinsic.control import load_site
    site = load_site()
    truth = fs.truth_for(a.camera)
    good = fs.find_positions(truth, 4)
    if len(good) < 4:
        say("Could not find 4 van positions that see enough targets."); return 1
    plan = [(good[0], 0.0), (good[1], 0.0), (good[1], 0.5), (good[2], 0.0), (good[3], 0.0)]
    poses = [dict(asdict(p), drift_m=d) for p, d in plan]
    (run / "_fake").mkdir()
    (run / "_fake" / "poses.json").write_text(json.dumps(poses, indent=1), encoding="utf-8")
    photos = [fs.render(site, p, truth, k) for k, (p, _d) in enumerate(plan)]
    lens = run / "Lens" / f"CAL_{a.serial}_20261115_120000.yaml"
    lens.parent.mkdir(); lens.write_text(fs.lens_yaml(a.serial), encoding="utf-8")
    (run / "TRUTH.json").write_text(json.dumps({"camera": truth.camera, "R_bc_zyx_deg": truth.R_bc_zyx_deg,
                                                "lever_fr_m": truth.lever_fr_m, "up_ground_m": truth.up_ground_m,
                                                "positions": poses}, indent=1), encoding="utf-8")
    say(f"Made-up day: {len(plan)} positions for {a.camera} (position 3: the van creeps 0.5 m).")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from src.styles import build_dark_palette
    app = QApplication([sys.argv[0]]); app.setPalette(build_dark_palette()); app.setStyle("Fusion")
    messages = []
    QMessageBox.information = staticmethod(lambda *x, **k: messages.append(("info", x[1:3])))
    QMessageBox.warning = staticmethod(lambda *x, **k: messages.append(("warning", x[1:3])))
    QMessageBox.question = staticmethod(lambda *x, **k: QMessageBox.StandardButton.No)

    def pump(s):
        t = time.time()
        while time.time() - t < s:
            app.processEvents(); time.sleep(0.03)

    def wait(cond, s):
        t = time.time()
        while time.time() - t < s:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.05)
        return False

    # ── 1. SurveyorCapture, Old School mode ──────────────────────────────────
    from src.capture.pos_link import PosLink
    from src.capture.source import FakeSource
    from src.capture.window import CaptureWindow
    now = [0]

    class Camera(FakeSource):                       # the photo of the position being collected
        def read(self):
            f = super().read()
            if f is None:
                return None
            f = photos[now[0]].copy(); f[0, 0] = self._n % 256      # a new frame each read
            return f

    def pos_factory():
        return PosLink(argv=[sys.executable, str(FAKE_POS), "--surveyor", "--out", "{out}", "--time-scale", "1",
                             "--poses", str(run / "_fake" / "poses.json")], cwd=str(run))

    w = CaptureWindow(use_db=False, names=[PORT], old_school=True, os_root=str(run),
                      source_factory=lambda cam, index: Camera(camera=a.camera), pos_factory=pos_factory)
    w._ask_close = lambda: True
    w.van_edit.setText("ARAN59"); w.van_edit.editingFinished.emit()
    w.show(); pump(1)
    w.camera_combo.setCurrentIndex(0); w.name_combo.setCurrentText(a.camera); w.serial_edit.setText(a.serial)
    w.size_combo.setCurrentText("1920 x 1080")
    if not wait(lambda: w._os.save_btn.isEnabled(), 30):
        say("Capture never got ready:", w._os.light.text(), w._os.light_text.text(), w.status.text()); return 1
    w.grab().save(str(run / "screen_1_capture_ready.png"))
    for k in range(len(plan)):
        now[0] = k
        pump(1.5)                                    # the live picture changes: the van moved here
        wait(lambda: w._os.save_btn.isEnabled(), 30)
        w._os._mark_secs = a.mark_seconds
        w._os.save_btn.click()
        if k == 0:
            pump(3); w.grab().save(str(run / "screen_2_capture_photos.png"))
        wait(lambda: not w._os.busy, a.mark_seconds + 60)
        say(f"  Capture: {w._os.result.text()}")
        if k == 2:
            w.grab().save(str(run / "screen_3_capture_not_passed.png"))
    say(f"  Capture says: {w._os.tally.text()}")
    w.grab().save(str(run / "screen_4_capture_done.png"))
    site_dir = Path(w.folder_edit.text())
    w.close(); pump(2)
    say(f"  POS logger closed cleanly: {w._os.pos.bye and not w._os.pos.killed}")

    # ── 2. the calibration app, Camera position ──────────────────────────────
    from src.extrinsic.intrinsic_source import from_file
    from src.widgets.launcher import Launcher
    L = Launcher(); L.show(); pump(1)
    win = L.open_main("extrinsic", use_db=False); pump(1)
    bar, ex = win.bar, win.extrinsic
    bar.van_edit.setText("ARAN59"); bar.role_combo.setCurrentText(a.camera); bar.serial_input.setText(a.serial)
    pump(0.5)
    ex.folder.setText(str(site_dir / a.camera)); ex._load_folder(); pump(0.5)
    ex._set_lens(from_file(str(lens))); pump(0.5)
    say(f"Camera position: {ex.setups.count()} setups listed: "
        + ", ".join(ex.setups.item(i).text().strip() for i in range(ex.setups.count())))
    ex.solve_btn.click()
    wait(lambda: ex._res is not None and not ex._worker.isRunning(), 300); pump(1)
    res = ex._res
    win.grab().save(str(run / "screen_5_camera_position_solved.png"))
    ex.save_btn.click(); pump(1)
    win.grab().save(str(run / "screen_6_camera_position_saved.png"))
    for kind, m in messages:
        say(f"  ({kind}) {m[0]}: {str(m[1]).splitlines()[0] if m[1] else ''}")
    win.close(); pump(1)

    # ── 3. compare with the truth ────────────────────────────────────────────
    from src.extrinsic.solve import pointing, rot_zyx
    if res is None or res.R_bc is None:
        say("RESULT: no camera place came out of the solve.")
    else:
        Rt = rot_zyx(*truth.R_bc_zyx_deg)
        err = float(np.degrees(np.arccos(np.clip((np.trace(res.R_bc.T @ Rt) - 1) / 2, -1, 1))))
        pt, ps = pointing(Rt), pointing(res.R_bc)
        for s in res.setups:
            say(f"  {s.setup.name}: {'used' if s.passed else 'not used'}"
                + (f", {s.solve.n_points} targets, miss {s.solve.loo_rms_mm:.1f} mm" if s.solve else "")
                + (f"  ({'; '.join(p for p in s.problems if not p.startswith('target '))})"
                   if [p for p in s.problems if not p.startswith('target ')] else ""))
        say(f"Pointing (pan, tilt, roll deg): put {np.round(pt, 3).tolist()}  solved {np.round(ps, 3).tolist()}"
            f"  -> off by {err:.4f} deg")
        say(f"Lever arm forward / right m: put {[round(v, 3) for v in truth.lever_fr_m]}  solved "
            f"{np.round(res.lever_frd[:2], 3).tolist()};  height: put {truth.up_ground_m:.3f}  solved {res.up_ground_m:.3f}")
        say(f"Camera position grade: {'PASS' if res.passed else 'NOT PASSED'} {'; '.join(res.reasons)}")
    saved = sorted((site_dir / a.camera).glob("Extrinsic_*"))
    say(f"Saved results: {saved[-1] if saved else 'none'}")
    say(f"Everything is in: {run}")
    (run / "SUMMARY.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
