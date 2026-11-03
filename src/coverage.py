"""coverage.py — 3 x 3 grid: how well the calibration did in each part of the image.

The image is split into 3 x 3 equal areas.  Every board point used in the
calibration falls in one area (by where it was detected in its image).  For
each area:

  points     How many board points landed there, over all images.  Few points
             = the lens is guessed there, not measured.  Corners matter most:
             that is where distortion is strongest.
  error      RMS reprojection error of those points (px): how well the final
             calibration fits that part of the lens.
  tilt       Spread of board angles seen there: the largest angle between the
             board directions of any two images that put >= 3 points in the
             area.  A board only ever seen flat-on in an area does not pin down
             the focal length there.

Each measure is rated good / weak / poor with the limits below; the area's
colour is its worst rating.  The limits are starting values chosen
2026-10-31 —
adjust them here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np


GRID_N = 3

# ── Limits (edit here) ───────────────────────────────────────────────────────
POINTS_GOOD = 30            # >= this many points: good
POINTS_POOR = 10            # <  this many points: poor
ERROR_GOOD_PX = 0.5    # <  0.5 px: good
ERROR_POOR_PX = 1.0    # >  1.0 px: poor (red)
TILT_GOOD_DEG = 20.0        # >= 20 deg spread of board angles: good
TILT_POOR_DEG = 10.0        # <  10 deg: poor
MIN_POINTS_PER_VIEW = 3     # an image counts toward an area's tilt spread
                            # only if it puts at least this many points there

GOOD, WEAK, POOR = "good", "weak", "poor"
_RANK = {GOOD: 0, WEAK: 1, POOR: 2}

ROW_NAMES = ("Top", "Middle", "Bottom")
COL_NAMES = ("left", "centre", "right")


@dataclass
class GridCell:
    row: int
    col: int
    points: int = 0
    images: int = 0                 # images with >= 1 point here
    rms_px: float = math.nan        # nan when no points
    tilt_spread_deg: float = 0.0
    points_status: str = POOR
    error_status: str = POOR
    tilt_status: str = POOR
    status: str = POOR              # worst of the three

    @property
    def name(self) -> str:
        if self.row == 1 and self.col == 1:
            return "Centre"
        return f"{ROW_NAMES[self.row]}-{COL_NAMES[self.col]}"

    def problems(self) -> list[str]:
        """Plain-language reasons this area is not green (empty if good)."""
        out = []
        if self.points_status != GOOD:
            out.append(f"only {self.points} points — take more photos with the "
                       f"board in this part of the image")
        if self.points and self.error_status != GOOD:
            out.append(f"error {self.rms_px:.2f} px — check the images that cover "
                       f"this area (blur, motion, a bent or lifted board)")
        if self.points and self.tilt_status != GOOD:
            out.append(f"board angles vary by only {self.tilt_spread_deg:.0f}° — "
                       f"tilt the board more (up/down and left/right) here")
        return out


@dataclass
class GridReport:
    cells: list = field(default_factory=list)     # [row][col] -> GridCell
    image_size: tuple = (0, 0)

    @property
    def flat(self) -> list[GridCell]:
        return [c for row in self.cells for c in row]

    @property
    def worst_status(self) -> str:
        return max((c.status for c in self.flat), key=_RANK.__getitem__, default=POOR)

    def count(self, status: str) -> int:
        return sum(c.status == status for c in self.flat)

    def advice(self) -> list[str]:
        """One line per non-green area, worst first."""
        cells = sorted((c for c in self.flat if c.status != GOOD),
                       key=lambda c: -_RANK[c.status])
        return [f"{c.name} ({c.status}): " + "; ".join(c.problems()) for c in cells]


def _rate_high_good(v: float, good: float, poor: float) -> str:
    return GOOD if v >= good else (POOR if v < poor else WEAK)


def _rate_low_good(v: float, good: float, poor: float) -> str:
    if math.isnan(v):
        return POOR
    return GOOD if v < good else (POOR if v > poor else WEAK)


def _max_pair_angle_deg(normals: list[np.ndarray]) -> float:
    if len(normals) < 2:
        return 0.0
    n = np.asarray(normals)
    c = np.clip(n @ n.T, -1.0, 1.0)
    return float(np.degrees(np.arccos(c.min())))


def compute_grid(cal_result) -> GridReport:
    """Build the 3 x 3 grid from a CalibrationResult (needs points_used)."""
    w, h = cal_result.image_size
    sq = [[[] for _ in range(GRID_N)] for _ in range(GRID_N)]      # residuals
    views = [[[] for _ in range(GRID_N)] for _ in range(GRID_N)]   # board normals
    imgs = [[0] * GRID_N for _ in range(GRID_N)]

    for (path, obj, img), rv, tv in zip(cal_result.points_used,
                                        cal_result.rvecs, cal_result.tvecs):
        proj, _ = cv2.projectPoints(obj.reshape(-1, 1, 3), rv, tv,
                                    cal_result.camera_matrix, cal_result.dist_coeffs)
        res = np.linalg.norm(proj.reshape(-1, 2) - img, axis=1)
        R, _ = cv2.Rodrigues(rv)
        normal = R[:, 2] / np.linalg.norm(R[:, 2])
        col = np.clip((img[:, 0] * GRID_N / w).astype(int), 0, GRID_N - 1)
        row = np.clip((img[:, 1] * GRID_N / h).astype(int), 0, GRID_N - 1)
        for r in range(GRID_N):
            for c in range(GRID_N):
                m = (row == r) & (col == c)
                k = int(m.sum())
                if k == 0:
                    continue
                sq[r][c].extend(res[m].tolist())
                imgs[r][c] += 1
                if k >= MIN_POINTS_PER_VIEW:
                    views[r][c].append(normal)

    report = GridReport(image_size=(w, h))
    for r in range(GRID_N):
        row_cells = []
        for c in range(GRID_N):
            e = np.asarray(sq[r][c])
            cell = GridCell(row=r, col=c, points=len(e), images=imgs[r][c],
                            rms_px=float(np.sqrt(np.mean(e ** 2))) if len(e) else math.nan,
                            tilt_spread_deg=_max_pair_angle_deg(views[r][c]))
            cell.points_status = _rate_high_good(cell.points, POINTS_GOOD, POINTS_POOR)
            cell.error_status = _rate_low_good(cell.rms_px, ERROR_GOOD_PX, ERROR_POOR_PX)
            cell.tilt_status = _rate_high_good(cell.tilt_spread_deg, TILT_GOOD_DEG, TILT_POOR_DEG)
            # Colour = points and tilt only (2026-11-03): the pixel error is shown, but it
            # did not predict real error and blur / 4K inflate it.
            cell.status = max((cell.points_status, cell.tilt_status),
                              key=_RANK.__getitem__)
            row_cells.append(cell)
        report.cells.append(row_cells)
    return report


def limits_text() -> str:
    """One-line legend of the limits, for the GUI and PDF."""
    return (f"Green = >= {POINTS_GOOD} points and board angles vary >= {TILT_GOOD_DEG:g}°.  "
            f"Red = < {POINTS_POOR} points or angles vary < {TILT_POOR_DEG:g}°.  Yellow = in between.  "
            f"The error (px) in each square is shown for information only.")
