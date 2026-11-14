"""marker_finder.py - a finder made for the 12x8 chessboard with hollow corner markers.

Derek, 2026-11-14: "each board can have its own finder if that would make it better".
OpenCV's chessboard finders miss about half of the GOX photos of this board, even clean,
flat, fully visible ones.  This board has a marker in each of its four corner cells: the
cell is solid dark with a centred white hole 45 % of the cell wide (ground truth:
Cal_board/Chessboard_12x8/generate_board_plain.py, the faithful copy of the physical board).

How it works:
  1. Find the four holes: a white four-sided blob whose surrounding ring (1.55 x its size)
     is dark all the way round.  (A white chessboard square fails: its diagonal neighbours
     are white.)
  2. The four hole centres are the centres of the four corner cells.  Order them round the
     board, and for each of the four ways they could match the board's corners, map the
     board into the picture (homography) and predict every inside corner.
  3. Pull each predicted corner onto the real corner with cornerSubPix (search window about
     a quarter of a square).
  4. Keep the answer only if the corners form a smooth grid: each corner sits close to the
     middle of its two neighbours along the row and along the column.  A wrong match or a
     corner pulled onto the wrong edge breaks that and the photo counts as "not found".
  5. The 4 corners that touch a marker cell are left out (see outer_ids); the other 73
     agreed with OpenCV's SB finder to a median 0.001 px on 71 GOX photos both could read.
Checked 2026-11-14 on 166 GOX photos (3840x2160) in the real calibration app:
  50 timer photos: 38 used instead of 25, lens steady 2.4 mm (SB only: 3.9 mm), PASS;
  95 photos: 38 used instead of 31, lens steady 4.7 mm (SB only: 3.3 mm), PASS;
  21 photos: all read by SB already, unchanged.
"Lens steady" swings 2.4-5.5 mm on the same 50 photos with which few are in, so it cannot
judge this; the corner accuracy above (0.001 px median against SB) is the real check.
A stricter grid check (3 %) found almost nothing extra; 6 % kept.
Used by src/detector.py only after the usual finders miss, and only for boards whose
board.yaml says  finder: corner_markers  (or the original 12x8 board, see src/boards.py).
"""

from __future__ import annotations

from itertools import combinations

import cv2
import numpy as np

HOLE_RATIO = 0.45          # white hole width / cell width (ground truth)
RING_SCALE = 1.55          # ring around the hole that must be dark (inside the marker cell)
SEARCH_W = 1280            # markers are looked for on a copy this wide
SMOOTH_FRAC = 0.06         # a corner may sit at most this x square size off its neighbours' middle
_CRIT = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001)


def _binaries(gray_small: np.ndarray):
    """Black/white versions to look for holes in.  The patch must be bigger than a board
    square, or the inside of every black square turns white and looks like a hole."""
    _, otsu = cv2.threshold(gray_small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield otsu
    w = gray_small.shape[1]
    yield cv2.adaptiveThreshold(gray_small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, (w // 6) | 1, 0)


def _holes(gray_small: np.ndarray) -> list[tuple[np.ndarray, float]]:
    """Candidate marker holes on the small copy: (centre xy, hole size px).  Tries each
    black/white version; returns the first that gives 4 to 10 candidates."""
    found = []
    for binary in _binaries(gray_small):
        found = _holes_in(binary)
        if 4 <= len(found) <= 10:
            return found
    return found


def _holes_in(binary: np.ndarray) -> list[tuple[np.ndarray, float]]:
    h, w = binary.shape
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        a = cv2.contourArea(c)
        if a < 30 or a > 0.01 * w * h:
            continue
        q = cv2.approxPolyDP(c, 0.06 * cv2.arcLength(c, True), True).reshape(-1, 2).astype(float)
        if len(q) != 4 or not cv2.isContourConvex(q.astype(np.int32).reshape(-1, 1, 2)):
            continue
        sides = np.linalg.norm(q - np.roll(q, 1, 0), axis=1)
        if sides.max() > 3.0 * sides.min():
            continue
        ctr = q.mean(0)
        ring = []
        for i in range(4):                       # 4 points along each side of the ring, corners included
            p0, p1 = ctr + RING_SCALE * (q[i] - ctr), ctr + RING_SCALE * (q[(i + 1) % 4] - ctr)
            ring += [p0 + t * (p1 - p0) for t in (0.0, 0.25, 0.5, 0.75)]
        ring = np.rint(np.array(ring)).astype(int)
        inside = (ring[:, 0] >= 0) & (ring[:, 1] >= 0) & (ring[:, 0] < w) & (ring[:, 1] < h)
        if inside.sum() < 10:                          # a marker cut by the picture edge may still count
            continue
        r = ring[inside]
        dark = int((binary[r[:, 1], r[:, 0]] == 0).sum())
        if dark >= inside.sum() - 1:
            out.append((ctr, float(np.sqrt(a))))
    return out


def outer_ids(squares_x: int, squares_y: int) -> set[int]:
    """The 4 inside corners that touch a marker cell.  On the physical board the marker sits
    where a white square would be, so these corners have three dark squares round them, not
    a true chessboard corner; finders disagree on them by up to ~20 px.  Left out."""
    cols, rows = squares_x - 1, squares_y - 1
    return {0, cols - 1, (rows - 1) * cols, rows * cols - 1}


def _order(pts: np.ndarray) -> np.ndarray:
    """Round the centre, in increasing angle (clockwise on screen: y points down)."""
    c = pts.mean(0)
    return pts[np.argsort(np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0]))]


def _smooth_error(grid: np.ndarray) -> float:
    """Worst distance of a corner from the middle of its two neighbours (row or column), px."""
    e = 0.0
    if grid.shape[1] >= 3:
        e = max(e, float(np.linalg.norm(grid[:, :-2] + grid[:, 2:] - 2 * grid[:, 1:-1], axis=2).max()) / 2)
    if grid.shape[0] >= 3:
        e = max(e, float(np.linalg.norm(grid[:-2] + grid[2:] - 2 * grid[1:-1], axis=2).max()) / 2)
    return e


def _predict(board_pts, img_pts, lattice, rows, cols, three: bool):
    if three:
        A = cv2.getAffineTransform(board_pts, img_pts)
        return (lattice @ A[:, :2].T + A[:, 2]).reshape(rows, cols, 2)
    Hm = cv2.getPerspectiveTransform(board_pts, img_pts)
    return cv2.perspectiveTransform(lattice.reshape(-1, 1, 2), Hm).reshape(rows, cols, 2)


def _cell(grid) -> float:
    return float(np.median(np.linalg.norm(np.diff(grid, axis=1), axis=2)))


def _inside(grid, W, H) -> bool:
    return not ((grid < 0).any() or (grid[..., 0] > W - 1).any() or (grid[..., 1] > H - 1).any())


def _refine(gray, pred, lattice, rows, cols):
    """Pull the predicted corners onto the real ones, refit a homography to them, repeat.
    (grid, smoothness error, cell) or None."""
    H, W = gray.shape[:2]
    grid = moved = cell = None
    for _pass in range(3):
        if not _inside(pred, W, H):
            return None                                # the whole grid must be in the picture
        cell = _cell(pred)
        if cell < 6:
            return None
        win = int(np.clip(0.22 * cell, 3, 60))
        ref = cv2.cornerSubPix(gray, pred.reshape(-1, 1, 2).astype(np.float32).copy(), (win, win), (-1, -1), _CRIT)
        grid = ref.reshape(rows, cols, 2)
        moved = np.linalg.norm(grid - pred, axis=2)
        good = moved.ravel() < 0.3 * cell
        if good.sum() < 0.6 * rows * cols:
            return None
        Hm, _ = cv2.findHomography(lattice[good], ref.reshape(-1, 2)[good], cv2.RANSAC, max(1.0, 0.05 * cell))
        if Hm is None:
            return None
        new_pred = cv2.perspectiveTransform(lattice.reshape(-1, 1, 2), Hm).reshape(rows, cols, 2)
        if float(np.abs(new_pred - pred).max()) < 0.5 and good.all():
            break
        pred = new_pred
    err = _smooth_error(grid)
    if float(moved.max()) > 0.3 * cell or err > SMOOTH_FRAC * cell:
        return None
    return grid, err, cell


def find_marker_corners(gray: np.ndarray, squares_x: int, squares_y: int):
    """(corners (N, 1, 2) float32, ids (N,)) in full-size pixels, or (None, None).
    Needs 3 or 4 of the corner markers; all inside corners must be in the picture.
    The search runs on a 1280 px copy; only the winner is refined on the full picture."""
    H, W = gray.shape[:2]
    s = min(1.0, SEARCH_W / W)
    small = cv2.resize(gray, (int(round(W * s)), int(round(H * s))), interpolation=cv2.INTER_AREA) if s < 1 else gray
    cands = _holes(small)
    if len(cands) < 3 or len(cands) > 10:
        return None, None
    cols, rows = squares_x - 1, squares_y - 1
    board = np.array([[0.5, 0.5], [squares_x - 0.5, 0.5], [squares_x - 0.5, squares_y - 0.5], [0.5, squares_y - 0.5]], np.float32)
    lattice = np.array([[c, r] for r in range(1, squares_y) for c in range(1, squares_x)], np.float32)
    best = None
    for n in (4, 3):
        for pick in combinations(range(len(cands)), n):
            pts = np.array([cands[i][0] for i in pick], np.float32)            # small-copy pixels
            sizes = np.array([cands[i][1] for i in pick])
            if sizes.max() > 3.0 * sizes.min():
                continue
            ordered = _order(pts).astype(np.float32)
            for j in (range(n) if n == 3 else (0,)):     # 3 markers: any of them may start the run
                img = np.ascontiguousarray(np.roll(ordered, -j, axis=0))
                for k in range(4):
                    b = np.ascontiguousarray(np.roll(board, -k, axis=0)[:n])   # board corners, same turning order
                    pred = _predict(b, img, lattice, rows, cols, three=(n == 3))
                    if not _inside(pred, small.shape[1], small.shape[0]):
                        continue
                    if not (0.25 < np.median(sizes) / max(_cell(pred), 1e-6) < 0.75):   # hole ~0.45 of a square
                        continue
                    r = _refine(small, pred, lattice, rows, cols)
                    if r is not None and (best is None or r[1] < best[0]):
                        best = (r[1], r[0])
        if best is not None:
            break
    if best is None:
        return None, None
    full = _refine(gray, best[1] / s, lattice, rows, cols)          # once, on the full-size picture
    if full is None:
        return None, None
    keep = np.array([i for i in range(cols * rows) if i not in outer_ids(squares_x, squares_y)])
    return np.ascontiguousarray(full[0].reshape(-1, 1, 2)[keep]).astype(np.float32), keep
