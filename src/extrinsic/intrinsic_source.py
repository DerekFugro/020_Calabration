"""intrinsic_source.py — the lens calibration each camera's extrinsic is solved with.

Accepted:
  * a passed result from Load Intrinsic in this session;
  * our CAL_*.yaml (its grade must be passed);
  * a fleet intrinsic XML (<VAN>_<Camera>_<Serial>_intrinsic_cal.xml) — ours or older ones.
    Files named NOT_PASSED_… are refused.  An older XML not graded by this app is
    accepted but marked as such in every result.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import numpy as np
import yaml


@dataclass
class Intrinsic:
    K: np.ndarray
    D: np.ndarray
    serial: str
    source: str            # shown in every result
    graded_pass: bool      # passed this app's grade


def from_run(run, serial: str) -> Intrinsic | None:
    g = getattr(run, "grade", None)
    if run is None or run.cal is None or g is None or not g.passed:
        return None
    return Intrinsic(run.cal.camera_matrix.copy(), run.cal.dist_coeffs.ravel()[:5].copy(), serial,
                     f"Load Intrinsic this session: {run.folder} (PASS)", True)


def from_file(path: str) -> Intrinsic:
    name = os.path.basename(path)
    if name.upper().startswith("NOT_PASSED_"):
        raise ValueError(f"{name} did not pass; it can't be used.")
    if name.lower().endswith((".yaml", ".yml")):
        d = yaml.safe_load(open(path, encoding="utf-8"))
        g = d.get("grade") or {}
        if g and not g.get("passed"):
            raise ValueError(f"{name}: its grade is not a pass ({g.get('headline', '')}).")
        K = np.array(d["camera_matrix"]["data"], float).reshape(3, 3)
        D = np.array(d["dist_coeffs"]["data"], float).ravel()[:5]
        return Intrinsic(K, D, str(d.get("serial_number", "")), f"{path} ({'PASS' if g else 'no grade'})", bool(g))
    if name.lower().endswith(".xml"):
        from src.van_scan import read_filed_xml
        f = read_filed_xml(path)
        if f is None:
            raise ValueError(f"{name} is not an intrinsic XML this app can read.")
        K = np.array([[f["fx"], 0, f["cx"]], [0, f["fy"], f["cy"]], [0, 0, 1.0]])
        D = np.array([f["k1"], f["k2"], f["p1"], f["p2"], f["k3"]])
        m = re.search(r"_(\d+)_intrinsic_cal\.xml$", name, re.I)
        return Intrinsic(K, D, m.group(1) if m else "", f"{path} (not graded by this app)", False)
    raise ValueError("Pick a CAL_*.yaml or an *_intrinsic_cal.xml file.")
