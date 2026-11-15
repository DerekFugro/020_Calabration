"""oldschool_fake_site.py - a made-up Old School day at the Richmond site, for checking the
whole Phase 8 process end to end without a van, a POS or a real site (Derek, 2026-11-15:
"make sure the whole process works, then we will run a full test").

The truth: one camera at a known place on the van (its seed from control/Richmond/seeds.yaml,
turned a little so the solve has something to find), and a few van positions around the
site that see enough targets.  For each position this draws the photo the camera would take
(dark discs with a white cross on the wall, yellow-green tennis balls on the ground) and
gives the van pose the POS logger would report.  Nothing here is used by the apps.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date

import cv2
import numpy as np

W, H = 1920, 1080
K = np.array([[1530.0, 0, 960], [0, 1530.0, 540], [0, 0, 1]])
D = np.zeros(5)
DISC_M, BALL_M = 0.25, 0.067          # wall disc and tennis ball diameters (made up / real)
WHEN = date(2026, 11, 15)


@dataclass
class VanPose:
    lat: float
    lon: float
    height_m: float
    heading: float
    pitch: float
    roll: float


@dataclass
class Truth:
    camera: str
    R_bc_zyx_deg: tuple
    lever_fr_m: tuple
    up_ground_m: float


def truth_for(camera: str = "ROW", turn_deg=(1.5, -0.8, 0.4), lever_add=(0.10, -0.05), up_add=0.05) -> Truth:
    """The camera's seed place, turned / moved a little (what the solve must find)."""
    import yaml
    from src.extrinsic.control import load_site
    seeds = yaml.safe_load((load_site().folder / "seeds.yaml").read_text(encoding="utf-8"))
    s = seeds[camera]
    z = [a + b for a, b in zip(s["R_bc_zyx_deg"], turn_deg)]
    lv = [a + b for a, b in zip(s["lever_fr_m"], lever_add)]
    return Truth(camera, tuple(z), tuple(lv), float(s["up_ground_m"]) + up_add)


def _pose(site, van: VanPose, t: Truth):
    from src.extrinsic.solve import rot_zyx
    from src.extrinsic.targets import predict_pose
    v = type("V", (), asdict(van))()
    return predict_pose(site, v, WHEN, rot_zyx(*t.R_bc_zyx_deg), np.array(list(t.lever_fr_m) + [0.0]), t.up_ground_m)


def visible(site, van: VanPose, t: Truth):
    """(index, x, y, distance m) of every target in the picture."""
    rvec, tvec = _pose(site, van, t)
    P = site.enh_m - site.enh_m[0]
    R, _ = cv2.Rodrigues(rvec)
    zc = (R @ P.T + tvec.reshape(3, 1))[2]
    pr, _ = cv2.projectPoints(P, rvec, tvec, K, D)
    pr = pr.reshape(-1, 2)
    m = 40
    return [(i, *pr[i], zc[i]) for i in range(len(P))
            if zc[i] > 1.0 and m < pr[i, 0] < W - m and m < pr[i, 1] < H - m]


def find_positions(t: Truth, n: int = 4, need: int = 14) -> list[VanPose]:
    """n van positions (spread apart) where the camera sees at least `need` targets."""
    from src.extrinsic.control import load_site
    site = load_site()
    lat0, lon0 = 37.605357, -77.491697
    m_lat, m_lon = 1 / 111_000.0, 1 / (111_000.0 * np.cos(np.radians(lat0)))
    found = []
    for dn in range(-40, 41, 5):
        for de in range(-40, 41, 5):
            for hd in range(0, 360, 10):
                v = VanPose(lat0 + dn * m_lat, lon0 + de * m_lon, 0.0, float(hd), 0.4, 0.7)
                vis = visible(site, v, t)
                walls = sum(1 for i, *_ in vis if not site.ground[i])
                balls = len(vis) - walls
                if len(vis) < need or walls < 6 or balls < 3:
                    continue
                dist = float(np.median([z for *_a, z in vis]))
                xs = [x for _i, x, _y, _z in vis]
                if dist <= 22 and max(xs) - min(xs) > 0.5 * W:      # close, like a real setup
                    found.append((max(xs) - min(xs) - 20 * dist, dn, de, v))
    found.sort(key=lambda x: -x[0])
    out = []
    for cnt, dn, de, v in found:                          # spread: >= 8 m or >= 30 deg apart
        if all(np.hypot(dn - a, de - b) >= 8 or abs((v.heading - o.heading + 180) % 360 - 180) >= 30
               for _c, a, b, o in out):
            out.append((cnt, dn, de, v))
        if len(out) == n:
            break
    return [v for *_x, v in out]


def render(site, van: VanPose, t: Truth, seed: int = 0) -> np.ndarray:
    """The photo: light wall above, grey pavement below, discs and balls where they project."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 196, np.uint8)
    img[H // 2:] = (118, 118, 118)
    img = cv2.add(img, rng.integers(0, 6, img.shape, dtype=np.uint8))
    for i, x, y, z in sorted(visible(site, van, t), key=lambda a: -a[3]):
        if site.ground[i]:
            r = max(3.0, K[0, 0] * BALL_M / 2 / z)
            cv2.circle(img, (int(round(x)), int(round(y))), int(round(r)), (60, 230, 200), -1, cv2.LINE_AA)
        else:
            r = max(5.0, K[0, 0] * DISC_M / 2 / z)
            c = (int(round(x)), int(round(y)))
            cv2.circle(img, c, int(round(r)), (55, 55, 55), -1, cv2.LINE_AA)
            cv2.line(img, (c[0] - int(r * 0.6), c[1]), (c[0] + int(r * 0.6), c[1]), (235, 235, 235), 2)
    return cv2.GaussianBlur(img, (3, 3), 0)


def lens_yaml(serial: str) -> str:
    """A lens file the Camera position step can read (CAL_<serial>_<date>.yaml)."""
    k = ", ".join(f"{v:g}" for v in K.ravel())
    d = ", ".join("0" for _ in range(5))
    return (f"serial_number: '{serial}'\nimage_width: {W}\nimage_height: {H}\n"
            f"camera_matrix: {{rows: 3, cols: 3, data: [{k}]}}\n"
            f"dist_coeffs: {{rows: 1, cols: 5, data: [{d}]}}\n"
            "grade: {passed: true, headline: PASS}\n")


def save_poses(path, poses: list[VanPose]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([asdict(p) for p in poses], fh, indent=1)
