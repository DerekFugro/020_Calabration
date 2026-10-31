"""test_coverage.py — 3 x 3 image coverage grid (src/coverage.py)."""

from __future__ import annotations

import math

import cv2
import numpy as np

from src.calibrator import CalibrationResult
from src.coverage import GOOD, POOR, WEAK, compute_grid, limits_text

W, H = 1500, 900
K = np.array([[1000.0, 0, 762], [0, 1000.0, 447], [0, 0, 1]])   # not the exact centre: that is the placeholder pattern
D = np.zeros((1, 5))


def _board(n=8, pitch=40.0):
    g = np.mgrid[0:n, 0:n].T.reshape(-1, 2) * pitch
    return np.c_[g - g.mean(0), np.zeros(len(g))].astype(np.float64)


def _result(views, noise_px=0.0, seed=0):
    """views: list of (rvec, tvec).  Detected points = projection + noise."""
    rng = np.random.default_rng(seed)
    obj = _board()
    pts, rvecs, tvecs = [], [], []
    for i, (rv, tv) in enumerate(views):
        rv, tv = np.asarray(rv, float), np.asarray(tv, float)
        img = cv2.projectPoints(obj, rv, tv, K, D)[0].reshape(-1, 2)
        img = img + rng.normal(0, noise_px, img.shape) if noise_px else img
        keep = (img[:, 0] >= 0) & (img[:, 0] < W) & (img[:, 1] >= 0) & (img[:, 1] < H)
        pts.append((f"img{i}.png", obj[keep], img[keep]))
        rvecs.append(rv.reshape(3, 1))
        tvecs.append(tv.reshape(3, 1))
    return CalibrationResult(camera_matrix=K, dist_coeffs=D, rms=0.0, rvecs=rvecs,
                             tvecs=tvecs, image_count_used=len(views),
                             image_size=(W, H), points_used=pts)


def _spread_views():
    """Board placed in all 9 areas, each at 3 clearly different tilts."""
    views = []
    for ty in (-300, 0, 300):
        for tx in (-520, 0, 520):
            for rv in ((0.35, 0, 0), (0, 0.35, 0), (-0.3, -0.3, 0)):
                views.append((rv, (tx, ty, 1100)))
    return views


def test_all_green_when_covered_tilted_and_exact():
    g = compute_grid(_result(_spread_views()))
    assert g.count(GOOD) == 9, [(c.name, c.status, c.problems()) for c in g.flat]
    assert g.advice() == []
    assert all(c.rms_px < 1e-6 for c in g.flat)


def test_empty_corners_are_red_for_points():
    views = [((0.35, 0, 0), (0, 0, 1100)), ((0, 0.35, 0), (0, 0, 1100)),
             ((-0.3, -0.3, 0), (0, 0, 1100))]
    g = compute_grid(_result(views))
    corner = g.cells[0][0]
    assert corner.points == 0 and corner.status == POOR and math.isnan(corner.rms_px)
    assert "only 0 points" in corner.problems()[0]
    assert g.cells[1][1].points_status == GOOD
    assert any(line.startswith("Top-left (poor)") for line in g.advice())


def test_noise_drives_error_rating():
    weak = compute_grid(_result(_spread_views(), noise_px=0.6))
    poor = compute_grid(_result(_spread_views(), noise_px=1.5))
    assert all(c.error_status == WEAK for c in weak.flat)
    assert all(c.error_status == POOR for c in poor.flat)
    assert 0.7 < weak.cells[1][1].rms_px < 0.95          # ~0.6*sqrt(2)


def test_flat_on_only_is_poor_for_tilt():
    views = [((0, 0, 0), (tx, ty, 1100)) for ty in (-300, 0, 300) for tx in (-520, 0, 520)]
    views = views * 3
    g = compute_grid(_result(views))
    assert all(c.tilt_spread_deg < 1 for c in g.flat)
    assert all(c.tilt_status == POOR for c in g.flat)
    assert "tilt the board more" in g.cells[1][1].problems()[-1]


def test_names_and_legend():
    g = compute_grid(_result(_spread_views()))
    assert [c.name for c in g.cells[0]] == ["Top-left", "Top-centre", "Top-right"]
    assert g.cells[1][1].name == "Centre"
    assert "30 points" in limits_text() and "0.5 px" in limits_text()
