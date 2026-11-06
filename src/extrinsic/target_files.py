"""target_files.py - <photo>.targets.json beside each Old School photo, written by every Solve.

The extrinsic twin of src/dot_files.py (Derek, 2026-11-05: months later a person or an
AI agent must be able to check exactly what happened).  Per setup: the van pose read
from the csv, the starting guess, whether the setup was used and why not, the solve
summary, and every target the pose says should be in view: wall disc or tennis ball,
found or not (and whether on the first pass or the second look), where it was found and
where the pose put it (px), used or dropped and why, its leave-one-out miss (mm), range,
and its surveyed position.  Also copied into the Extrinsic_<date> folder at Save.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np

SUFFIX = ".targets.json"


def _r(x, n=3):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else round(v, n)


def setup_doc(sr, site, cam, run_id: str = "") -> dict:
    from src.version import app_version
    s, m, sol = sr.setup, sr.match, sr.solve
    idx = site.index()
    found = {p: (x, y, k) for p, x, y, k in (m.matches if m else [])}
    used = set(sol.ids) if sol else set()
    loo = dict(zip(sol.ids, sol.loo_mm)) if sol else {}
    rng = dict(zip(sol.ids, sol.range_m)) if sol else {}
    dropped = dict(sol.dropped) if sol else {}
    ids = list(m.predicted) if m else []
    ids += [p for p in found if p not in ids]
    targets = []
    for pid in ids:
        i = idx.get(pid)
        f = found.get(pid)
        pr = m.predicted.get(pid) if m else None
        targets.append({
            "id": pid,
            "kind": "tennis ball" if (i is not None and bool(site.ground[i])) else "wall disc",
            "found": f is not None,
            "found_by": None if f is None else ("second look" if "2nd look" in f[2] else "first pass"),
            "x_px": None if f is None else _r(f[0]), "y_px": None if f is None else _r(f[1]),
            "predicted_x_px": None if pr is None else _r(pr[0]), "predicted_y_px": None if pr is None else _r(pr[1]),
            "used": pid in used,
            "dropped_why": dropped.get(pid),
            "miss_mm": _r(loo.get(pid), 1),
            "range_m": _r(rng.get(pid), 2),
            "surveyed_E_N_H_m": None if i is None else [_r(v, 4) for v in site.enh_m[i]],
        })
    v = s.van
    solve = None
    if sol is not None:
        from src.extrinsic.solve import pointing
        pan, tilt, roll = pointing(sol.R_bc) if sol.R_bc is not None else (None, None, None)
        solve = {"targets_used": sol.n_points, "miss_rms_mm": _r(sol.loo_rms_mm, 1),
                 "range_mean_m": _r(np.mean(sol.range_m), 2),
                 "pan_tilt_roll_deg": [_r(pan), _r(tilt), _r(roll)],
                 "lever_forward_right_m": None if sol.lever_frd is None else [_r(sol.lever_frd[0]), _r(sol.lever_frd[1])],
                 "up_above_pavement_m": _r(sol.up_ground_m),
                 "camera_E_N_H_m": [_r(x, 4) for x in sol.cam_enh]}
    return {
        "run_id": run_id,
        "app_version": app_version(),
        "written": datetime.now().isoformat(timespec="seconds"),
        "van": cam.van, "camera": cam.camera, "setup": s.name, "photo": os.path.basename(s.photo or ""),
        "site": site.name,
        "van_pose": None if v is None else {
            "csv": os.path.basename(s.pose_csv or ""), "rows": v.rows, "gps_status": v.gps_status,
            "roll_deg": _r(v.roll, 4), "pitch_deg": _r(v.pitch, 4), "heading_true_deg": _r(v.heading, 4),
            "lat": _r(v.lat, 8), "lon": _r(v.lon, 8), "elevation": _r(v.elevation),
            "moved_while_parked_deg": _r(v.spread_deg)},
        "starting_guess": sr.seed or None,
        "used": bool(sr.passed),
        "problems": list(sr.problems),
        "match_note": (m.note or None) if m else None,
        "tennis_balls_used": sr.ground_targets,
        "counts_for_height": sr.counts_for_height,
        "counts_for_direction": getattr(sr, "counts_for_direction", False),
        "solve": solve,
        "targets_in_view": len(m.predicted) if m else 0,
        "targets_found": len(found),
        "targets": targets,
    }


def write_target_files(cam, site, out_dir: str | Path | None = None, run_id: str = "") -> int:
    """One file per setup: beside the photo (out_dir None) or in out_dir/<setup>/.
    Never raises for one setup."""
    n = 0
    for sr in cam.setups:
        try:
            if not sr.setup.photo:
                continue
            stem = Path(sr.setup.photo).stem
            if out_dir is None:
                p = Path(sr.setup.photo).with_name(stem + SUFFIX)
            else:
                d = Path(out_dir) / sr.setup.name
                d.mkdir(parents=True, exist_ok=True)
                p = d / (stem + SUFFIX)
            p.write_text(json.dumps(setup_doc(sr, site, cam, run_id), indent=1), encoding="utf-8")
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n
