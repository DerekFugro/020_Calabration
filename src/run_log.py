"""run_log.py - RUN_<date>_<time>.json in the photo folder: what one run did, never overwritten.

Derek, 2026-11-05: months later a person or an AI agent must be able to check exactly
what happened.  One file per run, written at the end of the run (pass, fail or error),
and updated once more if the result is saved.  Holds: when and on which PC, the app
version, what was typed or found (van, camera, serial, and where each came from), the
board, every photo's fate, the result, any error with its traceback, and what Save
wrote.  Each photo's <photo>.dots.json carries the same run_id.
"""

from __future__ import annotations

import json
import os
import socket
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np

PREFIX = "RUN_"


def new_run_id(folder: str, when: datetime) -> str:
    base = f"{PREFIX}{when:%Y%m%d_%H%M%S}"
    rid, n = base, 1
    while (Path(folder) / f"{rid}.json").exists():
        n += 1
        rid = f"{base}_{n}"
    return rid


def _num(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, np.ndarray):
        return [_num(v) for v in x.tolist()]
    if isinstance(x, float) and (x != x):        # NaN -> null
        return None
    return x


def _photos(run, run_dots: dict) -> list:
    out = []
    for det in run.detections:
        info = run_dots.get(os.path.normcase(os.path.abspath(det.image_path)), {})
        out.append({"photo": os.path.basename(det.image_path),
                    "status": info.get("status", ""), "why": info.get("why", ""),
                    "in_NotUsed_folder": Path(det.image_path).parent.name == "NotUsed",
                    "dots_found": info.get("dots_found", int(det.corner_count or 0)),
                    "fit_rms_px": info.get("fit_rms_px")})
    return out


def write_run_log(run, run_id: str, started: datetime, inputs: dict | None, error_trace: str,
                  photo_info: dict) -> Path:
    from src.version import app_version
    from src.utils import photos_taken
    from src.van_scan import van_from_computer
    finished = datetime.now()
    first, last, how = photos_taken(run.folder)
    cal, g = run.cal, run.grade
    result = None
    if cal is not None:
        rep = getattr(g, "repeatability", None)
        result = {
            "image_size": _num(list(cal.image_size)),
            "camera_matrix": _num(np.asarray(cal.camera_matrix)),
            "dist_coeffs": _num(np.asarray(cal.dist_coeffs).ravel()),
            "rms_px": _num(float(cal.rms)),
            "photos_used": int(cal.image_count_used),
            "left_out_automatically": [[os.path.basename(p), why] for p, why in (cal.auto_removed or [])],
            "grade": None if g is None else {
                "passed": bool(g.passed), "headline": g.headline, "reasons": list(g.reasons),
                "warnings": list(g.warnings), "hard_stops": list(g.hard_stops),
                "lens_steady_at_10m_mm": round(float(rep.at_10m_mm), 2) if rep is not None else None,
                "dot_edge_blur_px": _num(round(float(getattr(g, "blur_median_px", float("nan"))), 2)),
                "more_photos_needed": int(getattr(g, "more_photos", 0) or 0)},
            "vs_fleet_lens_file_10m_mm": _num(run.vs_filed_10m_mm),
        }
    doc = {
        "run_id": run_id,
        "what": "One Load Intrinsic run of this folder (SurveyorCalibration). Never overwritten.",
        "app_version": app_version(),
        "pc": {"computer": os.environ.get("COMPUTERNAME") or socket.gethostname(),
               "user": os.environ.get("USERNAME") or os.environ.get("USER", ""),
               "van_from_computer_name": van_from_computer()},
        "started": started.isoformat(timespec="seconds"),
        "finished": finished.isoformat(timespec="seconds"),
        "seconds": round((finished - started).total_seconds(), 1),
        "folder": run.folder,
        "inputs": inputs or {},
        "photos_taken": {"first": first.isoformat(timespec="seconds") if first else None,
                         "last": last.isoformat(timespec="seconds") if last else None, "from": how},
        "board": None if run.board is None else {"name": run.board.name, "how_chosen": run.board_note or "picked by hand"},
        "photos_found": len(run.detections),
        "moved_to_NotUsed": [[f, why] for f, why in run.moved],
        "photos": _photos(run, photo_info),
        "result": result,
        "error": run.error or None,
        "error_detail": error_trace or None,
        "saved": None,
    }
    p = Path(run.folder) / f"{run_id}.json"
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return p


def record_save(run_log: str | Path, **saved) -> None:
    """Add what Save wrote (and the van/camera/serial it used) to the run's log."""
    p = Path(run_log)
    if not p.is_file():
        return
    doc = json.loads(p.read_text(encoding="utf-8"))
    entry = {"at": datetime.now().isoformat(timespec="seconds"), **{k: _num(v) for k, v in saved.items()}}
    prev = doc.get("saved")
    doc["saved"] = entry if prev is None else (prev if isinstance(prev, list) else [prev]) + [entry]
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def format_trace() -> str:
    return traceback.format_exc()
