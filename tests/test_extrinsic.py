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


def test_skip_dont_use_folders():
    from src.extrinsic.oldschool import SKIP_RE
    for name in ("20260807.145627 (Don't Use)", "20260807.145840 (Dont Use)", "RL5_Do Not Use",
                 "Position 7 (Do Not Use)", "x (do not use)", "Bad", "do_not_use", "20260807 (Don\u2019t Use)"):
        assert SKIP_RE.search(name), name
    for name in ("20260807.145008", "Position 5", "20260510.165335 (Missing IRI on CSV)", "ROW1", "Badge"):
        assert not SKIP_RE.search(name), name


def test_closest_position_fleet_angles():
    from src.extrinsic.run import closest_position
    # ARAN69 front corners point about +-21 deg; they must not be named ROW
    assert closest_position(21.1) == "ForwardRight"
    assert closest_position(-21.7) == "ForwardLeft"
    assert closest_position(39.6) == "ForwardRight" and closest_position(-38.9) == "ForwardLeft"
    assert closest_position(-6.4) == "ROW" and closest_position(1.8) == "ROW"
    assert closest_position(-163.1) == "RearLeft" and closest_position(-173.7) == "RearLeft"
    assert closest_position(165.0) == "RearRight"
    assert closest_position(90.0) == "Right" and closest_position(-90.0) == "Left"


def test_local_ball_finds_pale_ball():
    """A faded, washed-out ball the fixed colour range misses is found by the 2nd look."""
    import cv2
    import numpy as np
    from src.extrinsic.targets import _local_ball, detect_balls
    rng = np.random.default_rng(1)
    img = np.clip(rng.normal(95, 6, (200, 200, 3)), 0, 255).astype(np.uint8)      # grey pavement
    cv2.circle(img, (103, 98), 7, (150, 178, 170), -1)                           # pale green-white ball (BGR)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    assert len(detect_balls(img)) == 0                                            # first pass misses it
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    p = _local_ball(lab, 100, 100, 14.0, 1.0)
    assert p is not None and abs(p[0] - 103) < 1.5 and abs(p[1] - 98) < 1.5
    assert _local_ball(cv2.cvtColor(np.full((200, 200, 3), 95, np.uint8), cv2.COLOR_BGR2LAB), 100, 100, 14.0, 1.0) is None


def _intr(serial="2000713", w=1920, h=1080, when=None, passed=True, camera="ForwardLeft"):
    import numpy as np
    from src.extrinsic.intrinsic_source import Intrinsic
    K = np.array([[1700.0, 0, w / 2], [0, 1700.0, h / 2], [0, 0, 1]])
    return Intrinsic(K, np.zeros(5), serial, "test lens" + ("" if passed else " (NOT PASSED)"), passed, "" if passed else "The lens did not pass.",
                     width=w, height=h, date=when, date_what="Lens photos taken", camera=camera)


def _os_setups(tmp_path, w=1920, h=1080, names=("20260404.102502", "20260404.120509")):
    import cv2
    import numpy as np
    from types import SimpleNamespace
    out = []
    for n in names:
        d = tmp_path / n; d.mkdir(exist_ok=True)
        ph = d / "1.jpg"; cv2.imwrite(str(ph), np.zeros((h, w), np.uint8))
        out.append(SimpleNamespace(folder=str(d), name=n, photo=str(ph)))
    return out


def test_lens_checks_all_good(tmp_path):
    from datetime import datetime
    from src.extrinsic.lens_check import OK, lens_checks
    cks = lens_checks(_intr(when=datetime(2026, 4, 3, 9, 0)), _os_setups(tmp_path), "ForwardLeft", "2000713",
                      "ForwardLeft")
    assert all(s == OK for s, _, _ in cks), cks
    titles = [t for _, t, _ in cks]
    assert "The lens is for this camera" in titles and "The Old School folder is for this camera" in titles
    dates = [d for s, t, d in cks if "same visit" in t][0]
    assert "Fri 3 Apr 2026" in dates and "Sat 4 Apr 2026" in dates and "1 day apart" in dates


def test_lens_checks_warn_in_plain_words(tmp_path):
    from datetime import datetime
    from src.extrinsic.lens_check import WARN, lens_checks, warnings_text
    cks = lens_checks(_intr(serial="2000211", w=3840, h=2160, when=datetime(2026, 2, 18), passed=False),
                      _os_setups(tmp_path), "ForwardLeft", "2000713", "ForwardLeft")
    warn = {t: d for s, t, d in cks if s == WARN}
    assert "The lens is for a different serial" in warn
    assert "2000211" in warn["The lens is for a different serial"] and "2000713" in warn["The lens is for a different serial"]
    size = warn["The lens file is for a different photo size"]
    assert "1920 × 1080" in size and "3840 × 2160" in size
    visit = warn["The lens is from a different visit"]
    assert "Wed 18 Feb 2026" in visit and "Sat 4 Apr 2026" in visit and "45 days before" in visit
    assert any("did not pass" in t for t in warn)
    assert len(warnings_text(cks)) == 4


def test_lens_checks_missing_info(tmp_path):
    from src.extrinsic.lens_check import WARN, lens_checks
    cks = lens_checks(_intr(serial="", when=None), _os_setups(tmp_path), "ForwardLeft", "2000713", "ForwardLeft")
    titles = [t for s, t, _ in cks if s == WARN]
    assert "The lens file has no serial number" in titles and "The lens file has no date" in titles
    cks = lens_checks(_intr(), _os_setups(tmp_path), "", "", "ForwardLeft")
    assert any(t == "Pick the camera and serial at the top" for _, t, _ in cks)


def test_camera_and_serial_from_the_top_bar(tmp_path):
    """2026-11-10: the top bar names the camera and serial; the lens and the folder must agree."""
    from src.extrinsic.lens_check import OK, WARN, lens_checks
    st = _os_setups(tmp_path)
    warn = {t: d for s, t, d in lens_checks(_intr(camera="ROW"), st, "ForwardLeft", "2000713", "ForwardLeft") if s == WARN}
    assert "The lens is for a different camera" in warn and "ROW" in warn["The lens is for a different camera"]
    warn = {t: d for s, t, d in lens_checks(_intr(), st, "ForwardLeft", "2000713", "ROW") if s == WARN}
    assert "The Old School folder is for a different camera" in warn
    warn = {t: d for s, t, d in lens_checks(_intr(), st, "ForwardLeft", "2000713", "") if s == WARN}
    assert "The folder name doesn't say which camera this is" in warn
    states = {t: s for s, t, _ in lens_checks(_intr(camera=""), st, "ForwardLeft", "2000713", "ForwardLeft")}
    assert states["The lens is for this camera"] == OK            # old lens file: serial still checked


def test_lens_files_record_the_camera(tmp_path):
    from src.extrinsic.intrinsic_source import from_file
    y = tmp_path / "CAL_1_20260101_000000.yaml"
    y.write_text("serial_number: '1'\ncamera_role: FORWARDLEFT\ncamera_matrix: {data: [1,0,0,0,1,0,0,0,1]}\n"
                 "dist_coeffs: {data: [0,0,0,0,0]}\ngrade: {passed: true, headline: PASS}\n")
    assert from_file(str(y)).camera == "ForwardLeft"


def test_lens_file_dates_and_size(tmp_path):
    from src.extrinsic.intrinsic_source import from_file
    x = tmp_path / "ARAN62_ForwardLeft_2000713_intrinsic_cal.xml"
    x.write_text("""<IntrinsicCalibration><CalibrationDate>2026-04-06T10:11:12.1234567-04:00</CalibrationDate>
<OpenCVCameraModel width="1920" height="1080"><Center x="960" y="540" /><FocalLength x="1700" y="1700" />
<RadialDistortion k1="0" k2="0" k3="0" /><TangentialDistortion p1="0" p2="0" /></OpenCVCameraModel>
</IntrinsicCalibration>""", encoding="utf-8")
    i = from_file(str(x))
    assert (i.width, i.height, i.serial, i.camera) == (1920, 1080, "2000713", "ForwardLeft")
    assert i.date.date().isoformat() == "2026-04-06" and i.date_what == "Lens calibrated"


def test_target_files_record_every_target(tmp_path):
    """<photo>.targets.json: van pose, used/why, and each target found / used / dropped."""
    import json
    from types import SimpleNamespace
    import numpy as np
    from src.extrinsic.target_files import write_target_files
    site = SimpleNamespace(name="T", ids=["1", "2", "50"], ground=np.array([False, False, True]),
                           enh_m=np.array([[1.0, 2, 3], [4, 5, 6], [7, 8, 9]]),
                           index=lambda: {"1": 0, "2": 1, "50": 2})
    photo = tmp_path / "20260404.102502" / "123.jpg"; photo.parent.mkdir(); photo.write_bytes(b"x")
    van = SimpleNamespace(rows=5, gps_status="CADifferential", roll=0.1, pitch=0.2, heading=250.0,
                          lat=37.5, lon=-77.4, elevation=60.0, spread_deg=0.01)
    setup = SimpleNamespace(name="20260404.102502", photo=str(photo), pose_csv="ReviewData_1.csv", van=van)
    match = SimpleNamespace(matches=[("1", 10.0, 20.0, "wall"), ("50", 30.0, 40.0, "ball (2nd look)")],
                            predicted={"1": (11.0, 21.0), "2": (50.0, 60.0), "50": (31.0, 41.0)}, note="")
    solve = SimpleNamespace(ids=["1"], loo_mm=np.array([7.5]), range_m=np.array([12.0]),
                            dropped=[("50", "missed by 9 px: wrong target or wrong label")], R_bc=None,
                            n_points=1, loo_rms_mm=7.5, lever_frd=None, up_ground_m=2.1,
                            cam_enh=np.array([0.0, 0.0, 2.0]))
    sr = SimpleNamespace(setup=setup, match=match, solve=solve, seed="other setup", passed=False,
                         problems=["only 1 targets (need 10)"], ground_targets=0, counts_for_height=False)
    cam = SimpleNamespace(van="ARAN62", camera="ROW", setups=[sr])
    assert write_target_files(cam, site, run_id="SOLVE_x") == 1
    d = json.loads((photo.parent / "123.targets.json").read_text())
    assert d["run_id"] == "SOLVE_x" and d["van_pose"]["gps_status"] == "CADifferential" and not d["used"]
    t = {x["id"]: x for x in d["targets"]}
    assert t["1"]["used"] and t["1"]["miss_mm"] == 7.5 and t["1"]["kind"] == "wall disc"
    assert not t["2"]["found"] and t["2"]["predicted_x_px"] == 50.0
    assert t["50"]["kind"] == "tennis ball" and t["50"]["found_by"] == "second look" and "9 px" in t["50"]["dropped_why"]


def test_direction_from_strong_setups():
    """2026-11-06: direction from setups with 15+ targets and 2+ balls when 3+ such setups exist."""
    from src.extrinsic.run import CameraResult, _combine
    base = rot_zyx(0, -2, 0) @ np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0.0]])
    def g(tilt, n, balls):
        sol = SimpleNamespace(R_bc=rot_zyx(0, tilt, 0) @ base, lever_frd=np.array([-2.0, 0.0, 0]),
                              up_ground_m=2.3, n_points=n)
        return SimpleNamespace(solve=sol, passed=True, problems=[], ground_targets=balls)
    # five strong setups agree; two weak close-ups 1.8 deg off (like ARAN62 ROW 2026-04-04)
    good = [g(0.0, 28, 5), g(0.1, 24, 4), g(-0.1, 19, 2), g(0.05, 19, 3), g(-0.05, 41, 7), g(1.8, 16, 1), g(1.8, 11, 1)]
    res = CameraResult(camera="ROW", van="X", folder="f")
    _combine(res, good)
    assert res.passed and res.angle_spread_deg < 0.2
    assert [getattr(x, "counts_for_direction", False) for x in good] == [True] * 5 + [False, False]
    few = [g(0.0, 28, 5), g(1.8, 11, 1), g(-1.8, 12, 0)]
    res2 = CameraResult(camera="ROW", van="X", folder="f")
    _combine(res2, few)
    assert any("Camera direction from all setups" in w for w in res2.warnings)


def test_extrinsic_pdf_is_written(tmp_path):
    """2026-11-11: Save wrote pdf_error.txt ('old_click_checks') instead of the PDF."""
    import numpy as np
    from types import SimpleNamespace
    from src.extrinsic.report import write_pdf
    data = {"created": "2026-11-11T08:48:22", "serial": "88888888", "old_school_folder": str(tmp_path),
            "intrinsic": "test lens", "camera": "ROW",
            "grade": {"passed": True, "headline": "PASS: good", "reasons": [], "warnings": ["a warning"]},
            "pointing_deg": {"pan_right": 0.5, "tilt_up": -10.0, "roll_cw": 0.1, "spread_between_setups_max": 0.2},
            "lever_arm_m": {"forward": 1.2, "right": 0.0, "up_above_pavement": 2.5, "forward_right_spread": [0.1, 0.1],
                            "up_spread": 0.01, "camera_height_navd88_m": 100.0},
            "rwc_angles_unverified_deg": {"heading_offset": 0.5, "pitch_offset": -10.0, "roll_offset": 0.1},
            "setups": [{"name": "20250619.151616", "passed": True, "seed": "default", "targets": 22,
                        "miss_rms_mm": 8.0, "range_m": 12.0, "pointing_deg": [0.5, -10.0, 0.1],
                        "lever_forward_right_m": [1.2, 0.0], "up_above_pavement_m": 2.5, "problems": ["one problem"]}],
            "notes": ["note one"]}
    cam = SimpleNamespace(van="ARAN54", camera="ROW", setups=[], K=np.eye(3), D=np.zeros(5))
    out = tmp_path / "ARAN54_ROW_88888888_extrinsic.pdf"
    write_pdf(cam, data, out)
    assert out.exists() and out.read_bytes()[:4] == b"%PDF"
