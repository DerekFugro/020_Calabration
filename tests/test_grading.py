"""test_grading.py — pass/fail grading (src/grading.py) and the store gate."""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from src.calibration_store import StoreError, check_publishable
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
    assert "NOT PASSED" in g.headline and g.more_photos > 0
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
    ok = _yaml(tmp_path, {"grade": {"passed": True, "headline": "PASS"}})
    assert check_publishable(ok, passed=True) == "PASS"
    bad = _yaml(tmp_path, {"grade": {"passed": False, "headline": "NOT PASSED",
                                                             "reasons": ["Coverage: Top-left"]}})
    with pytest.raises(StoreError, match="did not pass its grade"):
        check_publishable(bad)
    old = _yaml(tmp_path, {"verdict": "Excellent"})                         # no grade: refused
    with pytest.raises(StoreError):
        check_publishable(old)


def test_pixel_error_alone_does_not_fail_but_few_points_does(monkeypatch):
    """2026-11-03: a square's pixel error is shown only; red = too few points or too little tilt."""
    from types import SimpleNamespace
    import numpy as np
    import src.grading as gr
    from src.coverage import GOOD, POOR, GridCell, GridReport

    def grid(kind):
        cells = [[GridCell(r, c, points=500, images=40, rms_px=0.4, tilt_spread_deg=40,
                           points_status=GOOD, error_status=GOOD, tilt_status=GOOD, status=GOOD)
                  for c in range(3)] for r in range(3)]
        c = cells[2][0]
        if kind == "error":
            c.rms_px, c.error_status = 1.17, POOR
        if kind == "points":
            c.points, c.points_status, c.status = 5, POOR, POOR
        return GridReport(cells=cells, image_size=(1920, 1080))

    cal = SimpleNamespace(image_size=(1920, 1080), rms=0.8, image_count_used=200,
                          camera_matrix=np.array([[1665.0, 0, 944], [0, 1665, 520], [0, 0, 1]]),
                          dist_coeffs=np.zeros((1, 5)), per_image_errors=[("a", 0.8)] * 5,
                          points_used=[], photo_blur_px=[], auto_removed=[])
    rep_ok = SimpleNamespace(est_error_p95_mrad=0.5, at_10m_mm=5.0)
    monkeypatch.setattr(gr, "repeatability", lambda c: rep_ok)
    monkeypatch.setattr(gr, "sanity_problems", lambda *a, **k: [])
    monkeypatch.setattr(gr, "compute_grid", lambda c: grid("error"))
    assert gr.grade(cal).passed
    monkeypatch.setattr(gr, "compute_grid", lambda c: grid("points"))
    g = gr.grade(cal)
    assert not g.passed and any("Bottom-left" in r for r in g.reasons)


def test_squares_say_done_or_how_many_photos():
    """Derek 2026-11-02: the 3x3 squares tell the crew 'done' or 'get N more photos here'."""
    from types import SimpleNamespace
    from src.grading import GradeReport
    rep = GradeReport(passed=False, headline="")
    a = SimpleNamespace(name="Bottom-centre", status="poor")
    b = SimpleNamespace(name="Centre", status="good")
    c = SimpleNamespace(name="Top-left", status="weak")
    rep._ask(a, 14, "board in this area")
    rep._ask(a, 3, "tilt the board 20-45°")
    rep.more_photos = 17
    assert rep.area_todo(a) == ("+17 photos", "board in this area, tilt the board 20-45°")
    assert rep.area_todo(b) == ("Done", "")
    assert rep.area_todo(c) == ("OK", "")
    assert rep.action.startswith("NOT PASSED") and "17 more photos" in rep.action
    rep.passed = True
    assert "you're done" in rep.action


def test_lens_steady_box_and_banner():
    """A fail on repeatability alone must point at the lens-steady box, not 'see the details'."""
    from src.grading import GradeReport, Repeatability
    rep = GradeReport(passed=False, headline="")
    rep.repeatability = Repeatability(est_error_p95_mrad=1.5, est_error_mean_mrad=1.0,
                                      halves_raw_mean_mrad=1.0, images_per_half=50)
    assert rep.steady[0] == "poor" and rep.steady[1] == "15 mm"
    assert "lens isn't steady" in rep.action
    rep.repeatability = Repeatability(0.6, 0.4, 0.4, 50)
    assert rep.steady[0] == "good"
    rep.repeatability = None
    assert rep.steady[0] == "none"
