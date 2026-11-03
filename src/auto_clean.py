"""auto_clean.py — calibrate, then leave out bad photos and calibrate again, automatically.

Each round:
  * photos whose fit is far worse than the rest (error > max(2 x median, RMS_MAX_PX))
  * blurry photos (edge blur over the fail limit, src/grading.blur_limits) — only when the set as a whole is sharp;
    when every photo is soft, leaving them out would leave nothing, so the grade
    explains the blur instead
are left out (worst first, at most 10% of the photos per round), and the set is
calibrated again.  Stops when nothing is left to remove, after MAX_ROUNDS, or when
removing more would drop below KEEP_MIN_SHARE of the photos (or MIN_IMAGES).

Left-out photos stay in their folder (they may be fine in another set); they are
listed on the result (cal.auto_removed) and in the report.  Unusable photos (no
board, unreadable, wrong size) are moved to NotUsed earlier, by src/not_used.py.
"""

from __future__ import annotations

import math
import os

import numpy as np

from src.calibrator import calibrate
from src.image_filter import FilterResult

MAX_ROUNDS = 4
KEEP_MIN_SHARE = 0.7
STEP_SHARE = 0.10


def _used(filter_results, detections) -> int:
    return sum(f.accepted and d.charuco_ids is not None for d, f in zip(detections, filter_results))


def calibrate_auto(detections, filter_results, board_config, progress_cb=None):
    from src.grading import MIN_IMAGES, RMS_MAX_PX, blur_limits
    say = progress_cb or (lambda _m: None)
    n0 = _used(filter_results, detections)
    keep_min = max(MIN_IMAGES, math.ceil(KEEP_MIN_SHARE * n0))
    removed: list[tuple[str, str]] = []
    index = {d.image_path: i for i, d in enumerate(detections)}
    cal = None
    for rnd in range(MAX_ROUNDS + 1):
        cal = calibrate(detections, filter_results, board_config)
        if rnd == MAX_ROUNDS:
            break
        errs = cal.per_image_errors                       # worst first
        med = float(np.median([e for _, e in errs])) if errs else 0.0
        w = int(cal.image_size[0])
        lim = max(2.0 * med, RMS_MAX_PX * w / 1920.0)
        blur_max = blur_limits(w)[1]
        cand = [(p, f"high error {e:.2f} px (set median {med:.2f})") for p, e in errs if e > lim]
        blur = getattr(cal, "photo_blur_px", []) or []
        paths = [p for p, _, _ in cal.points_used]
        if blur and len(blur) == len(paths):
            b = np.array(blur, float)
            if np.isfinite(b).any() and np.nanmedian(b) <= blur_max:
                seen = {p for p, _ in cand}
                cand += sorted(((p, f"blurry, edge blur {v:.1f} px") for p, v in zip(paths, b)
                                if v > blur_max and p not in seen), key=lambda x: x[1], reverse=True)
        now = _used(filter_results, detections)
        budget = min(now - keep_min, max(1, math.ceil(STEP_SHARE * now)))
        if not cand or budget <= 0:
            break
        for p, why in cand[:budget]:
            i = index[p]
            f = filter_results[i]
            filter_results[i] = FilterResult(accepted=False, reason=f"Left out automatically: {why}",
                                             corner_count=f.corner_count, blur_score=f.blur_score)
            removed.append((p, why))
        say(f"Left out {min(budget, len(cand))} photo(s), calibrating again "
            f"(round {rnd + 2})…")
    cal.auto_removed = removed
    return cal


def removed_text(cal) -> list[str]:
    return [f"{os.path.basename(p)}: {why}" for p, why in getattr(cal, "auto_removed", [])]
