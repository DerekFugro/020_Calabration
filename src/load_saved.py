"""load_saved.py - open a saved lens calibration as if it had just been processed.

Derek, 2026-11-06: picking a folder that is already calibrated loads the saved result
into the same report (3x3 squares, lens panel, View photos, Save, use for Load
Extrinsic), so people can check each other's work.  Nothing is recalculated:
  CAL_*.yaml      lens numbers, grade, reasons, warnings, lens steady, blur, board
  *.dots.json     every dot in every photo -> the 3x3 squares and their fit
  RUN_*.json      who / where / when / app version (found by the yaml's run_id)
check_by_rerunning() processes the photos again read-only (nothing in the folder
changes) and says how far today's lens is from the saved one.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml


def _dots_files(folder: Path) -> list[Path]:
    out = sorted(folder.glob("*.dots.json"))
    nu = folder / "NotUsed"
    if nu.is_dir():
        out += sorted(nu.glob("*.dots.json"))
    return out


def _board(block: dict):
    """The board a saved result used.  Dot boards are saved by name.  Chessboards are saved
    by squares and cell size only (no name), so match those against the library; failing
    that, rebuild the chessboard from the saved numbers.  (Bug 2026-11-14: every saved
    chessboard result re-opened with no board and the report crashed.)"""
    from src.board import BoardConfig
    from src.boards import list_boards
    block = block or {}
    boards = list_boards()
    name = block.get("name", "")
    if name:
        b = next((b for b in boards if b.name == name), None)
        if b is not None:
            return b
    try:
        sx, sy = int(block["squares_x"]), int(block["squares_y"])
        cw = float(block.get("cell_width_mm", 0)); ch = float(block.get("cell_height_mm", cw))
    except (KeyError, TypeError, ValueError):
        return None
    for b in boards:
        if (not b.is_dots and (b.squares_x, b.squares_y) == (sx, sy)
                and abs(b.cell_width_mm - cw) < 0.05 and abs(b.cell_height_mm - ch) < 0.05):
            return b
    return BoardConfig(squares_x=sx, squares_y=sy, cell_width_mm=cw, cell_height_mm=ch,
                       name=f"Chessboard {sx}x{sy} (from the saved file)")


def load_saved(yaml_path: str | Path):
    """A FolderRun rebuilt from the saved files.  Extra attributes:
    loaded_from (yaml path), loaded_note (one line for the report), run_id, run_log,
    saved_serial, saved_role."""
    from src.calibrator import CalibrationResult
    from src.detector import DetectionResult
    from src.grading import GradeReport, Repeatability
    from src.image_filter import FilterResult
    from src.pipeline import FolderRun

    yp = Path(yaml_path)
    d = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
    folder = yp.parent
    K = np.array(d["camera_matrix"]["data"], float).reshape(3, 3)
    D = np.array(d["dist_coeffs"]["data"], float).reshape(1, -1)
    res = d.get("image_resolution") or {}
    size = (int(res.get("width", 0)), int(res.get("height", 0)))
    run = FolderRun(folder=str(folder))
    run.board = _board(d.get("board") or {})
    run.board_note = "loaded from the saved calibration"

    run_id = d.get("run_id", "") or ""
    dets, filts, used, blur, removed, other_runs = [], [], [], [], [], set()
    for f in _dots_files(folder):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if run_id and j.get("run_id") and j["run_id"] != run_id:
            other_runs.add(j["run_id"])
        photo = str(f.with_name(j.get("photo", "")))
        dots = j.get("dots", [])
        ids = np.array([[x["n"]] for x in dots], np.int32).reshape(-1, 1)
        img = np.array([[x["x_px"], x["y_px"]] for x in dots], np.float32).reshape(-1, 1, 2)
        sz = tuple(j.get("image_size") or size)
        eb = j.get("edge_blur_px")
        det = DetectionResult(photo, sz, img if len(dots) else None, ids if len(dots) else None, len(dots), 0.0,
                              load_error=j.get("status") == "could not be read", load_error_msg=j.get("why", ""))
        det.edge_blur_px = float("nan") if eb is None else float(eb)
        st = j.get("status", "")
        dets.append(det)
        filts.append(FilterResult(st in ("used", "left out automatically"), j.get("why", ""), len(dots), 0.0))
        if st == "used" and len(dots) >= 4:
            obj = np.array([[x["board_x_mm"], x["board_y_mm"], 0.0] for x in dots], np.float64)
            used.append((photo, obj, img.reshape(-1, 2).astype(np.float64)))
            blur.append(det.edge_blur_px)
        elif st == "left out automatically":
            removed.append((photo, j.get("why", "")))
    rvecs, tvecs, pts = [], [], []
    for photo, obj, img in used:
        ok, rv, tv = cv2.solvePnP(obj, img, K, D)
        if ok:
            pts.append((photo, obj, img)); rvecs.append(rv); tvecs.append(tv)
    cal = CalibrationResult(camera_matrix=K, dist_coeffs=D, rms=float(d.get("rms_reprojection_error", math.nan)),
                            rvecs=rvecs, tvecs=tvecs, image_count_used=int(d.get("image_count_used", len(pts))),
                            image_size=size, points_used=pts, point_count_used=int(d.get("point_count_used", 0) or 0),
                            photo_blur_px=blur, auto_removed=removed)
    g = d.get("grade") or {}
    p95 = g.get("repeatability_p95_mrad")
    cal.grade = GradeReport(
        passed=bool(g.get("passed")), headline=str(g.get("headline", "no grade in the file")),
        hard_stops=list(g.get("hard_stops") or []), reasons=list(g.get("reasons") or []),
        warnings=list(g.get("warnings") or []), rms_px=cal.rms, images_used=cal.image_count_used,
        repeatability=None if p95 is None else Repeatability(float(p95), math.nan, math.nan, 0),
        more_photos=int(g.get("more_photos_needed") or 0),
        blur_median_px=float(g.get("dot_edge_blur_median_px") if g.get("dot_edge_blur_median_px") is not None else math.nan),
        left_out=[tuple(x) if isinstance(x, (list, tuple)) else (str(x), "") for x in (g.get("left_out_automatically") or [])])
    run.cal, run.detections, run.filter_results = cal, dets, filts

    # who / where / when, from the run log of that run
    log = folder / f"{run_id}.json" if run_id else None
    info = {}
    if log is not None and log.is_file():
        try:
            info = json.loads(log.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
    run.run_id, run.run_log = run_id, str(log) if info else ""
    when = d.get("calibration_datetime", "")
    who = (info.get("pc") or {}).get("computer", "")
    note = [f"LOADED from {yp.name} (saved {when.replace('T', ' ')}"
            + (f" on {who}" if who else "") + f", app {d.get('app_version', 'unknown')})."]
    if not dets:
        note.append("No .dots.json files here (saved before 2026-11-05): the 3x3 squares can't be shown; "
                    "use Check by re-running.")
    elif other_runs:
        note.append(f"The photo details (.dots.json) are from a later run ({', '.join(sorted(other_runs))}), "
                    "not the saved one.")
    run.loaded_from, run.loaded_note = str(yp), "  ".join(note)
    run.saved_serial, run.saved_role = str(d.get("serial_number", "")), str(d.get("camera_role", ""))
    return run


def compare(saved_run, new_run) -> tuple[bool, str]:
    """(agrees, text): today's re-run against the saved lens."""
    from src.grading import REPEAT_MAX_MRAD, ray_disagreement_mrad
    from src.version import app_version
    if new_run.error or new_run.cal is None:
        return False, f"The re-run did not finish: {new_run.error or 'no calibration'}"
    K1, D1, size = saved_run.cal.camera_matrix, saved_run.cal.dist_coeffs, tuple(saved_run.cal.image_size)
    K2, D2 = new_run.cal.camera_matrix, new_run.cal.dist_coeffs
    if tuple(new_run.cal.image_size) != size:
        return False, f"The photos are a different size now ({new_run.cal.image_size} vs saved {size})."
    diff = float(np.percentile(ray_disagreement_mrad(K1, D1, K2, D2, size), 95) * 10.0)
    limit = REPEAT_MAX_MRAD * 10.0
    agrees = diff <= limit and bool(new_run.passed) == bool(saved_run.grade.passed)
    g0, g1 = saved_run.grade, new_run.grade
    lines = [("AGREES" if agrees else "DOES NOT AGREE") + f" with the saved calibration.",
             f"Re-run with app {app_version()}: {g1.headline}",
             f"Saved result: {g0.headline}",
             f"Lens difference: {diff:.1f} mm at 10 m (95% of the picture; limit {limit:.0f} mm, the lens-steady limit).",
             f"Focal length: saved {K1[0, 0]:.1f}, re-run {K2[0, 0]:.1f} px ({100 * (K2[0, 0] / K1[0, 0] - 1):+.2f}%).",
             f"Photos used: saved {saved_run.cal.image_count_used}, re-run {new_run.cal.image_count_used}."]
    return agrees, "\n".join(lines)


def record_check(run_log: str | Path, agrees: bool, text: str) -> None:
    """Add the check to the saved run's log (who checked, when, the answer)."""
    from src.version import app_version
    p = Path(run_log)
    if not p.is_file():
        return
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.setdefault("checks", []).append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "computer": os.environ.get("COMPUTERNAME", ""), "user": os.environ.get("USERNAME", ""),
        "app_version": app_version(), "agrees": agrees, "result": text})
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")

