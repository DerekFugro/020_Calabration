"""solve.py — camera pose per setup, then camera-in-van angles and lever arms.

Frames
  world   site grid, metres: E, N, H (orthometric).  Local origin = the site's first point.
  NED     north, east, down (grid north)
  van     X forward, Y right, Z down; attitude from Applanix (roll + right side down,
          pitch + nose up, heading + clockwise from north; ZYX order)
  camera  OpenCV: x right, y down, z along the view

Lever arm = camera position minus the van reference point (ground at the front of the
van, where the Applanix position is given), in van axes: forward, right, up.
The up value is given two ways: from the surveyed ground (camera height above the
pavement under the camera) and from the GPS height.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime

import cv2
import numpy as np

from src.extrinsic.geo import latlon_to_grid_m, true_north_in_grid_deg

ENU2NED = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0]])


def rot_zyx(yaw, pitch, roll) -> np.ndarray:
    """Body -> NED for heading/pitch/roll in degrees (aerospace ZYX)."""
    y, p, r = np.radians([yaw, pitch, roll])
    cz, sz, cy, sy, cx, sx = math.cos(y), math.sin(y), math.cos(p), math.sin(p), math.cos(r), math.sin(r)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    return Rz @ Ry @ Rx


def zyx_from_rot(R) -> tuple[float, float, float]:
    """Inverse of rot_zyx: (yaw, pitch, roll) in degrees."""
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -R[2, 0]))))
    yaw = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    roll = math.degrees(math.atan2(R[2, 1], R[2, 2]))
    return yaw, pitch, roll


def rot_mean(Rs) -> np.ndarray:
    """Chordal mean of rotation matrices."""
    M = np.sum(Rs, axis=0)
    U, _, Vt = np.linalg.svd(M)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    return R


def rot_angle_deg(R) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))


# The camera's own pointing, in van axes, as people describe it:
#   pan  = left/right of straight ahead (+ to the right), deg
#   tilt = up/down (+ up), deg
#   roll = turn about the view direction (+ clockwise as seen from behind the camera), deg
def pointing(R_bc) -> tuple[float, float, float]:
    z = R_bc[:, 2]                       # view direction in van axes (fwd, right, down)
    pan = math.degrees(math.atan2(z[1], z[0]))
    tilt = math.degrees(math.atan2(-z[2], math.hypot(z[0], z[1])))
    # roll: camera x axis vs the horizontal direction to the right of the view
    right = np.cross(np.array([0.0, 0.0, 1.0]), z)      # down x view = right-ish
    n = np.linalg.norm(right)
    if n < 1e-9:
        return pan, tilt, 0.0
    right /= n
    x = R_bc[:, 0]
    roll = math.degrees(math.atan2(np.dot(np.cross(right, x), z), np.dot(right, x)))
    return pan, tilt, roll


@dataclass
class SetupSolve:
    name: str
    n_points: int
    ids: list
    fit_px: np.ndarray                  # per point, all points used
    loo_mm: np.ndarray                  # leave-one-out miss in the world at each point
    range_m: np.ndarray
    cam_enh: np.ndarray                 # camera position, world (E, N, H) m
    R_wc: np.ndarray                    # camera -> world(ENU)
    R_bc: np.ndarray | None = None      # camera -> van
    lever_frd: np.ndarray | None = None  # forward, right, down (m) from GPS position
    up_ground_m: float = float("nan")   # camera height above the pavement under it (up lever arm)
    up_gps_m: float = float("nan")
    gps_elev_raw: float = float("nan")
    north_corr_deg: float = 0.0
    dropped: list = field(default_factory=list)   # (id, why)

    @property
    def loo_rms_mm(self) -> float:
        return float(np.sqrt(np.mean(self.loo_mm ** 2))) if len(self.loo_mm) else float("nan")


def solve_setup(name, matches, site, K, D, drop_px: float | None = None) -> SetupSolve:
    """matches: list of (point id, x px, y px).  Points that miss by more than
    drop_px after a first solve are dropped (wrong target / wrong label) and listed."""
    if drop_px is None:
        drop_px = 6.0 * max(1.0, 2.0 * K[0, 2] / 1920.0)      # 6 px at 1080p, 12 px at 4K
    idx = site.index()
    m = [(pid, x, y) for pid, x, y in matches if pid in idx]
    G = np.array([site.enh_m[idx[p]] for p, _, _ in m], float)
    P = np.array([[x, y] for _, x, y in m], float)
    ids = [p for p, _, _ in m]
    o = site.enh_m[0]
    Gm = np.ascontiguousarray(G - o)
    dropped = []
    if len(G) < 6:
        raise ValueError(f"{name}: only {len(G)} usable targets")
    # 1. robust start: RANSAC keeps the targets that agree with one camera pose
    ok, rv, tv, inl = cv2.solvePnPRansac(Gm, P, K, D, reprojectionError=drop_px, iterationsCount=1000,
                                         confidence=0.999, flags=cv2.SOLVEPNP_EPNP)
    keep = np.zeros(len(G), bool)
    if ok and inl is not None:
        keep[inl.ravel()] = True
    if keep.sum() < 6:
        raise ValueError(f"{name}: only {keep.sum()} targets agree with one camera pose")

    def refine():
        _ok, r, t = cv2.solvePnP(Gm[keep], P[keep], K, D, rvec=rv.copy(), tvec=tv.copy(),
                                 useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
        return r, t

    rv, tv = refine()
    # RANSAC's quick model can leave out good targets: take back any that fit the refined pose
    pr, _ = cv2.projectPoints(Gm, rv, tv, K, D)
    back = ~keep & (np.linalg.norm(pr.reshape(-1, 2) - P, axis=1) < 0.5 * drop_px)
    if back.any():
        keep |= back
        rv, tv = refine()
    # 2. drop the worst one at a time while it misses by more than drop_px
    for _ in range(len(G)):
        pr, _ = cv2.projectPoints(Gm[keep], rv, tv, K, D)
        err = np.linalg.norm(pr.reshape(-1, 2) - P[keep], axis=1)
        if err.max() <= drop_px or keep.sum() <= 6:
            break
        k = np.nonzero(keep)[0][int(np.argmax(err))]
        keep[k] = False
        rv, tv = refine()
    for k in np.nonzero(~keep)[0]:
        pr, _ = cv2.projectPoints(Gm[k:k + 1], rv, tv, K, D)
        e = float(np.linalg.norm(pr.ravel() - P[k]))
        dropped.append((ids[k], f"missed by {e:.0f} px: wrong target or wrong label" if e < 1e5
                        else "far off: wrong target or wrong label"))
    R_cw, _ = cv2.Rodrigues(rv)
    cam = (-R_cw.T @ tv.ravel())
    Gk, Pk = Gm[keep], P[keep]
    loo, rng = [], []
    for i in range(len(Gk)):
        mm = np.ones(len(Gk), bool); mm[i] = False
        p2 = _loo_project(Gk, Pk, mm, i, K, D, rv, tv)
        r = float(np.linalg.norm(Gk[i] - cam))
        loo.append(float(np.linalg.norm(p2.ravel() - Pk[i])) / K[0, 0] * r * 1000.0)
        rng.append(r)
    pr, _ = cv2.projectPoints(Gk, rv, tv, K, D)
    fit = np.linalg.norm(pr.reshape(-1, 2) - Pk, axis=1)
    return SetupSolve(name=name, n_points=int(keep.sum()), ids=[i for i, k in zip(ids, keep) if k],
                      fit_px=fit, loo_mm=np.array(loo), range_m=np.array(rng),
                      cam_enh=cam + o, R_wc=R_cw.T, dropped=dropped)


def _loo_project(Gk, Pk, mm, i, K, D, rv, tv):
    """Predict point i from the others.  The guided solve can run away when few
    points are left (nearly flat wall); then take the best of a few solvers."""
    full, _ = cv2.projectPoints(Gk[mm], rv, tv, K, D)
    best = None
    for kw in (dict(rvec=rv.copy(), tvec=tv.copy(), useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE),
               dict(flags=cv2.SOLVEPNP_SQPNP), dict(flags=cv2.SOLVEPNP_EPNP)):
        try:
            ok, rv2, tv2 = cv2.solvePnP(Gk[mm], Pk[mm], K, D, **kw)
        except cv2.error:
            continue
        if not ok:
            continue
        pr, _ = cv2.projectPoints(Gk[mm], rv2, tv2, K, D)
        fit = float(np.sqrt(np.mean(np.sum((pr.reshape(-1, 2) - Pk[mm]) ** 2, axis=1))))
        if best is None or fit < best[0]:
            best = (fit, rv2, tv2)
    if best is None:
        best = (0.0, rv, tv)
    p2, _ = cv2.projectPoints(Gk[i:i + 1], best[1], best[2], K, D)
    return p2


def ground_height_at(site, e: float, n: float) -> float:
    """Pavement height (m) at grid E, N: one plane through all the ground targets.

    A plane through every ground target was the steadiest between setups on ARAN65
    (camera height varied 4-12 cm); local fits through the nearest few targets swing
    more because the van usually stands outside the area the targets cover.
    """
    g = site.enh_m[site.ground]
    A = np.c_[g[:, 0] - e, g[:, 1] - n, np.ones(len(g))]
    coef, *_ = np.linalg.lstsq(A, g[:, 2], rcond=None)
    return float(coef[2])


def ground_height(site, cam_enh) -> float:
    """Camera height straight above the pavement under it (m)."""
    return float(cam_enh[2] - ground_height_at(site, cam_enh[0], cam_enh[1]))


def in_van(sol: SetupSolve, van, site, when: date, elev_to_h=None) -> SetupSolve:
    """Camera angles and lever arm in the van frame for one setup."""
    corr = true_north_in_grid_deg(van.lat, van.lon, site.crs, when)
    R_nb = rot_zyx(van.heading + corr, van.pitch, van.roll)
    R_nc = ENU2NED @ sol.R_wc
    sol.R_bc = R_nb.T @ R_nc
    e, n = latlon_to_grid_m(van.lat, van.lon, site.crs, when)
    # Forward / right: from the van's GPS position (the reference point at the front of
    # the van), in van axes.  Up: camera height above the surveyed pavement under it,
    # which needs no GPS height at all.
    lev = R_nb.T @ (ENU2NED @ (sol.cam_enh - np.array([e, n, sol.cam_enh[2]])))
    sol.lever_frd = lev
    sol.up_ground_m = ground_height(site, sol.cam_enh)
    if elev_to_h is not None:
        sol.up_gps_m = float(sol.cam_enh[2] - elev_to_h(van.elevation))
    sol.gps_elev_raw = van.elevation
    sol.north_corr_deg = corr
    return sol


def setup_date(setup_name: str) -> date:
    try:
        return datetime.strptime(setup_name[:8], "%Y%m%d").date()
    except ValueError:
        return date.today()
