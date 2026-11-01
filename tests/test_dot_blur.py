"""Tests for the dot-edge blur measure and its grading."""
import math
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.dot_detector import detect_blobs, edge_blur_px
from src.grading import BLUR_MAX_PX, _grade_blur, GradeReport


def _dots(sigma, r=30):
    img = np.full((600, 900), 230, np.uint8)
    pts = [(150 + 150 * i, 150 + 150 * j) for i in range(5) for j in range(3)]
    for x, y in pts:
        cv2.circle(img, (x * 16, y * 16), r * 16, 25, -1, cv2.LINE_AA, 4)
    if sigma > 0:
        img = cv2.GaussianBlur(img, (0, 0), sigma)
    return img, np.array(pts, float)


@pytest.mark.parametrize("sigma", [1.0, 2.0, 3.5])
def test_blur_estimate_matches_known_blur(sigma):
    img, pts = _dots(sigma)
    b = detect_blobs(img)
    est = edge_blur_px(img, pts, b)
    # Sobel on a 1-px antialiased edge adds ~0.6 px; it shrinks as blur grows
    assert est == pytest.approx(math.hypot(sigma, 0.6), rel=0.2)


def test_blur_nan_without_dots():
    assert math.isnan(edge_blur_px(np.zeros((50, 50), np.uint8), np.zeros((0, 2)), np.zeros((0, 5))))


def _cal(blurs, z_m):
    return SimpleNamespace(photo_blur_px=list(blurs),
                           points_used=[(f"p{i}.jpg", None, None) for i in range(len(blurs))],
                           tvecs=[np.array([0, 0, z * 1000.0]) for z in z_m])


def test_blurry_set_fails_and_suggests_distance():
    z = np.linspace(1.2, 3.0, 12)
    rep = GradeReport(passed=False, headline="")
    _grade_blur(rep, _cal(8.0 - 1.8 * z, z))        # farther = sharper
    assert rep.blur_median_px > BLUR_MAX_PX
    assert rep.reasons == [] and any("blurry" in w for w in rep.warnings)   # warns, doesn't fail
    assert any("Do NOT refocus" in c and "farther" in c for c in rep.coaching)


def test_sharp_set_lists_single_blurry_photo():
    rep = GradeReport(passed=False, headline="")
    _grade_blur(rep, _cal([0.9] * 11 + [4.0], [1.5] * 12))
    assert rep.reasons == [] and rep.blurry_images == [("p11.jpg", 4.0)]
    assert any("1 blurry photo" in c for c in rep.coaching)
