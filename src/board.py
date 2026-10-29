"""board.py — Board configuration and 3D object point generation.

Defines the physical properties of the 12×8 board and builds the 3D object
point array used by cv2.calibrateCamera.  Points are built with separate X
and Y spacing so a non-square board would also work; the current board is
square (see the cell-size note below).

The printed board carries DICT_5X5_50 ArUco markers, but detection does not
use them — src/detector.py treats the board as a plain chessboard.
get_charuco_board() below is retained for tooling/debugging only and is not
called anywhere in the calibration path.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# Physical cell size: MEASURED, not nominal.
#
# The board was measured with digital calipers on 2026-08-18 (Derek):
#   two squares, same edge to same edge : 152.78 mm  ->  76.39 mm per cell
#   one square, its own width           :  76.59 mm  (0.20 mm of ink spread)
# Spanning two cells puts both jaws on the same white->grey edge, so the ink
# spread cancels; a single-square reading does not and comes out 0.20 mm large.
# Full method and evidence: references/BoardTrueSize.md.
#
# 76.39 mm = 3.0075" — the board was printed 0.25% over its nominal 3.000".
# The earlier 76.2 (= 3.000" x 25.4) was the assumed nominal, never measured.
#
# Cells are square: width and height must stay equal.  Only the width/height
# RATIO reaches the intrinsics — a uniform scale error has no effect on fx, fy,
# cx, cy or the distortion coefficients (tested; see BoardTrueSize.md §3).  So
# moving 76.2 -> 76.39 changes no calibration output.  It is done because the
# app should state what was measured rather than what was assumed.
#
# History: non-square 76.46 x 75.99 mm, derived from an overall
# 36.125" x 23.9375" measurement, is SUPERSEDED (fx/fy 0.994 vs 0.9998).
# See references/CalibrationBoard.txt.
_CELL_PITCH_MM = 76.39          # [measured] calipers 2026-08-18
_CELL_PITCH_IN = 3.0075         # = 76.39 / 25.4, for reference only

DEFAULT_SQUARES_X: int = 12
DEFAULT_SQUARES_Y: int = 8
DEFAULT_CELL_WIDTH_MM: float = _CELL_PITCH_MM
DEFAULT_CELL_HEIGHT_MM: float = _CELL_PITCH_MM
DEFAULT_MARKER_SIZE_MM: float = 60.0                # measure from printed board
DEFAULT_ARUCO_DICT: str = "DICT_5X5_50"

# Board kinds.  A chessboard is found by its corner grid; a dot board is a
# random-dot layout read from a CSV (see src/dot_detector.py).
KIND_CHESSBOARD: str = "chessboard"
KIND_DOTS: str = "dots"
DEFAULT_BOARD_NAME: str = "Chessboard 12x8"


def load_dot_layout(csv_path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a random-dot layout CSV.

    Format (space separated, metres, one dot per line):
        0  id  x  0  z  0  -1  0  radius
    x = right, z = up, origin = board centre.

    Returns (xy_mm, radius_mm): xy_mm is (N, 2) in board coordinates with
    X = x and Y = -z (Y down, so the board's Z axis points into the board,
    like the chessboard's), both in mm, ordered by dot id.
    """
    rows = []
    with open(csv_path, encoding="utf-8-sig") as fh:
        for line in fh:
            v = line.replace(",", " ").split()
            if len(v) >= 9:
                rows.append([float(x) for x in v[:9]])
    if len(rows) < 6:
        raise ValueError(f"Dot layout {csv_path} has only {len(rows)} dots.")
    a = np.array(rows, dtype=np.float64)
    a = a[np.argsort(a[:, 1], kind="stable")]
    xy = np.c_[a[:, 2], -a[:, 4]] * 1000.0
    return xy, a[:, 8] * 1000.0


@dataclass
class BoardConfig:
    """All physical and logical parameters that describe the calibration board."""

    squares_x: int = DEFAULT_SQUARES_X
    squares_y: int = DEFAULT_SQUARES_Y
    cell_width_mm: float = DEFAULT_CELL_WIDTH_MM
    cell_height_mm: float = DEFAULT_CELL_HEIGHT_MM
    marker_size_mm: float = DEFAULT_MARKER_SIZE_MM
    aruco_dict_name: str = DEFAULT_ARUCO_DICT
    # Which board.  Defaults describe the 12x8 chessboard, so every existing
    # BoardConfig(...) call keeps working unchanged.
    kind: str = KIND_CHESSBOARD
    name: str = DEFAULT_BOARD_NAME
    folder: str = ""                 # Cal_board/<board> folder, if any
    layout_csv: str = ""             # dot boards: layout CSV path
    label: str = ""                  # text printed on the board, if any
    dot_xy_mm: Optional[np.ndarray] = field(default=None, repr=False)
    dot_radius_mm: Optional[np.ndarray] = field(default=None, repr=False)

    @property
    def is_dots(self) -> bool:
        return self.kind == KIND_DOTS

    @classmethod
    def from_dot_csv(cls, csv_path: str | Path, name: str = "",
                     label: str = "", folder: str = "") -> "BoardConfig":
        """Build a dot-board config from its layout CSV."""
        xy, r = load_dot_layout(csv_path)
        return cls(kind=KIND_DOTS, name=name or Path(csv_path).stem,
                   folder=str(folder), layout_csv=str(csv_path), label=label,
                   dot_xy_mm=xy, dot_radius_mm=r)

    @property
    def num_corners(self) -> int:
        """Number of board points: chessboard interior corners, or dots."""
        if self.is_dots:
            return 0 if self.dot_xy_mm is None else len(self.dot_xy_mm)
        return (self.squares_x - 1) * (self.squares_y - 1)

    def get_aruco_dict(self) -> cv2.aruco.Dictionary:
        dict_id = getattr(cv2.aruco, self.aruco_dict_name)
        return cv2.aruco.getPredefinedDictionary(dict_id)

    def get_charuco_board(self) -> cv2.aruco.CharucoBoard:
        """Create the cv2 CharucoBoard object.

        NOT USED BY THE CALIBRATION PATH — retained for tooling and debugging
        (e.g. regenerating a printable board).  Detection is plain chessboard
        via src/detector.py; calibration uses get_all_object_points().

        cell_width_mm is passed as the nominal squareLength.
        """
        return cv2.aruco.CharucoBoard(
            (self.squares_x, self.squares_y),
            float(self.cell_width_mm),
            float(self.marker_size_mm),
            self.get_aruco_dict(),
        )

    def get_all_object_points(self) -> np.ndarray:
        """Return the 3D world coordinates for every interior corner.

        Corner ID assignment (row-major, matching detector.py's ID order):
            ID = row * (squares_x - 1) + col
            where col ∈ [0, squares_x-2], row ∈ [0, squares_y-2]

        Coordinate mapping (separate X/Y spacing, so non-square works too):
            X = col * cell_width_mm
            Y = row * cell_height_mm
            Z = 0

        Indexing by corner ID gives the correct object point for that ID,
        which is the key step in pairing detected 2D corners with their 3D
        positions when calling cv2.calibrateCamera.

        Returns
        -------
        np.ndarray, shape (num_corners, 3), dtype float32

        Dot boards: one point per dot centre, indexed by dot id, Z = 0.
        """
        if self.is_dots:
            pts = np.zeros((self.num_corners, 3), dtype=np.float32)
            pts[:, :2] = self.dot_xy_mm
            return pts
        n_cols = self.squares_x - 1
        n_rows = self.squares_y - 1
        pts = np.zeros((n_rows * n_cols, 3), dtype=np.float32)
        for row in range(n_rows):
            for col in range(n_cols):
                idx = row * n_cols + col
                pts[idx, 0] = col * self.cell_width_mm
                pts[idx, 1] = row * self.cell_height_mm
                # pts[idx, 2] remains 0.0 (flat board)
        return pts
