"""run.py — one camera, all its Old School setups: find targets, solve, combine, grade.

Seed (a first guess of where the camera looks), in this order:
  1. this setup's EOP clicks from the old exe (old data), only to start the search;
  2. another setup of this camera already solved here (its place on the van);
  3. the default seed for this camera position (control/<site>/seeds.yaml).
The targets used in the solve are always the ones the app found itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

from src.extrinsic.oldschool import read_eop_clicks
from src.extrinsic.solve import (in_van, pointing, rot_angle_deg, rot_mean, rot_zyx, setup_date,
                                 solve_setup)
from src.extrinsic.targets import match_targets, predict_pose

# ── Pass rules (proposals, 2026-11-01; edit here) ───────────────────────────
MIN_TARGETS = 10           # per setup
MAX_LOO_MM = 20.0          # per setup: leave-one-out miss, RMS over its targets
MIN_SETUPS = 3             # per camera
# Spread limits set from the fleet (2026-11-01, 83 cameras, _analysis/extrinsic_fleet.csv):
# setups of one camera normally disagree by 0.9 deg (median; 1.55 at p90), about equally in
# pan, tilt and roll, so it is the van's attitude while parked, which averages out over the
# setups.  The limits catch broken cameras/setups, not that normal noise.
MAX_ANGLE_SPREAD_DEG = 1.5  # per camera: worst setup vs the camera's mean direction (fleet p90 1.55)
MAX_HEIGHT_SPREAD_M = 0.20  # per camera: camera height above the pavement, max - min (fleet p90 0.21)
OUTLIER_SETUP_DEG = 2.0     # a setup this far from the others (and 3x their median) is left out


# Normal pointing of each camera position (pan, + right of straight ahead).  Real
# installs differ (customers sign off the angles), so the closest one names the camera.
NOMINAL_PAN_DEG = {"ROW": 0.0, "ForwardRight": 45.0, "ForwardLeft": -45.0, "Right": 90.0,
                   "Left": -90.0, "RearRight": 135.0, "RearLeft": -135.0}


def closest_position(pan_deg: float) -> str:
    return min(NOMINAL_PAN_DEG, key=lambda k: abs((pan_deg - NOMINAL_PAN_DEG[k] + 180) % 360 - 180))


@dataclass
class SetupResult:
    setup: object                          # oldschool.Setup
    seed: str = ""
    match: object = None                   # targets.MatchResult
    solve: object = None                   # solve.SetupSolve
    clicks: list = field(default_factory=list)
    label_checks: list = field(default_factory=list)   # (id, text) where the old clicks disagree
    passed: bool = False
    problems: list = field(default_factory=list)


@dataclass
class CameraResult:
    camera: str
    van: str
    folder: str
    setups: list = field(default_factory=list)
    R_bc: np.ndarray | None = None
    pan_tilt_roll: tuple = (math.nan,) * 3
    lever_frd: np.ndarray | None = None          # forward, right (GPS) — rough
    lever_spread_m: np.ndarray | None = None
    up_ground_m: float = math.nan
    height_spread_m: float = math.nan
    angle_spread_deg: float = math.nan
    passed: bool = False
    headline: str = ""
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    K: np.ndarray | None = None
    D: np.ndarray | None = None


def load_seeds(site) -> dict:
    p = Path(site.folder) / "seeds.yaml"
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = {}
    for cam, v in raw.items():
        out[cam] = dict(R_bc=rot_zyx(*v["R_bc_zyx_deg"]), lever=np.array(v["lever_fr_m"] + [0.0]),
                        up=float(v["up_ground_m"]))
    return out


def _seed_from_clicks(s, site, K, D):
    clicks = read_eop_clicks(s.eop) if s.eop else []
    if len(clicks) < 6:
        return None, clicks
    try:
        sol = solve_setup(s.name, clicks, site, K, D)
    except Exception:  # noqa: BLE001
        return None, clicks
    R_cw = sol.R_wc.T
    rvec, _ = cv2.Rodrigues(R_cw)
    tvec = -R_cw @ (sol.cam_enh - site.enh_m[0])
    return (rvec, tvec.reshape(3, 1)), clicks


def run_camera(cs, site, K, D, seeds: dict | None = None, progress_cb=None) -> CameraResult:
    say = progress_cb or (lambda _m: None)
    res = CameraResult(camera=cs.camera, van=cs.van, folder=cs.folder, K=K, D=D)
    seeds = seeds if seeds is not None else load_seeds(site)
    todo = [SetupResult(setup=s) for s in cs.setups]
    for sr in todo:
        if sr.setup.problems:
            sr.problems += sr.setup.problems
    solved = []

    def place_on_van():
        if not solved:
            return None
        return (rot_mean([x.solve.R_bc for x in solved]),
                np.mean([x.solve.lever_frd for x in solved], axis=0),
                float(np.mean([x.solve.up_ground_m for x in solved])))

    # pass 1: setups with old clicks (seed 1); pass 2: the rest (seed 2 or 3)
    order = sorted(todo, key=lambda x: (not bool(x.setup.eop), x.setup.name))

    def attempt(sr):
        s = sr.setup
        if s.van is None or not s.photo:
            return
        say(f"{cs.camera} {s.name}: finding targets…")
        img = cv2.imread(s.photo)
        if img is None:
            sr.problems.append("photo can't be read"); return
        when = setup_date(s.name)
        pose, sr.clicks = _seed_from_clicks(s, site, K, D)
        if pose is not None:
            sr.seed = "old clicks"
        else:
            pv = place_on_van()
            if pv is not None:
                sr.seed = "other setups of this camera"
                # the camera's average place first; each solved setup's own place and the
                # default seed are tried too when that finds few targets
                cands = [pv] + [(x.solve.R_bc, x.solve.lever_frd, x.solve.up_ground_m) for x in solved]
                if cs.camera in seeds:
                    sd = seeds[cs.camera]; cands.append((sd["R_bc"], sd["lever"], sd["up"]))
            elif cs.camera in seeds:
                sd = seeds[cs.camera]; cands = [(sd["R_bc"], sd["lever"], sd["up"])]
                sr.seed = "default seed"
            else:   # position not known from the folder name: try every position
                cands = [(sd["R_bc"], sd["lever"], sd["up"]) for sd in seeds.values()]
                sr.seed = "default seeds, all positions tried"
            if not cands:
                sr.problems.append("no starting guess: no old clicks, no other setup solved, no default seed")
                return
            best = None
            for c in cands:
                m = match_targets(img, site, K, D, *predict_pose(site, s.van, when, *c))
                if best is None or len(m.matches) > len(best.matches):
                    best = m
                if len(best.matches) >= 12:
                    break
            sr.match = best
            pose = None
        if pose is not None:
            sr.match = match_targets(img, site, K, D, *pose)
        if len(sr.match.matches) < 6:
            sr.problems.append(f"targets not found ({sr.match.note or 'too few'})"); return
        try:
            sr.solve = solve_setup(s.name, [(p, x, y) for p, x, y, _k in sr.match.matches], site, K, D)
        except ValueError as exc:
            sr.problems.append(str(exc)); return
        in_van(sr.solve, s.van, site, when)
        # old clicks vs what the app found: a click far from the found target = wrong label/target
        found = {p: (x, y) for p, x, y, _k in sr.match.matches}
        for pid, x, y in sr.clicks:
            if pid in found:
                d = math.hypot(found[pid][0] - x, found[pid][1] - y)
                if d > 4:
                    sr.label_checks.append((pid, f"old click is {d:.0f} px from the target the app found"))
        for pid, why in sr.solve.dropped:
            sr.problems.append(f"target {pid} dropped: {why}")
        if sr.solve.n_points < MIN_TARGETS:
            sr.problems.append(f"only {sr.solve.n_points} targets (need {MIN_TARGETS})")
        if sr.solve.loo_rms_mm > MAX_LOO_MM:
            sr.problems.append(f"targets miss by {sr.solve.loo_rms_mm:.0f} mm RMS (limit {MAX_LOO_MM:g})")
        sr.passed = not [p for p in sr.problems if not p.startswith("target ")]
        if sr.passed:
            solved.append(sr)

    tried_with = {}                      # setup -> how many setups were solved when it was tried
    for sr in order:
        tried_with[id(sr)] = len(solved)
        attempt(sr)
    # pass 3 (2026-11-02, ARAN62 ROW AK26): a setup that found too few targets is tried again
    # once more setups are solved, from the camera's real place on the van instead of the
    # default seed.  Repeats while that keeps solving new setups.
    while True:
        retry = [sr for sr in order if sr.solve is None and not sr.passed and sr.seed != "old clicks"
                 and sr.match is not None and len(solved) > tried_with[id(sr)]]
        if not retry:
            break
        for sr in retry:
            tried_with[id(sr)] = len(solved)
            sr.problems, sr.match, sr.seed = list(sr.setup.problems), None, ""
            sr.clicks, sr.label_checks = [], []
            attempt(sr)
    res.setups = sorted(todo, key=lambda x: x.setup.name)
    _combine(res, solved)
    return res


def _combine(res: CameraResult, good: list) -> None:
    # A setup far from all the others (wrong camera's photo, van pose not saved, ...) is left out.
    while len(good) >= 4:
        Rm = rot_mean([g.solve.R_bc for g in good])
        dev = np.array([rot_angle_deg(Rm.T @ g.solve.R_bc) for g in good])
        k = int(np.argmax(dev))
        rest = np.delete(dev, k)
        if dev[k] > OUTLIER_SETUP_DEG and dev[k] > 3 * np.median(rest):
            g = good.pop(k)
            g.passed = False
            g.problems.append(f"left out: points {dev[k]:.1f} deg away from the other setups")
            continue
        break
    if not good:
        res.headline = "NOT PASSED: no setup could be solved."
        res.reasons.append("No usable setup.")
        return
    Rs = [g.solve.R_bc for g in good]
    res.R_bc = rot_mean(Rs)
    res.pan_tilt_roll = pointing(res.R_bc)
    res.angle_spread_deg = max(rot_angle_deg(res.R_bc.T @ R) for R in Rs)
    lev = np.array([g.solve.lever_frd for g in good])
    res.lever_frd = lev.mean(axis=0)
    res.lever_spread_m = lev.max(axis=0) - lev.min(axis=0)
    ups = np.array([g.solve.up_ground_m for g in good])
    res.up_ground_m = float(ups.mean())
    res.height_spread_m = float(ups.max() - ups.min())
    if len(good) < MIN_SETUPS:
        res.reasons.append(f"Only {len(good)} setups passed (need {MIN_SETUPS}).")
    if res.angle_spread_deg > MAX_ANGLE_SPREAD_DEG:
        res.reasons.append(f"Setups disagree on the camera direction by up to {res.angle_spread_deg:.2f} deg "
                           f"(limit {MAX_ANGLE_SPREAD_DEG:g}).")
    if res.height_spread_m > MAX_HEIGHT_SPREAD_M:
        res.reasons.append(f"Camera height varies {res.height_spread_m * 1000:.0f} mm between setups "
                           f"(limit {MAX_HEIGHT_SPREAD_M * 1000:.0f} mm).")
    near = closest_position(res.pan_tilt_roll[0])
    if res.camera and near != res.camera:
        res.warnings.append(f"The folder says {res.camera}, but the camera points {res.pan_tilt_roll[0]:.0f} deg, "
                            f"closest to {near}. Check the folder name.")
    elif not res.camera:
        res.warnings.append(f"Camera position not in the folder name; it points {res.pan_tilt_roll[0]:.0f} deg, "
                            f"closest to {near}.")
    res.warnings.append(f"Forward/right lever arms come from VBS GPS (about ±0.3 m, setups spread "
                        f"{res.lever_spread_m[0]:.2f} / {res.lever_spread_m[1]:.2f} m); the loop refines them.")
    res.passed = not res.reasons
    res.headline = ("PASS: camera angles and height are good to use." if res.passed
                    else "NOT PASSED: see the reasons.")
