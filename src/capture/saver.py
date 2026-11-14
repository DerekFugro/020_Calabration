"""saver.py - save one full-size photo: <Camera>_<YYYYMMDD_HHMMSS_mmm>.jpg, never overwrite.

No resizing, cropping or filtering.  Written with cv2.imencode + a plain file write so folder
names with any characters work; the file is created exclusively (never replaces one).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import numpy as np


def safe_camera(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip()).strip("_")
    return s or "Camera"


def photo_path(folder, camera: str, when: datetime | None = None) -> Path:
    """A name that doesn't exist yet: <Camera>_<YYYYMMDD_HHMMSS_mmm>.jpg, then _2, _3 ..."""
    when = when or datetime.now()
    stem = f"{safe_camera(camera)}_{when:%Y%m%d_%H%M%S}_{when.microsecond // 1000:03d}"
    p = Path(folder) / f"{stem}.jpg"
    n = 2
    while p.exists():
        p = Path(folder) / f"{stem}_{n}.jpg"
        n += 1
    return p


def save_jpeg(frame: np.ndarray, folder, camera: str, quality: int = 95, when: datetime | None = None) -> Path:
    """Write the full frame; returns the path.  Raises OSError if it can't be written."""
    import cv2
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(max(1, min(100, quality)))])
    if not ok:
        raise OSError("The photo could not be turned into a JPEG.")
    Path(folder).mkdir(parents=True, exist_ok=True)
    for _ in range(20):
        p = photo_path(folder, camera, when)
        try:
            with open(p, "xb") as fh:              # exclusive: never overwrite
                fh.write(buf.tobytes())
            return p
        except FileExistsError:
            continue
    raise OSError(f"Could not find a free file name in {folder}.")
