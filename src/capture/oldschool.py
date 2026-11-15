"""oldschool.py - Old School collection without Qt (Phase 8): folder names and each position's rating.

Derek, 2026-11-15:
  <root picked by the crew>\\ExtrinsicAran<XX>_<YYYYMMDD_HHMMSS>\\<camera>\\Position<N>\\
      a few photos + the POS logger's 5-minute CSV + CAPTURE_*.json (with the rating)
  One camera at a time; the crew waits the 5 minutes; each position is rated PASS / NOT PASSED:
    POS     PASS if the light stayed green the whole time and the van did not move
    photos  PASS if at least one photo is sharp and shows a picture (not "no signal")
  NOT PASSED -> "Redo this position" (the folder is kept; the next Save makes Position<N+1>).
The limits below are first guesses: set them on the first real van run (the plan says so).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

PHOTOS = 5                 # photos per position (all kept; the solve uses the sharpest)
PHOTO_EVERY_S = 1.0        # Magewell inputs are read once a second
MARK_SECONDS = 300.0       # POS logging per position (Derek: 5 minutes)
MIN_POSITIONS = 3          # the camera position solve needs at least 3 per camera

# "The van moved" is judged by position, speed, roll and pitch - NOT heading: on a parked van
# (ARAN59, 2026-11-15, 5 minutes) the position stayed within 2 cm and speed 0, roll / pitch
# within 0.025 deg, but the POS heading wandered 0.21 deg (and 0.5 deg over 30 minutes).
# The heading spread is kept in the log.  Limits are first guesses, to set on more van runs.
MAX_TILT_SPREAD_DEG = 0.10  # roll / pitch over the 5 minutes (parked: 0.025)
MAX_MOVE_M = 0.10           # position spread, metres (parked: 0.018)
MAX_SPEED_MPS = 0.10        # (parked: 0.0)
MIN_ROWS_PER_S = 40        # POS Group 1 is ~50 a second
MIN_SHARPNESS = 20.0       # variance of the Laplacian on a 960-wide grey copy
MIN_CONTRAST = 8.0         # grey level spread: below this the picture is blank (lens cap, black)


def site_folder_name(van: str, when: datetime | None = None) -> str:
    """ExtrinsicAran59_20261115_164300 (van ARAN59).  Other names are kept, made safe."""
    when = when or datetime.now()
    v = (van or "").strip()
    m = re.fullmatch(r"(?i)aran\s*(\d+)", v)
    tag = f"Aran{m.group(1)}" if m else re.sub(r"[^A-Za-z0-9]+", "", v)
    return f"Extrinsic{tag}_{when:%Y%m%d_%H%M%S}"


def next_position(camera_folder: Path) -> int:
    """The next free Position<N> number (a redo never reuses a folder)."""
    used = [int(m.group(1)) for p in Path(camera_folder).glob("Position*")
            if (m := re.fullmatch(r"Position(\d+)", p.name, re.I)) and p.is_dir()]
    return max(used, default=0) + 1


def make_position_folder(site: Path, camera: str) -> tuple[int, Path]:
    """Make <site>\\<camera>\\Position<N> (exclusive) and return (N, folder)."""
    cam = Path(site) / camera
    cam.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        n = next_position(cam)
        p = cam / f"Position{n}"
        try:
            p.mkdir()
            return n, p
        except FileExistsError:
            continue
    raise OSError(f"Could not make a new Position folder in {cam}.")


# ── photos ───────────────────────────────────────────────────────────────────
def photo_quality(img: np.ndarray | None) -> tuple[float, float]:
    """(sharpness, contrast) of a BGR photo; (0, 0) if there is none."""
    import cv2
    if img is None or img.size == 0:
        return 0.0, 0.0
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if g.shape[1] > 960:
        g = cv2.resize(g, (960, int(round(g.shape[0] * 960 / g.shape[1]))), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(g, cv2.CV_64F).var()), float(g.std())


@dataclass
class PhotoCheck:
    file: str
    sharpness: float
    contrast: float
    no_signal: bool

    @property
    def usable(self) -> bool:
        return (not self.no_signal and self.contrast >= MIN_CONTRAST and self.sharpness >= MIN_SHARPNESS)


def check_photos(paths) -> list[PhotoCheck]:
    import cv2
    from src.capture.nosignal import is_no_signal
    out = []
    for p in paths:
        img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR) if Path(p).exists() else None
        s, c = photo_quality(img)
        out.append(PhotoCheck(Path(p).name, round(s, 1), round(c, 1), img is None or is_no_signal(img)))
    return out


# ── the rating ───────────────────────────────────────────────────────────────
@dataclass
class Rating:
    passed: bool
    reasons: list = field(default_factory=list)     # plain words, empty when passed
    best_photo: str = ""
    still: dict = field(default_factory=dict)       # how still the van was (from the POS CSV)

    def text(self, n: int) -> str:
        if self.passed:
            return f"Position {n}: PASS"
        return f"Position {n}: NOT PASSED - {'; '.join(self.reasons)}. Redo this position."

    def as_dict(self) -> dict:
        return {"passed": self.passed, "reasons": list(self.reasons), "best_photo": self.best_photo,
                "still": self.still,
                "limits": {"max_tilt_spread_deg": MAX_TILT_SPREAD_DEG, "max_move_m": MAX_MOVE_M,
                           "max_speed_mps": MAX_SPEED_MPS, "min_rows_per_s": MIN_ROWS_PER_S,
                           "min_sharpness": MIN_SHARPNESS, "min_contrast": MIN_CONTRAST}}


def van_still(csv_path) -> dict:
    """From the position's POS CSV: position spread (m), top speed, and roll / pitch / heading spread."""
    import csv
    cols = ("lat_deg", "lon_deg", "speed_mps", "roll_deg", "pitch_deg", "heading_deg")
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            vals = [[float(r[k]) for k in cols] for r in csv.DictReader(fh)
                    if all(r.get(k) not in (None, "") for k in cols)]
    except (OSError, ValueError, KeyError):
        return {}
    if not vals:
        return {}
    a = np.array(vals)
    lat0 = np.radians(a[:, 0].mean())
    n = 6371008.8 * np.radians(a[:, 0] - a[:, 0].mean())
    e = 6371008.8 * np.cos(lat0) * np.radians(a[:, 1] - a[:, 1].mean())
    hd = a[:, 5]
    hd = (hd - hd[0] + 180) % 360 - 180                     # across north
    return {"move_m": round(float(np.hypot(n, e).max() * 2), 4), "max_speed_mps": round(float(np.abs(a[:, 2]).max()), 4),
            "roll_spread_deg": round(float(np.ptp(a[:, 3])), 4), "pitch_spread_deg": round(float(np.ptp(a[:, 4])), 4),
            "heading_spread_deg": round(float(np.ptp(hd)), 4), "rows": len(a)}


def rate_position(pos, photos: list[PhotoCheck], still: dict | None = None) -> Rating:
    """pos = pos_link.MarkResult (None if the POS never finished this position);
    still = van_still() of its CSV ({} if it could not be read: roll / pitch from the summary only)."""
    why = []
    still = still or {}
    if pos is None:
        why.append("the POS did not finish logging this position")
    else:
        secs = float(pos.seconds or MARK_SECONDS)
        if not pos.complete or pos.rows < MIN_ROWS_PER_S * secs:
            why.append("the POS logging stopped early")
        if not pos.green_whole_time:
            msg = f" ({pos.worst_message})" if pos.worst_message else ""
            why.append(f"the POS lost accuracy{msg}")
        tilt = [s for s in pos.spread_deg[:2] if s is not None]
        moved = (len(tilt) < 2 or max(tilt) > MAX_TILT_SPREAD_DEG
                 or still.get("move_m", 0.0) > MAX_MOVE_M or still.get("max_speed_mps", 0.0) > MAX_SPEED_MPS)
        if moved:
            why.append("the van moved")
    good = [p for p in photos if p.usable]
    if not photos:
        why.append("no photos were saved")
    elif not good:
        if all(p.no_signal or p.contrast < MIN_CONTRAST for p in photos):
            why.append("the photos show no picture")
        else:
            why.append("the photos are blurry")
    best = max(good or photos, key=lambda p: p.sharpness, default=None)
    return Rating(passed=not why, reasons=why, best_photo=best.file if best else "", still=dict(still))
