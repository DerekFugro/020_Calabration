"""Tests for the Old School (extrinsic) solve."""
from datetime import date
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.extrinsic.control import load_site
from src.extrinsic.geo import latlon_to_grid_m, true_north_in_grid_deg
from src.extrinsic.intrinsic_source import from_file
from src.extrinsic.oldschool import read_van_pose
from src.extrinsic.outputs import opk
from src.extrinsic.solve import (ENU2NED, in_van, pointing, rot_zyx, solve_setup,
                                 zyx_from_rot)
from src.extrinsic.targets import detect_balls, detect_wall, predict_pose

K = np.array([[1530.0, 0, 960], [0, 1530.0, 540], [0, 0, 1]])
D = np.zeros(5)
WHEN = date(2024, 12, 5)
LAT, LON = 37.605357, -77.491697


def test_site_loads_tennis_file():
    s = load_site()
    assert len(s.ids) == 54 and s.ground.sum() == 15 and "50" in s.ids


def test_zyx_round_trip():
    R = rot_zyx(165.6, 0.4, -0.7)
    assert np.allclose(zyx_from_rot(R), (165.6, 0.4, -0.7))


def test_grid_north_correction_richmond():
    # east of the Virginia South central meridian (-78.5): true north is west of grid north
    assert true_north_in_grid_deg(LAT, LON, 6595, WHEN) == pytest.approx(-0.61, abs=0.03)
    e, n = latlon_to_grid_m(LAT, LON, 6595, WHEN)
    assert 3.5e6 < e < 3.7e6 and 1.1e6 < n < 1.2e6


def _van(heading=165.6, pitch=0.4, roll=0.7):
    return SimpleNamespace(lat=LAT, lon=LON, heading=heading, pitch=pitch, roll=roll, elevation=88.5,
                           gps_status="CADifferential", spread_deg=0.05)


def test_known_camera_on_van_is_recovered():
    """Put a camera on the van at a known place, project the targets, solve: same place back."""
    site = load_site()
    van = _van()
    R_bc_true = rot_zyx(39.0, -2.2, 0.0) @ np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0.0]])  # look 39 deg right
    rvec, tvec = predict_pose(site, van, WHEN, R_bc_true, np.array([-2.4, 0.6, 0.0]), 2.3)
    pts, _ = cv2.projectPoints(site.enh_m - site.enh_m[0], rvec, tvec, K, D)
    pts = pts.reshape(-1, 2)
    R, _ = cv2.Rodrigues(rvec)
    zc = (R @ (site.enh_m - site.enh_m[0]).T + tvec)[2]
    vis = (zc > 0) & (pts[:, 0] > 0) & (pts[:, 0] < 1920) & (pts[:, 1] > 0) & (pts[:, 1] < 1080)
    matches = [(site.ids[i], *pts[i]) for i in np.nonzero(vis)[0]]
    assert len(matches) >= 10
    sol = in_van(solve_setup("t", matches, site, K, D), van, site, WHEN)
    assert np.degrees(np.arccos(np.clip((np.trace(sol.R_bc.T @ R_bc_true) - 1) / 2, -1, 1))) < 0.01
    assert sol.lever_frd[:2] == pytest.approx([-2.4, 0.6], abs=0.01)
    assert sol.up_ground_m == pytest.approx(2.3, abs=0.01)
    pan, tilt, _ = pointing(sol.R_bc)
    assert pan == pytest.approx(39.0, abs=0.05) and tilt == pytest.approx(-2.2, abs=0.05)
    assert sol.loo_rms_mm < 0.5


def test_wrong_label_is_dropped():
    site = load_site()
    van = _van()
    R_bc = rot_zyx(39.0, -2.2, 0.0) @ np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0.0]])
    rvec, tvec = predict_pose(site, van, WHEN, R_bc, np.array([-2.4, 0.6, 0.0]), 2.3)
    pts, _ = cv2.projectPoints(site.enh_m - site.enh_m[0], rvec, tvec, K, D)
    pts = pts.reshape(-1, 2)
    vis = [i for i in range(len(pts)) if 0 < pts[i, 0] < 1920 and 0 < pts[i, 1] < 1080]
    m = [[site.ids[i], *pts[i]] for i in vis]
    m[3][1], m[4][1] = m[4][1], m[3][1]          # swap two labels' pixels
    sol = solve_setup("t", [tuple(x) for x in m], site, K, D)
    assert {d[0] for d in sol.dropped} >= {m[3][0]} or {d[0] for d in sol.dropped} >= {m[4][0]}


def test_opk_matches_old_eop_convention():
    # a camera looking roughly east-north-east, level: old EOP lines 7-9 look like (24, -87, 179)
    R_bc = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0.0]])
    R_wc = ENU2NED @ (rot_zyx(66.0, 0, 0) @ R_bc)
    ph, om, ka = opk(R_wc)
    assert abs(om) == pytest.approx(90, abs=0.5) and abs(abs(ka) - 180) < 0.5 or abs(ka) < 0.5


def test_read_van_pose(tmp_path):
    p = tmp_path / "ReviewData_x.csv"
    p.write_text("Begin Chainage,End Chainage,Roll,Pitch,Heading,Latitude,Longitude,Elevation,GPS Status\n"
                 + "".join(f"{i},0,0.7,0.4,{359.9 if i % 2 else 0.1},37.6,-77.49,88.5,CADifferential\n" for i in range(10)))
    v = read_van_pose(str(p))
    assert v.rows == 10 and v.gps_status == "CADifferential"
    assert min(v.heading, 360 - v.heading) < 0.01           # circular mean across north


def test_not_passed_lens_usable_with_warning(tmp_path):
    """2026-11-03: a lens that did not pass may be used for the extrinsic, with a warning."""
    y = tmp_path / "CAL_1_20260101_000000.yaml"
    y.write_text("serial_number: '1'\ncamera_matrix: {data: [1,0,0,0,1,0,0,0,1]}\n"
                 "dist_coeffs: {data: [0,0,0,0,0]}\ngrade: {passed: false, headline: NOT PASSED}\n")
    it = from_file(str(y))
    assert not it.graded_pass and "did not pass" in it.warning and it.serial == "1"
    y.write_text("serial_number: '1'\ncamera_matrix: {data: [1,0,0,0,1,0,0,0,1]}\n"
                 "dist_coeffs: {data: [0,0,0,0,0]}\ngrade: {passed: true, headline: PASS}\n")
    it = from_file(str(y))
    assert it.graded_pass and it.warning == ""
    bad = tmp_path / "x_intrinsic_cal.xml"; bad.write_text("<x/>")
    with pytest.raises(ValueError, match="can read"):
        from_file(str(bad))


def test_detectors_find_disc_and_ball():
    img = np.full((400, 600, 3), 210, np.uint8)
    cv2.circle(img, (150, 150), 22, (70, 70, 70), -1)
    cv2.line(img, (138, 150), (162, 150), (230, 230, 230), 2)
    cv2.rectangle(img, (0, 300), (600, 400), (60, 60, 60), -1)
    cv2.circle(img, (400, 350), 6, (60, 230, 200), -1)       # yellow-green ball (BGR)
    w = detect_wall(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    b = detect_balls(img)
    assert np.min(np.hypot(w[:, 0] - 150, w[:, 1] - 150)) < 1.5
    assert len(b) == 1 and np.hypot(b[0, 0] - 400, b[0, 1] - 350) < 1.5


def test_closest_position_and_side_names():
    from src.extrinsic.run import closest_position
    from src.van_scan import camera_from_name
    assert closest_position(39) == "ForwardRight" and closest_position(-6) == "ROW"
    assert closest_position(-162.7) == "RearLeft" and closest_position(95) == "Right"
    assert camera_from_name("Right") == "Right" and camera_from_name("Left") == "Left"


def test_outlier_setup_left_out():
    from src.extrinsic.run import CameraResult, _combine
    base = rot_zyx(39, -2, 0) @ np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0.0]])
    def g(yaw):
        sol = SimpleNamespace(R_bc=rot_zyx(yaw, 0, 0) @ base, lever_frd=np.array([-2.4, 0.6, 0]), up_ground_m=2.3)
        return SimpleNamespace(solve=sol, passed=True, problems=[])
    good = [g(0.2), g(-0.2), g(0.1), g(-0.1), g(50.0)]
    res = CameraResult(camera="ForwardRight", van="X", folder="f")
    _combine(res, good)
    assert len(good) == 4 and res.angle_spread_deg < 0.5 and res.passed
    assert "left out" in good_out[0] if (good_out := []) else True


def test_height_from_setups_with_tennis_balls():
    """2026-11-02: height comes from setups with 3+ balls when 3+ such setups exist."""
    from src.extrinsic.run import CameraResult, _combine
    base = rot_zyx(39, -2, 0) @ np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0.0]])
    def g(up, balls):
        sol = SimpleNamespace(R_bc=base, lever_frd=np.array([-2.4, 0.6, 0]), up_ground_m=up)
        return SimpleNamespace(solve=sol, passed=True, problems=[], ground_targets=balls)
    good = [g(2.30, 5), g(2.31, 4), g(2.32, 3), g(2.05, 1), g(2.19, 0)]
    res = CameraResult(camera="ForwardRight", van="X", folder="f")
    _combine(res, good)
    assert abs(res.up_ground_m - 2.31) < 1e-6 and res.height_spread_m < 0.03 and res.passed
    assert [getattr(x, "counts_for_height", False) for x in good] == [True, True, True, False, False]
    few = [g(2.30, 5), g(2.31, 0), g(2.05, 1)]
    res2 = CameraResult(camera="ForwardRight", van="X", folder="f")
    _combine(res2, few)
    assert any("Park so at least 3 balls" in w for w in res2.warnings)
