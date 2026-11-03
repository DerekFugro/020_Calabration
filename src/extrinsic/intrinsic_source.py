"""intrinsic_source.py — the lens calibration a camera's extrinsic is solved with.

Accepted (Derek, 2026-11-03: a lens that did not pass may be used for now, with a warning):
  * this session's Load Intrinsic result for the camera, passed or not;
  * our CAL_*.yaml, passed or not;
  * a fleet intrinsic XML (<VAN>_<Camera>_<Serial>_intrinsic_cal.xml), ours or older ones,
    including NOT_PASSED_ files.
Anything that did not pass, or was never graded by this app, carries a `warning` that is
shown on the screen, in the results and on the office check page.
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
    warning: str = ""      # set when the lens did not pass or was never graded


def from_run(run, serial: str) -> Intrinsic | None:
    g = getattr(run, "grade", None)
    if run is None or run.cal is None or g is None or getattr(run, "error", ""):
        return None
    K, D = run.cal.camera_matrix.copy(), run.cal.dist_coeffs.ravel()[:5].copy()
    if g.passed:
        return Intrinsic(K, D, serial, f"Load Intrinsic this session: {run.folder} (PASS)", True)
    return Intrinsic(K, D, serial, f"Load Intrinsic this session: {run.folder} (NOT PASSED)", False,
                     f"The lens did not pass its own check ({g.headline}). Usable for now; redo the lens.")


def from_file(path: str) -> Intrinsic:
    name = os.path.basename(path)
    not_passed = name.upper().startswith("NOT_PASSED_")
    if name.lower().endswith((".yaml", ".yml")):
        d = yaml.safe_load(open(path, encoding="utf-8"))
        g = d.get("grade") or {}
        K = np.array(d["camera_matrix"]["data"], float).reshape(3, 3)
        D = np.array(d["dist_coeffs"]["data"], float).ravel()[:5]
        serial = str(d.get("serial_number", ""))
        if g and g.get("passed") and not not_passed:
            return Intrinsic(K, D, serial, f"{path} (PASS)", True)
        if g:
            return Intrinsic(K, D, serial, f"{path} (NOT PASSED)", False,
                             f"The lens did not pass its own check ({g.get('headline', '')}). "
                             "Usable for now; redo the lens.")
        return Intrinsic(K, D, serial, f"{path} (no grade)", False,
                         "The lens file has no grade from this app. Usable for now; redo the lens.")
    if name.lower().endswith(".xml"):
        from src.van_scan import read_filed_xml
        f = read_filed_xml(path)
        if f is None:
            raise ValueError(f"{name} is not an intrinsic XML this app can read.")
        K = np.array([[f["fx"], 0, f["cx"]], [0, f["fy"], f["cy"]], [0, 0, 1.0]])
        D = np.array([f["k1"], f["k2"], f["p1"], f["p2"], f["k3"]])
        m = re.search(r"_(\d+)_intrinsic_cal\.xml$", name, re.I)
        why = ("The lens file is marked NOT_PASSED." if not_passed
               else "The lens file was not graded by this app.")
        return Intrinsic(K, D, m.group(1) if m else "", f"{path} ({'NOT PASSED' if not_passed else 'not graded by this app'})",
                         False, why + " Usable for now; redo the lens.")
    raise ValueError("Pick a CAL_*.yaml or an *_intrinsic_cal.xml file.")
