"""outputs.py — write an Old School (extrinsic) result in every format we know.

Per camera, into <camera folder>/Extrinsic_<date>/ :
  <setup>/<photo id>.EOP     same layout as the old exe's EOP (see EOP_NOTE)
  <setup>/<photo id>_targets.png   the photo with found targets, numbers and misses
  <stem>_extrinsic.yaml      everything: angles (3 ways), lever arms, per setup, grade
  <stem>_setups.csv          one row per setup
  <stem>_extrinsic.json
  PGExteriorCalibration_<serial>_<date>.RWC   old exe format (angles UNVERIFIED, see RWC_NOTE)
  <stem>_extrinsic.pdf       report
  <stem>_CHECK.html          one page for the office: PASS/FAIL, checks, photos (open before loading)
A camera that did not pass still gets its files, all named NOT_PASSED_…

And, exactly as the old Old School program did (Derek, 2026-11-11: the office may still
look for them there), <setup folder>/<photo id>.EOP beside each photo, passed or not, no
prefix.  The EOP already there is moved to <camera folder>/Superseded/<setup>/ first.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

from src.extrinsic.control import US_FT
from src.extrinsic.solve import ENU2NED, pointing, rot_mean, rot_zyx

EOP_NOTE = ("EOP header: lines 1-3 = principal point x, y and focal length (px), lines 4-6 = camera X, Y, Z "
            "in control units (US ft), 7-9 = photogrammetric angles. Lines 4-9 match the old exe's files; "
            "lines 1-3 are inferred (2026-11-01, 664 old EOPs: their medians sit at the image centre, and "
            "solving with them puts the camera within 0.45 ft of lines 4-6, against 1.7 ft with the "
            "camera's own calibration), so they are the old exe's per-setup lens solve. We write our "
            "calibrated values there.")
RWC_NOTE = ("PGExteriorCalibration angles use the best rule found from 26 old RWC files (rear cameras "
            "agreed within 0.3-2 deg, forward cameras did not): NOT VERIFIED. UpLeverArm is written the "
            "old way (camera height, NAVD88, m); the real camera height above the pavement is in the "
            "YAML. GroundCoefficient1-8 are not known and are written as 0.")


# ── angles ───────────────────────────────────────────────────────────────────

def opk(R_wc) -> tuple[float, float, float]:
    """Photogrammetric angles as in the old EOP lines 7-9 (order as written there)."""
    M = R_wc @ np.diag([1.0, -1.0, -1.0])
    ph = math.degrees(math.asin(max(-1, min(1, M[0, 2]))))
    om = math.degrees(math.atan2(-M[1, 2], M[2, 2]))
    ka = math.degrees(math.atan2(-M[0, 1], M[0, 0]))
    return ph, om, ka


_M_RWC = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])   # rwc_convention.json


def rwc_angles(cam) -> tuple[float, float, float]:
    """Heading/Pitch/RollOffset by the rule fitted to old RWC files (unverified).

    The fit used: van roll with its sign flipped, true heading, camera->van rotation,
    then extrinsic Euler 'zxy' of (R_bc @ M) as (Heading, Roll, Pitch).
    """
    Rs = []
    for sr in cam.setups:
        if not (sr.passed and sr.solve is not None):
            continue
        v = sr.setup.van
        R_nb = rot_zyx(v.heading, v.pitch, -v.roll)
        Rs.append(R_nb.T @ (ENU2NED @ sr.solve.R_wc))
    if not Rs:
        return (math.nan,) * 3
    A = rot_mean(Rs) @ _M_RWC
    b = math.asin(max(-1, min(1, -A[1, 2])))
    a = math.atan2(A[1, 0], A[1, 1])
    c = math.atan2(A[0, 2], A[2, 2])
    return math.degrees(a), math.degrees(c), math.degrees(b)        # heading, pitch, roll


# ── per-setup files ──────────────────────────────────────────────────────────

def write_eop(sr, site, path: Path, K=None) -> None:
    s, sol, m = sr.setup, sr.solve, sr.match
    o_ft = site.enh_m / US_FT
    idx = site.index()
    found = {p: (x, y) for p, x, y, _k in (m.matches if m else [])}
    used = set(sol.ids) if sol else set()
    rows = []
    for pid, (px, py) in (m.predicted.items() if m else []):
        if pid in found and pid in used:
            rows.append((pid, *found[pid], 1))
        else:
            rows.append((pid, px, py, 2))
    rows.sort(key=lambda r: (int(r[0]) if r[0].lstrip("-").isdigit() else 0))
    cam_ft = sol.cam_enh / US_FT if sol else np.zeros(3)
    ang = opk(sol.R_wc) if sol else (0, 0, 0)
    stem = Path(s.photo).stem
    lens = [K[0, 2], K[1, 2], (K[0, 0] + K[1, 1]) / 2] if K is not None else [0.0, 0.0, 0.0]
    L = [f"{v:.6f}" for v in lens] + [f"{v:.6f}" for v in cam_ft] + [f"{v:.6f}" for v in ang]
    L += ["", str(Path(s.folder) / stem), "", str(len(rows)), "",
          "PhotoID     \tPointID     \t      Xg   \t          Yg    \t      Zg      \t      Xp    \t     Yp    \t Status", ""]
    for pid, x, y, st in rows:
        X, Y, Z = o_ft[idx[pid]]
        L.append(f"{stem}\t{pid:<12s}\t{X:12.3f}\t{Y:12.3f}\t{Z:12.3f}\t{x:12.3f}\t{y:11.3f}\t{st:5d}")
    path.write_bytes(("\r\n".join(L) + "\r\n").encode("ascii"))


GREEN, RED, ORANGE = (60, 200, 60), (80, 80, 255), (40, 180, 255)


def _label(img, text, x, y, col, sc):
    """Text in a dark box, so it reads on the white wall and the dark pavement."""
    fs, th = 0.55 * sc, max(1, int(round(1.4 * sc)))
    (tw, tht), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
    x, y = int(x), int(y)
    h, w = img.shape[:2]
    x = min(max(0, x), w - tw - 6)
    y = min(max(tht + 6, y), h - 4)
    cv2.rectangle(img, (x - 3, y - tht - 5), (x + tw + 3, y + base), (25, 25, 25), -1)
    cv2.rectangle(img, (x - 3, y - tht - 5), (x + tw + 3, y + base), col, max(1, int(sc)))
    cv2.putText(img, text, (x, y - 2), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th, cv2.LINE_AA)


def overlay(sr, site, K, D) -> np.ndarray | None:
    """The photo with every target marked for a person to check:
    green = found and used (number + miss in mm), red = found but left out (why),
    orange = should be in view but not found.  Zoom in to read the small ones."""
    img = cv2.imread(sr.setup.photo) if sr.setup.photo else None
    if img is None:
        return None
    sc = img.shape[1] / 1920.0
    r0, t = int(14 * sc), max(2, int(round(2 * sc)))
    sol, m = sr.solve, sr.match
    used = set(sol.ids) if sol else set()
    dropped = {p: why for p, why in (sol.dropped if sol else [])}
    miss = dict(zip(sol.ids, sol.loo_mm)) if sol is not None else {}
    found = {p: (x, y) for p, x, y, _k in (m.matches if m else [])}
    if m is not None:
        for pid, (px, py) in m.predicted.items():
            if pid in found and pid in used:
                x, y = found[pid]
                cv2.circle(img, (int(x), int(y)), r0, GREEN, t, cv2.LINE_AA)
                cv2.line(img, (int(x - r0 * 1.6), int(y)), (int(x - r0 * 0.6), int(y)), GREEN, t)
                cv2.line(img, (int(x + r0 * 0.6), int(y)), (int(x + r0 * 1.6), int(y)), GREEN, t)
                cv2.line(img, (int(x), int(y - r0 * 1.6)), (int(x), int(y - r0 * 0.6)), GREEN, t)
                cv2.line(img, (int(x), int(y + r0 * 0.6)), (int(x), int(y + r0 * 1.6)), GREEN, t)
                _label(img, f"{pid}  {miss.get(pid, 0):.0f} mm", x + r0 * 1.8, y - r0 * 0.4, GREEN, sc)
            elif pid in found:
                x, y = found[pid]
                cv2.drawMarker(img, (int(x), int(y)), RED, cv2.MARKER_TILTED_CROSS, int(r0 * 2.2), t)
                why = dropped.get(pid, "left out")
                _label(img, f"{pid} left out: {why.split(':')[0]}", x + r0 * 1.8, y - r0 * 0.4, RED, sc)
            else:
                cv2.circle(img, (int(px), int(py)), int(r0 * 0.8), ORANGE, t, cv2.LINE_AA)
                _label(img, f"{pid} not found", px + r0 * 1.2, py - r0 * 0.4, ORANGE, sc)
    if sol is not None:
        head = (f"{sr.setup.name}   {'USED' if sr.passed else 'NOT USED'}   {sol.n_points} targets   "
                f"miss {sol.loo_rms_mm:.1f} mm RMS")
    else:
        head = f"{sr.setup.name}   NOT USED"
    lines = [head] + [p for p in sr.problems][:3]
    for i, ln in enumerate(lines):
        _label(img, ln, 12 * sc, (34 + i * 30) * sc, GREEN if sr.passed else RED, sc * (1.25 if i == 0 else 1.0))
    return img


# ── per-camera files ─────────────────────────────────────────────────────────

def _app_version() -> str:
    from src.version import app_version
    return app_version()


def summary(cam, serial: str, intrinsic_source: str) -> dict:
    pan, tilt, roll = cam.pan_tilt_roll
    h, p, r = rwc_angles(cam)
    good = [s for s in cam.setups if s.passed and s.solve is not None]
    cam_h = float(np.mean([s.solve.cam_enh[2] for s in good])) if good else math.nan
    return {
        "van": cam.van, "camera": cam.camera, "serial": serial,
        "created": datetime.now().isoformat(timespec="seconds"),
        "app_version": _app_version(),
        "run_id": getattr(cam, "run_id", ""),
        "per_target_detail": "<setup>/<photo>.targets.json (also beside each Old School photo)",
        "old_school_folder": cam.folder, "intrinsic": intrinsic_source,
        "grade": {"passed": cam.passed, "headline": cam.headline, "reasons": cam.reasons,
                  "warnings": cam.warnings},
        "pointing_deg": {"pan_right": round(pan, 3), "tilt_up": round(tilt, 3), "roll_cw": round(roll, 3),
                         "spread_between_setups_max": round(cam.angle_spread_deg, 3)},
        "camera_to_van_matrix": None if cam.R_bc is None else [[round(float(v), 8) for v in row] for row in cam.R_bc],
        "camera_to_van_note": "columns = camera x right, y down, z view, in van axes forward, right, down",
        "lever_arm_m": {"forward": round(float(cam.lever_frd[0]), 3) if cam.lever_frd is not None else None,
                        "right": round(float(cam.lever_frd[1]), 3) if cam.lever_frd is not None else None,
                        "up_above_pavement": round(cam.up_ground_m, 3),
                        "forward_right_spread": None if cam.lever_spread_m is None
                        else [round(float(v), 3) for v in cam.lever_spread_m[:2]],
                        "up_spread": round(cam.height_spread_m, 3),
                        "reference": "forward/right from the van's GPS position (ground at the front of the van), "
                                     "VBS, rough; up = camera height above the surveyed pavement",
                        "camera_height_navd88_m": round(cam_h, 3)},
        "rwc_angles_unverified_deg": {"heading_offset": round(h, 3), "pitch_offset": round(p, 3),
                                      "roll_offset": round(r, 3)},
        "setups": [{
            "name": s.setup.name, "photo": s.setup.photo, "passed": s.passed, "seed": s.seed,
            "targets": s.solve.n_points if s.solve else 0,
            "miss_rms_mm": round(s.solve.loo_rms_mm, 1) if s.solve else None,
            "range_m": round(float(np.mean(s.solve.range_m)), 1) if s.solve else None,
            "pointing_deg": [round(v, 3) for v in pointing(s.solve.R_bc)] if s.solve else None,
            "lever_forward_right_m": [round(float(v), 3) for v in s.solve.lever_frd[:2]] if s.solve else None,
            "up_above_pavement_m": round(s.solve.up_ground_m, 3) if s.solve else None,
            "van_gps_status": s.setup.van.gps_status if s.setup.van else "",
            "true_to_grid_north_deg": round(s.solve.north_corr_deg, 3) if s.solve else None,
            "tennis_balls_used": s.ground_targets, "counts_for_height": s.counts_for_height,
            "counts_for_direction": getattr(s, "counts_for_direction", False),
            "problems": s.problems,
        } for s in cam.setups],
        "notes": [EOP_NOTE, RWC_NOTE],
    }


def write_rwc(cam, serial: str, path: Path, camera_view: str = "") -> None:
    h, p, r = rwc_angles(cam)
    good = [s for s in cam.setups if s.passed and s.solve is not None]
    cam_h = float(np.mean([s.solve.cam_enh[2] for s in good])) if good else math.nan
    hdr = ("IDPGExteriorCalibration,CameraView,ForwardLeverArm,UpLeverArm,RightLeverArm,HeadingOffset,"
           "PitchOffset,RollOffset,GroundCoefficient1,GroundCoefficient2,GroundCoefficient3,GroundCoefficient4,"
           "GroundCoefficient5,GroundCoefficient6,GroundCoefficient7,GroundCoefficient8,TruckSerialNumber,EffectiveDate")
    d = datetime.now()
    date = f"{d.month}/{d.day}/{d.year} {d.strftime('%I:%M %p').lstrip('0')}"
    f, rgt = (cam.lever_frd[0], cam.lever_frd[1]) if cam.lever_frd is not None else (math.nan, math.nan)
    row = [1, camera_view, f"{f:.4f}", f"{cam_h:.4f}", f"{rgt:.4f}", f"{h:.3f}", f"{p:.3f}", f"{r:.3f}"] \
        + ["0"] * 8 + [serial, date]
    path.write_bytes((hdr + "\r\n" + ",".join(str(v) for v in row)).encode("ascii"))


def write_eops_beside_photos(cam, site) -> tuple[list[Path], list[Path]]:
    """EOPs exactly where and as the old Old School program wrote them (Derek, 2026-11-11: the
    office may still look for them there): <setup folder>\\<photo>.EOP, passed or not, no prefix.
    Every EOP already beside a photo of this camera (the old program's, or an earlier save) is
    moved to <camera folder>\\Superseded\\<setup>\\ first, so no setup keeps another run's EOP.
    Returns (written, moved)."""
    from src.superseded import move_to_superseded
    written, moved = [], []
    for sr in cam.setups:
        s = sr.setup
        if not s.photo:
            continue
        target = Path(s.photo).with_suffix(".EOP")
        old = [p for p in Path(s.folder).glob("*.EOP") if p.is_file()] if Path(s.folder).is_dir() else []
        moved += move_to_superseded(old, cam.folder, sub=s.name)
        if sr.solve is not None:
            write_eop(sr, site, target, cam.K)
            written.append(target)
    return written, moved


def export_camera(cam, site, serial: str, intrinsic_source: str, camera_view: str = "",
                  out_root: str | None = None, intrinsic=None, beside_photos: bool = False) -> Path:
    dt = datetime.now()
    out = Path(out_root or cam.folder) / f"Extrinsic_{dt:%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    pre = "" if cam.passed else "NOT_PASSED_"
    stem = f"{pre}{cam.van}_{cam.camera}_{serial}"
    overlays = {}
    for sr in cam.setups:
        if sr.match is None:
            continue
        d = out / sr.setup.name
        d.mkdir(exist_ok=True)
        pid = Path(sr.setup.photo).stem
        if sr.solve is not None:
            write_eop(sr, site, d / f"{pre}{pid}.EOP", cam.K)
        img = overlay(sr, site, cam.K, cam.D)
        if img is not None:
            cv2.imwrite(str(d / f"{pre}{pid}_targets.png"), img)
            overlays[sr.setup.name] = img
    data = summary(cam, serial, intrinsic_source)
    try:
        from src.extrinsic.target_files import write_target_files
        write_target_files(cam, site, out_dir=out, run_id=getattr(cam, "run_id", ""))
    except Exception:  # noqa: BLE001 - the detail file never costs the save
        pass
    (out / f"{stem}_extrinsic.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                                                encoding="utf-8")
    (out / f"{stem}_extrinsic.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with open(out / f"{stem}_setups.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["setup", "passed", "targets", "miss_rms_mm", "range_m", "pan_deg", "tilt_deg", "roll_deg",
                    "lever_forward_m", "lever_right_m", "up_above_pavement_m", "problems"])
        for s in data["setups"]:
            pt = s["pointing_deg"] or [None] * 3
            lv = s["lever_forward_right_m"] or [None] * 2
            w.writerow([s["name"], s["passed"], s["targets"], s["miss_rms_mm"], s["range_m"], *pt, *lv,
                        s["up_above_pavement_m"], " | ".join(s["problems"])])
    write_rwc(cam, serial, out / f"{pre}PGExteriorCalibration_{serial}_{dt:%Y%b%d_%H_%M}.RWC", camera_view)
    try:
        from src.extrinsic.html_report import write_html
        write_html(cam, site, data, out / f"{stem}_CHECK.html", serial, intrinsic, overlays)
    except Exception as exc:  # noqa: BLE001
        (out / f"{stem}_html_error.txt").write_text(str(exc), encoding="utf-8")
    try:
        from src.extrinsic.report import write_pdf
        write_pdf(cam, data, out / f"{stem}_extrinsic.pdf")
    except Exception as exc:  # noqa: BLE001
        (out / f"{stem}_pdf_error.txt").write_text(str(exc), encoding="utf-8")
    if beside_photos:
        cam.eops_beside_photos = write_eops_beside_photos(cam, site)
    return out
