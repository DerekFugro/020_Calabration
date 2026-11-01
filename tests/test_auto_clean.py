"""Tests for src/auto_clean.py — bad photos are left out without asking."""
import cv2
import numpy as np

from src.auto_clean import calibrate_auto
from src.board import BoardConfig
from src.detector import DetectionResult
from src.image_filter import FilterResult


def _set(n=24, bad=(3, 11), noise=0.15, bad_noise=6.0, seed=0):
    rng = np.random.default_rng(seed)
    b = BoardConfig()
    obj = b.get_all_object_points().reshape(-1, 3).astype(np.float64)
    obj -= obj.mean(0) * [1, 1, 0]
    K = np.array([[1500, 0, 960], [0, 1500, 540], [0, 0, 1.0]])
    D = np.array([-0.1, 0.05, 0, 0, 0])
    dets, filts = [], []
    for i in range(n):
        rv = rng.uniform(-0.5, 0.5, 3); rv[2] *= 0.3
        tv = np.array([rng.uniform(-200, 200), rng.uniform(-100, 100), rng.uniform(1300, 2000)])
        img, _ = cv2.projectPoints(obj, rv, tv, K, D)
        img = img.reshape(-1, 2) + rng.normal(0, bad_noise if i in bad else noise, (len(obj), 2))
        ids = np.arange(len(obj), dtype=np.int32).reshape(-1, 1)
        dets.append(DetectionResult(f"p{i:02d}.jpg", (1920, 1080), img.astype(np.float32).reshape(-1, 1, 2),
                                    ids, len(obj), 50.0))
        filts.append(FilterResult(True, "", len(obj), 50.0))
    return b, dets, filts


def test_bad_photos_are_left_out_and_listed():
    b, dets, filts = _set()
    cal = calibrate_auto(dets, filts, b)
    left = sorted(p for p, _ in cal.auto_removed)
    assert left == ["p03.jpg", "p11.jpg"]
    assert cal.image_count_used == 22 and cal.rms < 0.5
    assert all("Left out automatically" in filts[i].reason for i in (3, 11))


def test_good_set_is_left_alone():
    b, dets, filts = _set(bad=())
    cal = calibrate_auto(dets, filts, b)
    assert cal.auto_removed == [] and cal.image_count_used == 24


def test_never_drops_below_70_percent():
    b, dets, filts = _set(n=20, bad=tuple(range(12)), bad_noise=4.0)
    cal = calibrate_auto(dets, filts, b)
    assert cal.image_count_used >= 15 and len(cal.auto_removed) <= 5
