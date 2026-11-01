"""dot_detector.py — Find and identify the dots of a random-dot board.

Two steps per image:
  1. detect_blobs(): dark round blobs -> ellipse centres (adaptive threshold,
     contour circularity >= 0.8, cv2.fitEllipse centre).
  2. match_dots(): work out which blob is which board dot.  Every triple of
     neighbouring board dots is tried against every triple of neighbouring
     blobs (affine seed), the best seeds are refined to a homography with
     mutual-nearest-neighbour matching, and the seed with the most matches wins.

Random layouts make every local triple unique, so a wrong seed matches only a
few dots while the right one matches most of the visible board.

Pass K and D (from a first calibration) to match on undistorted points: the
board is then exactly a homography and the tolerance can be tight.  The
calibrator does this second pass automatically (src/calibrator.py).

Ellipse centres are not exactly the projected circle centres when the board is
tilted (perspective bias, well under 1 px for these boards at 1-1.5 m); this
is accepted, as in the 2026-10-08 AranSW1 calibrations.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Blob columns: x, y, ellipse major axis, minor axis, area (all pixels)
_REF_WIDTH = 2880.0            # tuned on the 2880 x 1860 LUCID images
_MIN_CIRCULARITY = 0.8
_N_SEEDS = 40                  # affine seeds refined to a homography
_MIN_MATCHES = 8               # fewer than this = board not found


@dataclass
class DotMatch:
    ids: np.ndarray            # (M,) board dot ids
    image_points: np.ndarray   # (M, 2) blob centres in the original image (px)
    n_blobs: int               # blobs found in the image
    rms_px: float              # fit of the matches to the board homography


def detect_blobs(gray: np.ndarray) -> np.ndarray:
    """Dark round blobs in a grey image.  Returns (N, 5): x, y, MA, ma, area."""
    h, w = gray.shape[:2]
    s = w / _REF_WIDTH
    block = max(31, int(301 * s) | 1)                  # odd, ~10% of width
    min_area = max(30.0, 300.0 * s * s)
    max_area = 0.05 * w * h
    b = cv2.GaussianBlur(gray, (5, 5), 0)
    th = cv2.adaptiveThreshold(b, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, block, 25)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in contours:
        a = cv2.contourArea(c)
        if a < min_area or a > max_area or len(c) < 20:
            continue
        p = cv2.arcLength(c, True)
        if p <= 0 or 4 * np.pi * a / (p * p) < _MIN_CIRCULARITY:
            continue
        (x, y), (ma1, ma2), _ = cv2.fitEllipse(c)
        out.append((x, y, max(ma1, ma2), min(ma1, ma2), a))
    return np.array(out, dtype=np.float64).reshape(-1, 5)


def _nn(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each row of a, distance to and index of the nearest row of b."""
    d = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    i = d.argmin(1)
    return d[np.arange(len(a)), i], i


def _knn_idx(a: np.ndarray, k: int) -> np.ndarray:
    d = np.linalg.norm(a[:, None, :] - a[None, :, :], axis=2)
    return np.argsort(d, axis=1)[:, :k]


def _affine_seeds(P: np.ndarray, q: np.ndarray, tol: float) -> list:
    """Score every board-triple -> blob-triple affine map; return best few."""
    pn = _knn_idx(P, 3)                                 # (nP, 3) self + 2 NN
    qn = _knn_idx(q, 3)
    Bt = np.concatenate([q[qn], q[qn[:, [0, 2, 1]]]])   # (2nQ, 3, 2)
    Ph = np.c_[P, np.ones(len(P))]                      # (nP, 3)
    scored = []
    for i in range(len(P)):
        A = Ph[pn[i]]                                   # (3, 3)
        if abs(np.linalg.det(A)) < 1e-9:
            continue
        X = np.linalg.solve(A, Bt)                      # (2nQ, 3, 2)
        m = np.einsum("pk,ckd->cpd", Ph, X)             # (2nQ, nP, 2)
        d = np.sqrt(((m[:, :, None, :] - q[None, None, :, :]) ** 2).sum(-1)).min(-1)
        n = (d < tol).sum(1)
        for c in np.argsort(-n)[:4]:
            scored.append((int(n[c]), X[c]))
    scored.sort(key=lambda s: -s[0])
    return scored[:_N_SEEDS]


def match_dots(blobs: np.ndarray, board_xy_mm: np.ndarray,
               K: np.ndarray | None = None, D: np.ndarray | None = None,
               image_size: tuple[int, int] | None = None,
               ) -> DotMatch | None:
    """Identify board dots among the blobs.  None if the board is not found.

    image_size (w, h): when given, at least half of the board dots that the
    fitted homography puts inside the image must be matched.  This rejects a
    wrong board, which typically matches only ~20% of its dots by chance.
    """
    if len(blobs) < _MIN_MATCHES:
        return None
    P = np.asarray(board_xy_mm, dtype=np.float64)
    xy = blobs[:, :2].astype(np.float64)
    if K is not None:
        q = cv2.undistortPoints(xy[:, None, :], K, D, P=K)[:, 0]
        final_k = 0.12
    else:
        q = xy
        final_k = 0.25                 # lens distortion not yet removed
    size = float(np.median(np.sqrt(blobs[:, 2] * blobs[:, 3])))

    best = None
    for n0, X in _affine_seeds(P, q, 0.25 * size):
        if n0 < 4:
            break
        H = np.vstack([X.T, [0, 0, 1]])
        for _ in range(8):
            m = cv2.perspectiveTransform(P[None], H)[0]
            dd, ii = _nn(m, q)
            _, back = _nn(q, m)
            sel = (dd < 0.35 * size) & (back[ii] == np.arange(len(P)))
            if sel.sum() < 6:
                break
            Hn, _ = cv2.findHomography(P[sel], q[ii[sel]], 0)
            if Hn is None:
                break
            H = Hn
        m = cv2.perspectiveTransform(P[None], H)[0]
        dd, ii = _nn(m, q)
        _, back = _nn(q, m)
        sel = (dd < final_k * size) & (back[ii] == np.arange(len(P)))
        if best is None or sel.sum() > best[0]:
            best = (int(sel.sum()), sel, ii, dd, H)
    if best is None or best[0] < _MIN_MATCHES:
        return None
    _, sel, ii, dd, H = best
    if image_size is not None:
        m = cv2.perspectiveTransform(P[None], H)[0]
        w, h = image_size
        vis = int(((m[:, 0] >= 0) & (m[:, 0] < w) & (m[:, 1] >= 0) & (m[:, 1] < h)).sum())
        if sel.sum() < 0.5 * vis:
            return None
    ids = np.nonzero(sel)[0]
    return DotMatch(ids=ids, image_points=xy[ii[sel]],
                    n_blobs=len(blobs), rms_px=float(np.sqrt(np.mean(dd[sel] ** 2))))


def rematch_dots(blobs: np.ndarray, board_xy_mm: np.ndarray, prev: DotMatch,
                 K: np.ndarray, D: np.ndarray) -> DotMatch | None:
    """Second pass: re-identify dots on undistorted points, starting from a
    first-pass match (no seed search, so it is fast).  Picks up edge dots
    that lens distortion hid from the first pass."""
    P = np.asarray(board_xy_mm, dtype=np.float64)
    xy = blobs[:, :2].astype(np.float64)
    q = cv2.undistortPoints(xy[:, None, :], K, D, P=K)[:, 0]
    qp = cv2.undistortPoints(prev.image_points[:, None, :].astype(np.float64),
                             K, D, P=K)[:, 0]
    H, _ = cv2.findHomography(P[prev.ids], qp, 0)
    if H is None:
        return None
    size = float(np.median(np.sqrt(blobs[:, 2] * blobs[:, 3])))
    for tol in (0.35, 0.2, 0.12, 0.12):
        m = cv2.perspectiveTransform(P[None], H)[0]
        dd, ii = _nn(m, q)
        _, back = _nn(q, m)
        sel = (dd < tol * size) & (back[ii] == np.arange(len(P)))
        if sel.sum() < _MIN_MATCHES:
            return None
        H, _ = cv2.findHomography(P[sel], q[ii[sel]], 0)
        if H is None:
            return None
    ids = np.nonzero(sel)[0]
    return DotMatch(ids=ids, image_points=xy[ii[sel]], n_blobs=len(blobs),
                    rms_px=float(np.sqrt(np.mean(dd[sel] ** 2))))


def edge_blur_px(gray: np.ndarray, points: np.ndarray, blobs: np.ndarray) -> float:
    """How blurry the dots' edges are: Gaussian blur sigma in pixels (median over dots).

    For a blurred black/white edge the steepest slope is contrast / (sigma*sqrt(2 pi)),
    so sigma = contrast / (sqrt(2 pi) * steepest slope).  Works on any edge direction,
    so tilted (elliptical) dots are fine.  Sharp photos give about 0.7-1.2 px.
    NaN if no dot could be measured.
    """
    if points is None or len(points) == 0 or blobs is None or len(blobs) == 0:
        return float("nan")
    g = gray.astype(np.float32)
    h, w = g.shape[:2]
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    mag = np.hypot(gx, gy)
    pts = np.asarray(points, np.float64).reshape(-1, 2)
    _, bi = _nn(pts, blobs[:, :2])
    sig = []
    for (x, y), k in zip(pts, bi):
        r = 0.25 * (blobs[k, 2] + blobs[k, 3])          # mean semi-axis
        R = int(np.ceil(1.7 * blobs[k, 2] / 2)) + 2
        x0, x1, y0, y1 = int(x) - R, int(x) + R + 1, int(y) - R, int(y) + R + 1
        if r < 5 or x0 < 0 or y0 < 0 or x1 > w or y1 > h:
            continue                                     # too small or cut by the frame
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d = np.hypot(xx - x, yy - y) / r
        patch, m = g[y0:y1, x0:x1], mag[y0:y1, x0:x1]
        inside = np.median(patch[d < 0.5])
        outside = np.median(patch[(d > 1.4) & (d < 1.7)])
        contrast = outside - inside
        ring = m[(d > 0.6) & (d < 1.4)]
        if contrast < 30 or ring.size < 20:
            continue
        slope = np.percentile(ring, 95)
        if slope > 0:
            sig.append(contrast / (np.sqrt(2 * np.pi) * slope))
    return float(np.median(sig)) if sig else float("nan")
