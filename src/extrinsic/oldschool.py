"""oldschool.py — find Old School setups and read what each one holds.

<van Old School folder>/<camera>/<setup timestamp>/
    *.jpg (or .bmp)        the photo (the .bmp is a decoded copy of the .jpg)
    *.EOP                  ignored: the app finds the targets itself and writes its own EOP
    ReviewData_*.csv or *Processed*.csv   the van's Applanix values while parked
    *.gcp                  ignored: the site control file is used instead
<camera>/PGExteriorCalibration*.RWC, PGInteriorCalibration*.RWC   old exe results (compare)

Setups in folders named DO NOT USE, Bad, or with "(do not use)" are skipped.
"""

from __future__ import annotations

import csv
import glob
import os
import re
from dataclasses import dataclass, field

import numpy as np

from src.van_scan import camera_from_name, van_from_path

SKIP_RE = re.compile(r"do[\s_]*not[\s_]*use|(^|[\\/])bad([\\/]|$)", re.I)


@dataclass
class VanPose:
    roll: float
    pitch: float
    heading: float          # true north, deg
    lat: float
    lon: float
    elevation: float        # as written in the csv (units / datum: see report)
    gps_status: str
    rows: int
    spread_deg: float       # largest attitude spread while parked


@dataclass
class Setup:
    folder: str
    name: str
    photo: str = ""
    photo_id: int = 0
    pose_csv: str = ""
    van: VanPose | None = None
    problems: list = field(default_factory=list)


@dataclass
class CameraSetups:
    folder: str
    camera: str
    van: str
    setups: list = field(default_factory=list)
    old_exterior_rwc: str = ""
    old_interior_rwc: str = ""


def _first_col(header, name):
    for i, h in enumerate(header):
        if h.strip().lower() == name.lower():
            return i
    return None


def read_van_pose(path: str) -> VanPose | None:
    with open(path, newline="", encoding="utf-8", errors="ignore") as fh:
        rd = csv.reader(fh)
        hdr = next(rd, None)
        if not hdr:
            return None
        cols = {k: _first_col(hdr, k) for k in ("Roll", "Pitch", "Heading", "Latitude", "Longitude",
                                                  "Elevation", "GPS Status")}
        if any(cols[k] is None for k in ("Roll", "Pitch", "Heading", "Latitude", "Longitude")):
            return None
        vals, status = [], []
        for row in rd:
            try:
                vals.append([float(row[cols[k]]) for k in ("Roll", "Pitch", "Heading", "Latitude", "Longitude")]
                            + [float(row[cols["Elevation"]]) if cols["Elevation"] is not None else np.nan])
                if cols["GPS Status"] is not None:
                    status.append(row[cols["GPS Status"]].strip())
            except (ValueError, IndexError):
                continue
    if not vals:
        return None
    a = np.array(vals)
    hd = a[:, 2]
    hd_c = np.degrees(np.angle(np.mean(np.exp(1j * np.radians(hd)))))      # circular mean
    hd_dev = (hd - hd_c + 180) % 360 - 180
    spread = float(max(np.ptp(a[:, 0]), np.ptp(a[:, 1]), np.ptp(hd_dev)))
    med = np.median(a, axis=0)
    st = max(set(status), key=status.count) if status else ""
    return VanPose(roll=float(med[0]), pitch=float(med[1]), heading=float(hd_c % 360),
                   lat=float(med[3]), lon=float(med[4]), elevation=float(med[5]),
                   gps_status=st, rows=len(a), spread_deg=spread)


def _setup(folder: str) -> Setup:
    s = Setup(folder=folder, name=os.path.basename(folder))
    jpg = sorted(glob.glob(os.path.join(folder, "*.jpg")) + glob.glob(os.path.join(folder, "*.jpeg")))
    bmp = sorted(glob.glob(os.path.join(folder, "*.bmp")))
    s.photo = (jpg or bmp or [""])[0]
    if s.photo:
        try:
            s.photo_id = int(os.path.splitext(os.path.basename(s.photo))[0])
        except ValueError:
            pass
    else:
        s.problems.append("no photo")
    csvs = (glob.glob(os.path.join(folder, "*Processed*.csv")) + glob.glob(os.path.join(folder, "ReviewData*.csv"))
            + sorted(glob.glob(os.path.join(folder, "*.csv"))))
    for c in csvs:                       # first csv that has the Applanix columns
        v = read_van_pose(c)
        if v is not None:
            s.pose_csv, s.van = c, v
            break
    if s.van is None:
        s.problems.append("no van pose (ReviewData / Processed csv)")
    return s


def scan_old_school(root: str) -> list[CameraSetups]:
    """Every camera folder under root that holds setup folders with a photo."""
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not SKIP_RE.search(x)]
        if SKIP_RE.search(d):
            continue
        if not any(f.lower().endswith((".jpg", ".jpeg", ".bmp")) for f in files):
            continue
        if not any(f.lower().endswith(".csv") for f in files):     # the van pose file
            continue
        cam_dir = os.path.dirname(d)
        cam = camera_from_name(os.path.basename(cam_dir))
        cs = out.get(cam_dir)
        if cs is None:
            cs = CameraSetups(folder=cam_dir, camera=cam, van=van_from_path(cam_dir))
            ext = sorted(glob.glob(os.path.join(cam_dir, "PGExteriorCalibration*.RWC")))
            itr = sorted(glob.glob(os.path.join(cam_dir, "PGInteriorCalibration*.RWC")))
            cs.old_exterior_rwc = ext[-1] if ext else ""
            cs.old_interior_rwc = itr[-1] if itr else ""
            out[cam_dir] = cs
        cs.setups.append(_setup(d))
    for cs in out.values():
        cs.setups.sort(key=lambda s: s.name)
    return sorted(out.values(), key=lambda c: (c.camera, c.folder))
