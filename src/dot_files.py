"""dot_files.py - one <photo>.dots.json beside each lens photo, for trouble-shooting.

Written at Save (src/output_writer.write_outputs).  Each file says whether the photo
was used, left out (and why) or never usable, and lists every dot (or chessboard
corner) found in it: its number on the board, where it was found (px), where it is
on the board (mm), and its fit - how far it sits from where the finished lens says
it should be (px).  Named .dots.json because Lucid raw frames already have a
<name>.json beside them that the raw converter reads.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

SUFFIX = ".dots.json"


def dots_path(image_path: str) -> Path:
    p = Path(image_path)
    return p.with_name(p.stem + SUFFIX)


def _fit(obj, img, K, D):
    """Per-dot distance (px) from where the finished lens puts each dot, with this
    photo's board pose solved from its own dots.  None if it can't be solved."""
    if len(obj) < 6:
        return None
    ok, rv, tv = cv2.solvePnP(obj.astype(np.float64), img.astype(np.float64), K, D)
    if not ok:
        return None
    pr, _ = cv2.projectPoints(obj.astype(np.float64), rv, tv, K, D)
    return np.hypot(*(pr.reshape(-1, 2) - img).T)


def write_dot_files(cal, board, detections, filter_results) -> int:
    """Write the files; returns how many were written.  Never raises for one bad photo."""
    K = np.asarray(cal.camera_matrix, np.float64)
    D = np.asarray(cal.dist_coeffs, np.float64).ravel()
    all_obj = board.get_all_object_points()
    key = lambda p: os.path.normcase(os.path.abspath(str(p)))  # noqa: E731
    used = {key(p) for p, _o, _i in getattr(cal, "points_used", [])}
    removed = {key(p): why for p, why in getattr(cal, "auto_removed", []) or []}
    stamp = datetime.now().isoformat(timespec="seconds")
    n = 0
    for det, filt in zip(detections, filter_results):
        try:
            k = key(det.image_path)
            if k in used:
                status, why = "used", ""
            elif k in removed:
                status, why = "left out automatically", removed[k]
            elif det.load_error:
                status, why = "could not be read", det.load_error_msg
            else:
                status, why = "not used", getattr(filt, "reason", "")
            dots, fit_rms = [], None
            if det.charuco_ids is not None and det.charuco_corners is not None and len(det.charuco_ids):
                ids = det.charuco_ids.ravel().astype(int)
                img = det.charuco_corners.reshape(-1, 2).astype(np.float64)
                okk = ids < len(all_obj)
                ids, img = ids[okk], img[okk]
                obj = all_obj[ids].reshape(-1, 3)
                fit = _fit(obj, img, K, D)
                if fit is not None:
                    fit_rms = round(float(np.sqrt(np.mean(fit ** 2))), 3)
                for j, (i, (x, y)) in enumerate(zip(ids, img)):
                    dots.append({"n": int(i), "x_px": round(float(x), 3), "y_px": round(float(y), 3),
                                 "board_x_mm": round(float(obj[j, 0]), 3), "board_y_mm": round(float(obj[j, 1]), 3),
                                 "fit_px": None if fit is None else round(float(fit[j]), 3)})
            blur = getattr(det, "edge_blur_px", float("nan"))
            doc = {
                "photo": os.path.basename(det.image_path),
                "written": stamp,
                "image_size": list(det.image_size) if det.image_size else None,
                "board": getattr(board, "name", ""),
                "status": status,
                "why": why,
                "in_NotUsed_folder": Path(det.image_path).parent.name == "NotUsed",
                "edge_blur_px": None if blur is None or (isinstance(blur, float) and np.isnan(blur)) else round(float(blur), 3),
                "dots_found": len(dots),
                "fit_rms_px": fit_rms,
                "fit_note": "fit_px = how far the dot sits from where the finished lens says it should be, "
                            "with this photo's board position solved from its own dots",
                "dots": dots,
            }
            dots_path(det.image_path).write_text(json.dumps(doc, indent=1), encoding="utf-8")
            n += 1
        except Exception:  # noqa: BLE001 - one bad photo must not stop the others or the save
            continue
    return n
