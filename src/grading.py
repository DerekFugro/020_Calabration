"""grading.py — Grade a calibration: is it good enough, and if not, what to shoot next.

Rules agreed with Derek on 2026-10-31.  A calibration PASSES when all hold:
  1. No hard stop (sanity): no NaN, not a placeholder (image-centre principal
     point with zero distortion), plausible focal length, >= MIN_IMAGES used.
  2. Repeatability: the photos are split into two random halves, each half is
     calibrated separately, and after removing a common camera rotation
     (absorbed by the extrinsic/boresight) half their 95th-percentile
     disagreement is the estimated error.  Done REPEAT_SPLITS times; the median
     counts.  Must be <= REPEAT_MAX_MRAD (0.6 mrad = 6 mm at 10 m).
     Changed 2026-11-02 (Derek): was first half vs second half in time, limit
     1 mrad.  On 68 fleet cameras random splits were a little steadier and
     tracked real Old School target misses better; 0.6 mrad keeps about the same
     pass rate as before (38 vs 39 of 68) until a sharp PASS set sets the limit.
  3. Coverage: every 3x3 area has enough points and enough board tilt
     (points_status and tilt_status good, src/coverage.py).  No red square: red
     means too few points or too little tilt there.
  4. Not too blurry: median dot edge blur <= BLUR_FAIL_HD px in HD terms
     (x width/1920, so 4.4 px on a 4K camera).  Blur shifts the lens without
     making it unsteady, so only this check catches it (blur test on 10 cameras,
     2026-11-03: up to ~1.7 px HD / 4 px 4K the lens moved 0.5-4 mm at 10 m).
Shown but NOT a fail since 2026-11-03 (Derek): RMS and the pixel error per square.
On 68 fleet cameras neither predicted real Old School target misses, and both are
inflated by blur and 4K.  Fleet with these rules: 30 of 68 pass (0 before).

The engine works on a finished CalibrationResult, so the same code grades a
folder now and, later, a live stream of frames (see coverage_counts()).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from src.coverage import GOOD, GRID_N, POINTS_GOOD, GridReport, compute_grid

# ── Pass rules (edit here) ───────────────────────────────────────────────────
RMS_MAX_PX = 2.0
REPEAT_MAX_MRAD = 0.6
REPEAT_SPLITS = 6
REPEAT_SEED = 0                  # fixed: the same photos always give the same answer
MIN_IMAGES = 15
MIN_IMAGES_PER_HALF = 6
PLACEHOLDER_CENTRE_TOL_PX = 1.0
BLUR_SOFT_HD = 1.6              # dot edge blur, px at 1920 wide: above = soft (warning)
BLUR_FAIL_HD = 2.2              # above = too blurry (fail); a 4K camera gets 2x these


def blur_limits(width: int) -> tuple[float, float]:
    """(soft, fail) dot-edge blur limits in px for an image this wide."""
    s = max(width, 1) / 1920.0
    return BLUR_SOFT_HD * s, BLUR_FAIL_HD * s
TILT_PHOTOS_PER_AREA = 3
DEFAULT_POINTS_PER_PHOTO = 10     # coaching: when an area has no photos yet


@dataclass
class Repeatability:
    est_error_p95_mrad: float      # estimated error of the full set, 95% of image
    est_error_mean_mrad: float
    halves_raw_mean_mrad: float    # before removing the common rotation
    images_per_half: int

    @property
    def at_10m_mm(self) -> float:
        return self.est_error_p95_mrad * 10.0


@dataclass
class GradeReport:
    passed: bool
    headline: str
    hard_stops: list = field(default_factory=list)
    reasons: list = field(default_factory=list)      # why it did not pass
    coaching: list = field(default_factory=list)     # what to shoot next
    rms_px: float = math.nan
    images_used: int = 0
    repeatability: Repeatability | None = None
    grid: GridReport | None = None
    worst_images: list = field(default_factory=list)  # (path, rms_px)
    more_photos: int = 0
    warnings: list = field(default_factory=list)        # shown, but do not fail the grade
    left_out: list = field(default_factory=list)        # (path, why) left out by src/auto_clean.py
    blur_median_px: float = math.nan                    # dot edge blur, median over photos
    blurry_images: list = field(default_factory=list)   # (path, blur_px), worst first
    area_photos: dict = field(default_factory=dict)     # 3x3 area name -> photos to take there
    area_how: dict = field(default_factory=dict)        # 3x3 area name -> short "how" text

    def _ask(self, cell, n: int, how: str) -> None:
        self.area_photos[cell.name] = self.area_photos.get(cell.name, 0) + n
        if how not in self.area_how.get(cell.name, ""):
            self.area_how[cell.name] = (self.area_how.get(cell.name, "") + ", " + how).strip(", ")

    def area_todo(self, cell) -> tuple[str, str]:
        """(big, small) text for one 3x3 square: what to do there."""
        n = self.area_photos.get(cell.name, 0)
        if n:
            return f"+{n} photo{'s' if n > 1 else ''}", self.area_how.get(cell.name, "")
        if cell.status == "poor":
            return "Retake", "photos here fit badly"
        if cell.status == "weak":
            return "OK", ""
        return "Done", ""

    @property
    def steady(self) -> tuple[str, str, str]:
        """(status, big, small) for the lens-steady box under the squares.
        status: 'good' | 'poor' | 'none' (not checked)."""
        r = self.repeatability
        limit = REPEAT_MAX_MRAD * 10
        if r is None:
            return "none", "Not checked", f"needs at least {2 * MIN_IMAGES_PER_HALF} usable photos"
        if r.est_error_p95_mrad <= REPEAT_MAX_MRAD:
            return "good", f"{r.at_10m_mm:.0f} mm", f"lens steady: error at 10 m (limit {limit:.0f} mm)"
        return "poor", f"{r.at_10m_mm:.0f} mm", (f"lens not steady: error at 10 m (limit {limit:.0f} mm). Spread the "
                                                 "board over the whole picture all through the shoot, hold it still.")

    @property
    def action(self) -> str:
        """The one line the crew needs: done, get more photos, or retake."""
        if self.passed:
            return "PASS — you're done. Click Save."
        if self.hard_stops:
            return "NOT PASSED — this set must not be used. Retake the photos."
        if self.more_photos == 0 and self.steady[0] == "poor":
            return "NOT PASSED — the lens isn't steady yet (box below the squares). Retake the photos."
        if self.more_photos:
            return (f"NOT PASSED — get about {self.more_photos} more photo{'s' if self.more_photos > 1 else ''} "
                    f"where the squares below ask for them.")
        return "NOT PASSED — retake the photos (see the details below)."

    def as_text(self) -> str:
        lines = [self.headline]
        if not math.isnan(self.blur_median_px):
            lines.append(f"  Sharpness: dot edge blur {self.blur_median_px:.1f} px (sharp is about 1 px)")
        lines += [f"  STOP: {s}" for s in self.hard_stops]
        lines += [f"  - {r}" for r in self.reasons]
        lines += [f"  ! {w}" for w in self.warnings]
        if self.left_out:
            lines.append(f"  Left out automatically: {len(self.left_out)} photo(s)")
            import os as _os2
            lines += [f"    {_os2.path.basename(p)}: {why}" for p, why in self.left_out[:15]]
        if self.coaching:
            lines.append("What to do:")
            lines += [f"  * {c}" for c in self.coaching]
        import os as _os
        lines += [f"    blurry: {_os.path.basename(p)}  {b:.1f} px" for p, b in self.blurry_images[:10]]
        return "\n".join(lines)


# ── Pieces ───────────────────────────────────────────────────────────────────

def _rays(K, D, w, h, step=40):
    xs, ys = np.meshgrid(np.arange(0, w, step), np.arange(0, h, step))
    px = np.c_[xs.ravel(), ys.ravel()].astype(np.float64)
    n = cv2.undistortPoints(px[:, None, :], K, D)[:, 0]
    v = np.c_[n, np.ones(len(n))]
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _best_rotation(a, b):
    u, _, vt = np.linalg.svd(b.T @ a)
    d = np.sign(np.linalg.det(u @ vt))
    return u @ np.diag([1.0, 1.0, d]) @ vt


def ray_disagreement_mrad(K1, D1, K2, D2, size, remove_rotation=True) -> np.ndarray:
    """Angle between the two lenses' viewing directions over the image (mrad)."""
    w, h = size
    a, b = _rays(K1, D1, w, h), _rays(K2, D2, w, h)
    if remove_rotation:
        a = a @ _best_rotation(a, b).T
    return np.arccos(np.clip((a * b).sum(1), -1.0, 1.0)) * 1000.0


def repeatability(cal_result) -> Repeatability | None:
    """Split the photos into two random halves, calibrate each, compare; median of REPEAT_SPLITS splits."""
    pts = cal_result.points_used
    k = len(pts) // 2
    if k < MIN_IMAGES_PER_HALF:
        return None
    O = [np.asarray(o, np.float32) for _, o, _ in pts]
    I = [np.asarray(i, np.float32).reshape(-1, 1, 2) for _, _, i in pts]
    size = tuple(cal_result.image_size)
    rng = np.random.default_rng(REPEAT_SEED)
    splits = [rng.permutation(len(pts)) for _ in range(REPEAT_SPLITS)]

    def one(perm):
        a, b = np.sort(perm[:k]), np.sort(perm[k:])
        _, Ka, Da, _, _ = cv2.calibrateCamera([O[i] for i in a], [I[i] for i in a], size, None, None)
        _, Kb, Db, _, _ = cv2.calibrateCamera([O[i] for i in b], [I[i] for i in b], size, None, None)
        ang = ray_disagreement_mrad(Ka, Da, Kb, Db, size)
        raw = ray_disagreement_mrad(Ka, Da, Kb, Db, size, remove_rotation=False)
        return float(np.percentile(ang, 95)), float(ang.mean()), float(raw.mean())

    from concurrent.futures import ThreadPoolExecutor      # OpenCV releases the GIL
    with ThreadPoolExecutor(max_workers=REPEAT_SPLITS) as ex:
        res = np.array(list(ex.map(one, splits)))
    p95, mean, raw = np.median(res, axis=0)
    # two independent halves each carry ~sqrt(2) x the full set's error,
    # so their difference is ~2 x the full set's error.
    return Repeatability(est_error_p95_mrad=float(p95) / 2, est_error_mean_mrad=float(mean) / 2,
                         halves_raw_mean_mrad=float(raw), images_per_half=k)


def sanity_problems(K, D, size, images_used: int) -> list[str]:
    """Hard stops: results no one should use."""
    w, h = size
    out = []
    K = np.asarray(K, float); D = np.asarray(D, float).ravel()
    if not np.all(np.isfinite(K)) or not np.all(np.isfinite(D)):
        return ["The lens values contain NaN or infinity: the calibration did not solve."]
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    if (abs(cx - (w - 1) / 2) <= PLACEHOLDER_CENTRE_TOL_PX and abs(cy - (h - 1) / 2) <= PLACEHOLDER_CENTRE_TOL_PX
            and np.allclose(D, 0)):
        out.append("Placeholder values: image centre exactly in the middle and zero distortion "
                   "(the calibration never ran).")
    if not (0.3 * w <= fx <= 10 * w) or not (0.3 * w <= fy <= 10 * w):
        out.append(f"Focal length {fx:.0f} px is not plausible for a {w} px wide image.")
    elif abs(fx - fy) / fx > 0.05:
        out.append(f"fx and fy differ by {abs(fx - fy) / fx:.0%}; pixels are square on these cameras.")
    return out


def coverage_counts(points_xy: list, size) -> np.ndarray:
    """Points per 3x3 area from detected image points only (no calibration).
    For live mode: update after every frame."""
    w, h = size
    c = np.zeros((GRID_N, GRID_N), int)
    for p in points_xy:
        p = np.asarray(p, float).reshape(-1, 2)
        if not len(p):
            continue
        col = np.clip((p[:, 0] * GRID_N / w).astype(int), 0, GRID_N - 1)
        row = np.clip((p[:, 1] * GRID_N / h).astype(int), 0, GRID_N - 1)
        np.add.at(c, (row, col), 1)
    return c


def board_warning(rep, board) -> None:
    """Warn when the board's print was never measured (Boards tab)."""
    if rep is None or board is None:
        return
    if getattr(board, "print_measured", True) is False:
        rep.warnings.append(f"Board {board.name}: the print has not been measured (Boards tab). "
                            "A print stretched 1% one way adds about 0.9 px of error.")


def _grade_blur(rep, cal_result) -> None:
    blur = np.array([b for b in getattr(cal_result, "photo_blur_px", []) or []], float)
    paths = [p for p, _, _ in cal_result.points_used]
    if blur.size == 0 or np.isnan(blur).all() or len(paths) != blur.size:
        return
    soft, fail = blur_limits(int(cal_result.image_size[0]))
    rep.blur_median_px = float(np.nanmedian(blur))
    rep.blurry_images = sorted(((p, float(b)) for p, b in zip(paths, blur) if b > fail), key=lambda x: -x[1])
    if rep.blur_median_px > soft:
        tip = "Do NOT refocus the camera (that changes the lens numbers). "
        # Board distance per photo (board units are mm): if the far photos are sharper,
        # the board is held closer than the lens is focused.
        try:
            z = np.array([float(np.ravel(t)[2]) for t in cal_result.tvecs]) / 1000.0
            ok = ~np.isnan(blur)
            if ok.sum() >= 6 and np.corrcoef(z[ok], blur[ok])[0, 1] < -0.3:
                sharp = z[ok][blur[ok] <= np.nanpercentile(blur, 25)]
                tip += (f"The sharpest photos were with the board about {np.median(sharp):.1f} m away: "
                        f"hold it at that distance or farther. ")
        except Exception:  # noqa: BLE001
            pass
        tip += "Board on a stand and stopped before each photo, van engine off, good light, clean lens."
        if rep.blur_median_px > fail:
            rep.reasons.append(f"Too blurry: dot edge blur {rep.blur_median_px:.1f} px (limit {fail:.1f} px "
                               f"for this image size). Blur shifts the lens without the other checks noticing.")
        else:
            rep.warnings.append(f"Photos are soft: dot edge blur {rep.blur_median_px:.1f} px (fails above "
                                f"{fail:.1f} px for this image size).")
        rep.coaching.append(tip)
    elif rep.blurry_images:
        n = len(rep.blurry_images)
        rep.coaching.append(f"{n} blurry photo{'s' if n > 1 else ''} (edge blur over {fail:.1f} px, "
                            f"listed): hold the board still.")


# ── The grade ────────────────────────────────────────────────────────────────

def grade(cal_result) -> GradeReport:
    """Grade a finished calibration and say what to shoot next."""
    size = tuple(cal_result.image_size)
    rep = GradeReport(passed=False, headline="", rms_px=float(cal_result.rms),
                      images_used=int(cal_result.image_count_used))

    rep.hard_stops = sanity_problems(cal_result.camera_matrix, cal_result.dist_coeffs,
                                     size, rep.images_used)
    try:
        rep.grid = compute_grid(cal_result)
    except Exception:  # noqa: BLE001
        rep.grid = None
    try:
        rep.repeatability = repeatability(cal_result)
    except Exception:  # noqa: BLE001
        rep.repeatability = None

    # Coverage coaching: points and tilt per area
    more = 0
    if rep.grid is not None:
        for c in rep.grid.flat:
            if c.points_status != GOOD:
                per = c.points / c.images if c.images else DEFAULT_POINTS_PER_PHOTO
                need = max(1, math.ceil((POINTS_GOOD - c.points) / max(per, 1)))
                more += need
                rep._ask(c, need, "board in this area")
                rep.coaching.append(f"{c.name}: only {c.points} points. Take about {need} more "
                                    f"photo{'s' if need > 1 else ''} with the board in this part of the picture.")
            if c.points and c.tilt_status != GOOD:
                more += TILT_PHOTOS_PER_AREA
                rep._ask(c, TILT_PHOTOS_PER_AREA, "tilt the board 20-45°")
                rep.coaching.append(f"{c.name}: board angles vary only {c.tilt_spread_deg:.0f}°. "
                                    f"Take {TILT_PHOTOS_PER_AREA} photos here with the board tilted "
                                    f"20-45° up, down and sideways.")
        weak = [c.name for c in rep.grid.flat if c.points_status != GOOD or (c.points and c.tilt_status != GOOD)]
        if weak:
            rep.reasons.append(f"Coverage: {len(weak)} of 9 areas need more photos ({', '.join(weak)}).")
    else:
        rep.reasons.append("Coverage could not be measured.")

    # Photo count (fixable by shooting more, so not a hard stop)
    if rep.images_used < MIN_IMAGES:
        short = MIN_IMAGES - rep.images_used
        more = max(more, short)
        rep.reasons.append(f"Only {rep.images_used} usable photos; at least {MIN_IMAGES} are needed.")
        rep.coaching.append(f"Take at least {short} more photo{'s' if short > 1 else ''}.")

    # Repeatability
    r = rep.repeatability
    if r is None:
        rep.reasons.append(f"Repeatability not checked: needs at least {2 * MIN_IMAGES_PER_HALF} usable photos.")
    elif r.est_error_p95_mrad > REPEAT_MAX_MRAD:
        rep.reasons.append(f"Repeatability: about {r.at_10m_mm:.0f} mm at 10 m (limit "
                           f"{REPEAT_MAX_MRAD * 10:.0f} mm). Halves of the photos give different lenses.")
        rep.coaching.append("Lens not steady: take sharp photos with the board held still, spread over the "
                            "whole picture and tilted; more photos at the edges help most.")

    # RMS: shown only (not a fail since 2026-11-03)
    sc = size[0] / 1920.0
    if not math.isnan(rep.rms_px) and rep.rms_px >= RMS_MAX_PX * sc:
        rep.warnings.append(f"RMS {rep.rms_px:.2f} px is high for this image size: the dots are not found "
                            f"cleanly (blur, motion, compression or a board that is not flat). Shown only.")

    rep.left_out = list(getattr(cal_result, "auto_removed", []) or [])

    # Blur (dot boards: measured on the dot edges, src/dot_detector.edge_blur_px)
    _grade_blur(rep, cal_result)

    # Worst photos
    errs = [e for _, e in cal_result.per_image_errors]
    if errs:
        lim = max(2.0 * float(np.median(errs)), RMS_MAX_PX * sc)
        rep.worst_images = [(p, e) for p, e in cal_result.per_image_errors if e > lim][:10]
        if rep.worst_images:
            n = len(rep.worst_images)
            rep.coaching.append(f"{'1 photo still fits' if n == 1 else f'{n} photos still fit'} "
                                f"poorly (listed): hold the board still and take replacements.")

    rep.more_photos = more
    rep.passed = not rep.hard_stops and not rep.reasons
    if rep.passed:
        rep.headline = "PASS: good enough to use."
    elif rep.hard_stops:
        rep.headline = "NOT PASSED: this calibration must not be used."
    elif more:
        rep.headline = (f"NOT PASSED: take about {more} more photo{'s' if more > 1 else ''} "
                        f"in the areas listed.")
    else:
        rep.headline = "NOT PASSED: retake the photos, see the reasons."
    return rep
