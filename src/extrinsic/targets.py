"""targets.py — find the Old School targets in a photo and work out which is which.

Wall targets: dark discs (some with a white cross) on the light wall.
Ground targets: tennis balls (yellow-green) on the pavement.

Which target is which comes from a predicted camera pose (the camera's place on the
van from another setup, moved by this setup's van position and attitude).  The
predicted target positions are shifted to line up with the found blobs (vote on the
shift), matched, solved, and matched again tighter.  Targets not found in the first
pass are looked for again in a small window around where they should be.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

WALL_BLOCK, WALL_C, WALL_MIN_AREA, WALL_MIN_CIRC = 61, 25, 10.0, 0.35


def detect_wall(gray: np.ndarray) -> np.ndarray:
    """Dark round blobs: (N, 3) x, y, diameter px."""
    h, w = gray.shape[:2]
    sc = w / 1920.0                       # tuned on 1920 x 1080; scaled for 4K
    blk = max(15, int(WALL_BLOCK * sc) | 1)
    b = cv2.GaussianBlur(gray, (3, 3), 0)
    th = cv2.adaptiveThreshold(b, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, blk, WALL_C)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cs:
        a = cv2.contourArea(c)
        if a < WALL_MIN_AREA * sc * sc or a > 0.01 * w * h or len(c) < 6:
            continue
        p = cv2.arcLength(c, True)
        if p <= 0 or 4 * np.pi * a / (p * p) < WALL_MIN_CIRC:
            continue
        if len(c) >= 20:
            (x, y), (d1, d2), _ = cv2.fitEllipse(c)
            d = float(np.sqrt(max(d1, 1) * max(d2, 1)))
        else:
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            x, y, d = M["m10"] / M["m00"], M["m01"] / M["m00"], 2 * np.sqrt(a / np.pi)
        out.append((x, y, d))
    return np.array(out, float).reshape(-1, 3)


def detect_balls(bgr: np.ndarray) -> np.ndarray:
    """Tennis balls: (N, 3) x, y, diameter px."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (22, 70, 110), (50, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m)
    out = []
    for i in range(1, n):
        a, bw, bh = st[i, 4], st[i, 2], st[i, 3]
        sc2 = (bgr.shape[1] / 1920.0) ** 2
        if 4 * sc2 <= a <= 2500 * sc2 and max(bw, bh) <= 3 * min(bw, bh) + 2:
            out.append((cen[i][0], cen[i][1], 2 * np.sqrt(a / np.pi)))
    return np.array(out, float).reshape(-1, 3)


def _local_wall(gray, x, y, r=18):
    """Look again for a dark blob near (x, y) with a local threshold.  None if none."""
    h, w = gray.shape[:2]
    x0, x1, y0, y1 = int(x) - r, int(x) + r + 1, int(y) - r, int(y) + r + 1
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    patch = cv2.GaussianBlur(gray[y0:y1, x0:x1], (3, 3), 0)
    t = (int(np.percentile(patch, 90)) + int(patch.min())) // 2
    _, th = cv2.threshold(patch, t, 255, cv2.THRESH_BINARY_INV)
    n, lab, st, cen = cv2.connectedComponentsWithStats(th)
    best = None
    for i in range(1, n):
        if st[i, 4] < 4 or st[i, 4] > 0.6 * th.size:
            continue
        cx, cy = cen[i]
        d = np.hypot(cx - r, cy - r)
        if d < r * 0.6 and (best is None or d < best[0]):
            best = (d, cx + x0, cy + y0)
    return None if best is None else (best[1], best[2])


@dataclass
class MatchResult:
    matches: list = field(default_factory=list)      # (id, x, y, kind) kind: 'wall' | 'ball'
    blobs_wall: np.ndarray = None
    blobs_ball: np.ndarray = None
    predicted: dict = field(default_factory=dict)    # id -> (x, y) from the final pose
    rvec: np.ndarray = None
    tvec: np.ndarray = None
    note: str = ""


def _project(site, rvec, tvec, K, D, size):
    o = site.enh_m[0]
    P = site.enh_m - o
    R, _ = cv2.Rodrigues(rvec)
    zc = (R @ P.T + tvec.reshape(3, 1))[2]
    pr, _ = cv2.projectPoints(P, rvec, tvec, K, D)
    pr = pr.reshape(-1, 2)
    w, h = size
    vis = (zc > 0.5) & (pr[:, 0] > -20) & (pr[:, 0] < w + 20) & (pr[:, 1] > -20) & (pr[:, 1] < h + 20)
    return pr, vis


def _assign(pred, vis, ground, wall, balls, tol):
    """Nearest blob of the right kind within tol, one to one."""
    pairs = []
    for i in np.nonzero(vis)[0]:
        B = balls if ground[i] else wall
        if len(B) == 0:
            continue
        d = np.hypot(B[:, 0] - pred[i, 0], B[:, 1] - pred[i, 1])
        j = int(np.argmin(d))
        if d[j] < tol:
            pairs.append((d[j], i, j, bool(ground[i])))
    pairs.sort()
    used, out = set(), []
    for d, i, j, g in pairs:
        if (g, j) in used:
            continue
        used.add((g, j)); out.append((i, j, g))
    return out


def match_targets(bgr, site, K, D, rvec0, tvec0) -> MatchResult:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    sc = w / 1920.0
    res = MatchResult(blobs_wall=detect_wall(gray), blobs_ball=detect_balls(bgr))
    W, Bl = res.blobs_wall, res.blobs_ball
    pred, vis = _project(site, rvec0, tvec0, K, D, (w, h))
    if vis.sum() < 4:
        res.note = "the predicted view shows almost no targets"; return res
    # 1. vote on the image shift between prediction and blobs (GPS / van pose error)
    # Cameras on different vans point up to ~10 deg apart, so search a wide window.
    reach = 0.45 * w
    offs = []
    for i in np.nonzero(vis)[0]:
        B = Bl if site.ground[i] else W
        if len(B):
            dd = B[:, :2] - pred[i]
            offs.append(dd[np.hypot(dd[:, 0], dd[:, 1]) < reach])
    offs = np.vstack(offs) if offs else np.zeros((0, 2))
    if len(offs) == 0:
        res.note = "no blobs near the predicted targets"; return res
    nb = int(2 * reach / (10 * sc))
    H, xe, ye = np.histogram2d(offs[:, 0], offs[:, 1], bins=nb, range=[[-reach, reach], [-reach, reach]])
    H = cv2.GaussianBlur(H.astype(np.float32), (5, 5), 1.0)
    ix, iy = np.unravel_index(int(np.argmax(H)), H.shape)
    shift = np.array([(xe[ix] + xe[ix + 1]) / 2, (ye[iy] + ye[iy + 1]) / 2])
    o = site.enh_m[0]
    G = site.enh_m - o
    rv, tv = rvec0.copy(), tvec0.copy()
    cur = pred + shift
    # 1b. the van's GPS error also changes the range (scale) and turn: fit a 2D
    #     similarity on candidate pairs with RANSAC and apply it to the prediction
    src, dst = [], []
    for i in np.nonzero(vis)[0]:
        B = Bl if site.ground[i] else W
        if len(B):
            d = np.hypot(B[:, 0] - cur[i, 0], B[:, 1] - cur[i, 1])
            for j in np.nonzero(d < 120 * sc)[0]:
                src.append(cur[i]); dst.append(B[j, :2])
    if len(src) >= 6:
        A, inl = cv2.estimateAffinePartial2D(np.array(src, np.float32), np.array(dst, np.float32),
                                             method=cv2.RANSAC, ransacReprojThreshold=8.0 * sc, maxIters=4000)
        if A is not None and inl is not None and inl.sum() >= 6:
            cur = (cur @ A[:, :2].T) + A[:, 2]
    # 2. match loosely, solve, match tighter
    for tol in (25.0 * sc, 12.0 * sc, 6.0 * sc, 4.0 * sc):
        pairs = _assign(cur, vis, site.ground, W, Bl, tol)
        if len(pairs) < 6:
            res.note = f"only {len(pairs)} targets matched"; return res
        obj = np.array([G[i] for i, _, _ in pairs]); img = np.array([(Bl if g else W)[j, :2] for _, j, g in pairs])
        ok, rv, tv = cv2.solvePnP(obj, img, K, D, rvec=rv, tvec=tv, useExtrinsicGuess=True)
        if tol == 25.0 * sc:
            ok, rv, tv, inl = cv2.solvePnPRansac(obj, img, K, D, rvec=rv, tvec=tv, useExtrinsicGuess=True,
                                                 reprojectionError=8.0 * sc, iterationsCount=200)
        cur, vis = _project(site, rv, tv, K, D, (w, h))
    # 3. look again for wall targets that should be visible but were not found
    pairs = _assign(cur, vis, site.ground, W, Bl, 4.0 * sc)
    got = {i for i, _, _ in pairs}
    extra = []
    for i in np.nonzero(vis)[0]:
        if i in got or site.ground[i]:
            continue
        p = _local_wall(gray, *cur[i], r=int(18 * sc))
        if p is not None and np.hypot(p[0] - cur[i, 0], p[1] - cur[i, 1]) < 4.0 * sc:
            extra.append((i, p))
    res.matches = ([(site.ids[i], float((Bl if g else W)[j, 0]), float((Bl if g else W)[j, 1]),
                     "ball" if g else "wall") for i, j, g in pairs]
                   + [(site.ids[i], float(p[0]), float(p[1]), "wall (2nd look)") for i, p in extra])
    res.predicted = {site.ids[i]: (float(cur[i, 0]), float(cur[i, 1])) for i in np.nonzero(vis)[0]}
    res.rvec, res.tvec = rv, tv
    return res


def predict_pose(site, van, when, R_bc, lever_frd_fr, up_ground_m):
    """Camera pose (rvec, tvec, world local) for a setup from the camera's place on the van."""
    from src.extrinsic.geo import latlon_to_grid_m, true_north_in_grid_deg
    from src.extrinsic.solve import ENU2NED, rot_zyx
    corr = true_north_in_grid_deg(van.lat, van.lon, site.crs, when)
    R_nb = rot_zyx(van.heading + corr, van.pitch, van.roll)
    R_wc = ENU2NED @ (R_nb @ R_bc)                      # camera -> ENU
    e, n = latlon_to_grid_m(van.lat, van.lon, site.crs, when)
    from src.extrinsic.solve import ground_height_at
    d_ned = R_nb @ np.array([lever_frd_fr[0], lever_frd_fr[1], 0.0])
    cam = np.array([e + d_ned[1], n + d_ned[0], 0.0])
    cam[2] = ground_height_at(site, cam[0], cam[1]) + up_ground_m
    o = site.enh_m[0]
    R_cw = R_wc.T
    tvec = -R_cw @ (cam - o)
    rvec, _ = cv2.Rodrigues(R_cw)
    return rvec, tvec.reshape(3, 1)
