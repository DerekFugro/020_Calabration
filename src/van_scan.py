"""van_scan.py — find every camera's photo folder under a van's Intrinsic folder.

For each folder holding calibration photos it works out:
  camera  from the folder name (ForwardRight, FR, Row, RearLeft…)
  serial  from a filed intrinsic XML  <VAN>_<Camera>_<Serial>_intrinsic_cal.xml
          or one of our CAL_<serial>_… YAMLs, in the folder or its parent
  van     from the path (ARAN65, "Aran 68", ARAN_75…)
Anything it can't work out is left blank for the user to fill in.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.utils import find_images

MIN_IMAGES = 15

# canonical name -> lower-case aliases seen in the dailies
CAMERA_ALIASES = {
    "ForwardLeft":  ["forwardleft", "fl", "frontleft", "forward_left", "front_left"],
    "ForwardRight": ["forwardright", "fr", "frontright", "forward_right", "front_right"],
    "ROW":          ["row"],
    "RearLeft":     ["rearleft", "rl", "rear_left"],
    "RearRight":    ["rearright", "rr", "rear_right"],
    "Right":        ["right", "sideright", "rightside", "side_right"],
    "Left":         ["left", "sideleft", "leftside", "side_left"],
    "PAVE":         ["pave", "rear"],
}
CAMERAS = list(CAMERA_ALIASES)

_VAN_RE = re.compile(r"aran[\s_]*(\d{2,3})", re.I)
_XML_RE = re.compile(r"(?P<van>aran[\s_]*\d+)_(?P<cam>[A-Za-z]+)_(?P<serial>\d+)_intrinsic_cal\.xml$", re.I)
_CAL_RE = re.compile(r"^CAL_(?P<serial>[^_]+)_\d{8}_\d{6}\.yaml$", re.I)


def camera_from_name(name: str) -> str:
    key = re.sub(r"[\s\-]", "", name).lower()
    for canon, aliases in CAMERA_ALIASES.items():
        if key in aliases:
            return canon
    return ""


def van_from_path(path: str) -> str:
    m = None
    for m in _VAN_RE.finditer(str(path)):
        pass                      # last match = closest to the photos
    return f"ARAN{int(m.group(1))}" if m else ""


@dataclass
class CameraFolder:
    folder: str
    camera: str = ""
    serial: str = ""
    van: str = ""
    images: int = 0
    filed_xml: str = ""          # filed intrinsic for comparison, if any
    notes: list = field(default_factory=list)


def _serial_for(folder: Path, camera: str) -> tuple[str, str]:
    """(serial, filed_xml_path) from files in the folder or its parent."""
    for d in (folder, folder.parent):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            m = _XML_RE.search(n)
            if m and camera_from_name(m.group("cam")) == camera:
                return m.group("serial"), str(d / n)
    try:
        for n in sorted(os.listdir(folder), reverse=True):
            m = _CAL_RE.match(n)
            if m:
                return m.group("serial"), ""
    except OSError:
        pass
    return "", ""


def scan(root: str, min_images: int = MIN_IMAGES) -> list[CameraFolder]:
    """Every folder under root with at least min_images photos, sorted by camera."""
    out = []
    for d, dirs, _files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() != "notused"]
        n = len(find_images(d))
        if n < min_images:
            continue
        p = Path(d)
        cf = CameraFolder(folder=d, images=n)
        cf.camera = camera_from_name(p.name)
        if not cf.camera:
            cf.notes.append(f"camera not known from folder name '{p.name}'")
        cf.van = van_from_path(d)
        if cf.camera:
            cf.serial, cf.filed_xml = _serial_for(p, cf.camera)
        if not cf.serial:
            cf.notes.append("serial not found; type it in")
        out.append(cf)
    order = {c: i for i, c in enumerate(CAMERAS)}
    out.sort(key=lambda c: (order.get(c.camera, 99), c.folder))
    return out


def read_filed_xml(path: str) -> dict | None:
    """fx, fy, cx, cy, k1.. from a filed fleet XML (None if unreadable)."""
    import xml.etree.ElementTree as ET
    try:
        r = ET.parse(path).getroot()
        m = r.find("OpenCVCameraModel")
        g = lambda tag, a: float(m.find(tag).get(a))  # noqa: E731
        return dict(width=int(m.get("width")), height=int(m.get("height")),
                    fx=g("FocalLength", "x"), fy=g("FocalLength", "y"),
                    cx=g("Center", "x"), cy=g("Center", "y"),
                    k1=g("RadialDistortion", "k1"), k2=g("RadialDistortion", "k2"),
                    k3=g("RadialDistortion", "k3"),
                    p1=g("TangentialDistortion", "p1"), p2=g("TangentialDistortion", "p2"))
    except Exception:  # noqa: BLE001
        return None
