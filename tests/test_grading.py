"""test_grading.py — pass/fail grading (src/grading.py) and the store gate."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
import yaml

from src.calibration_store import StoreError, check_publishable
from src.calibrator import CalibrationResult
from src.grading import coverage_counts, grade, ray_disagreement_mrad, sanity_problems
from tests.test_coverage import _result, _spread_views, K, D, W, H


def _result_with_errors(views, noise=0.0, seed=0):
    r = _result(views, noise_px=noise, seed=seed)
    r.image_count_used = len(views)
    r.per_image_errors = [(p, 0.3) for p, _, _ in r.points_used]
    return r


def test_good_set_passes():
    g = grade(_result_with_errors(_spread_views() * 2, noise=0.1))
    assert g.passed, g.as_text()
    assert g.headline.startswith("PASS")
    assert g.repeatability is not None and g.repeatability.at_10m_mm < 10


def test_empty_corner_fails_with_coaching():
    views = [v for v in _spread_views() * 2 if not (v[1][0] < 0 and v[1][1] < 0)]   # nothing top-left
    g = grade(_result_with_errors(views, noise=0.1))
    assert not g.passed
    assert "NOT GOOD ENOUGH" in g.headline and g.more_photos > 0
    assert any(c.startswith("Top-left") for c in g.coaching)


def test_placeholder_is_a_hard_stop():
    Kp = np.array([[4117.45, 0, (W - 1) / 2], [0, 4117.45, (H - 1) / 2], [0, 0, 1]])
    probs = sanity_problems(Kp, np.zeros(5), (W, H), 50)
    assert any("Placeholder" in p for p in probs)
    assert sanity_problems(K, D, (W, H), 50) == []
    assert any("NaN" in p for p in sanity_problems(K * np.nan, D, (W, H), 50))
    assert sanity_problems(K, D, (W, H), 5) == []          # too few photos: a reason, not a hard stop


def test_rotation_is_removed_from_disagreement():
    K2 = K.copy(); K2[0, 2] += K[0, 0] * 0.01                  # image centre moved ~ a 10 mrad turn
    raw = ray_disagreement_mrad(K, D, K2, D, (W, H), remove_rotation=False)
    rem = ray_disagreement_mrad(K, D, K2, D, (W, H))
    assert raw.mean() > 5 and rem.mean() < raw.mean() / 4
    assert ray_disagreement_mrad(K, D, K, D, (W, H)).max() < 1e-3


def test_coverage_counts():
    c = coverage_counts([np.array([[10, 10], [W - 5, H - 5], [W / 2, H / 2]])], (W, H))
    assert c[0, 0] == 1 and c[2, 2] == 1 and c[1, 1] == 1 and c.sum() == 3


def _yaml(tmp_path, data):
    p = tmp_path / "c.yaml"; p.write_text(yaml.safe_dump(data)); return p


def test_store_gate_uses_grade(tmp_path):
    ok = _yaml(tmp_path, {"verdict": "Needs Improvement", "grade": {"passed": True, "headline": "PASS"}})
    assert check_publishable(ok, passed=True) == "Needs Improvement"
    bad = _yaml(tmp_path, {"verdict": "Excellent", "grade": {"passed": False, "headline": "NOT GOOD ENOUGH",
                                                             "reasons": ["Coverage: Top-left"]}})
    with pytest.raises(StoreError, match="did not pass its grade"):
        check_publishable(bad)
    old = _yaml(tmp_path, {"verdict": "Needs Improvement"})                 # no grade: old rule
    with pytest.raises(StoreError):
        check_publishable(old)
