"""Camera position reads SurveyorCapture's Old School folders (Phase 8, task 4):
<camera>/Position<N>/ with a few photos, the POS logger's CSV and Capture's log (rating)."""
import json
from datetime import datetime

from src.extrinsic import oldschool
from src.extrinsic.lens_check import setup_datetime

HEAD = ("time1_s,time_type,lat_deg,lon_deg,height_m,roll_deg,pitch_deg,heading_deg,speed_mps,"
        "align_status,rms_n_m,rms_e_m,rms_d_m,light,message\n")


def _pos_csv(path, heading=(359.9, 0.1)):
    rows = [f"{77346 + i * 0.02:.4f},UTC,37.605508635,-77.491835536,28.9058,0.30,0.23,{heading[i % 2]},0.0,0,"
            f"0.35,0.35,0.43,green,POS ready\n" for i in range(50)]
    path.write_text(HEAD + "".join(rows), encoding="utf-8")


def _position(cam, n, passed=True, best=1, reasons=("the van moved",)):
    p = cam / f"Position{n}"; p.mkdir(parents=True)
    photos = [f"ROW_20261115_1728{n:02d}_{k}00.jpg" for k in range(3)]
    for f in photos:
        (p / f).write_bytes(b"jpg")
    _pos_csv(p / f"{n:02d}_ROW_Position{n}.csv")
    log = {"camera": "ROW", "started": "2026-11-15T17:28:00", "photos": [{"file": f} for f in photos],
           "old_school": {"position": n, "rating": {"passed": passed, "reasons": [] if passed else list(reasons),
                                                    "best_photo": photos[best]}}}
    (p / "CAPTURE_20261115_172800.json").write_text(json.dumps(log), encoding="utf-8")
    return p, photos


def test_position_folders_are_read(tmp_path):
    site = tmp_path / "ExtrinsicAran59_20261115_172757"
    cam = site / "ROW"
    p1, ph1 = _position(cam, 1, best=2)
    _position(cam, 2, passed=False)
    _position(cam, 10)
    (site / "SurveyorPOS_20261115_172759").mkdir(parents=True)
    (site / "SurveyorPOS_20261115_172759" / "marks.csv").write_text("mark,label\n", encoding="utf-8")

    cams = oldschool.scan_old_school(str(cam))
    assert len(cams) == 1 and cams[0].camera == "ROW" and cams[0].van == "ARAN59"
    names = [s.name for s in cams[0].setups]
    assert names == ["Position1", "Position2", "Position10"]           # 2 before 10

    s1, s2, s10 = cams[0].setups
    assert s1.photo.endswith(ph1[2])                                    # the sharpest (the log's best_photo)
    assert s1.when == datetime(2026, 11, 15, 17, 28) and setup_datetime(s1) == s1.when
    v = s1.van
    assert v.source == "pos" and v.elevation_unit == "m" and v.rows == 50
    assert abs(v.lat - 37.605508635) < 1e-9 and abs(v.elevation - 28.9058) < 1e-9
    assert (v.roll, v.pitch) == (0.30, 0.23) and abs(((v.heading + 180) % 360) - 180) < 1e-6   # across north
    assert v.gps_status == "0" and not s1.problems and not s1.left_out
    assert v.spread_deg == 0.0 and abs(v.heading_spread_deg - 0.2) < 1e-6        # heading wander kept apart
    assert s2.left_out == "rated NOT PASSED when collected (the van moved)"
    assert not s10.left_out

    # the whole site folder works too (the POS recording folder has no photos: not a setup)
    assert [c.camera for c in oldschool.scan_old_school(str(site))] == ["ROW"]


def test_aran_csv_still_read_as_before(tmp_path):
    p = tmp_path / "ReviewData_1.csv"
    p.write_text("Roll,Pitch,Heading,Latitude,Longitude,Elevation,GPS Status\n"
                 "0.5,0.2,90.0,37.6,-77.5,94.8,12\n0.5,0.2,90.0,37.6,-77.5,94.8,12\n", encoding="utf-8")
    v = oldschool.read_van_pose(str(p))
    assert v.source == "aran" and v.elevation_unit == "ft" and v.gps_status == "12" and v.heading == 90.0


def test_left_out_position_is_not_solved(tmp_path):
    """run_camera never tries a position rated NOT PASSED, and says why."""
    import numpy as np
    from src.extrinsic.run import run_camera
    cam = tmp_path / "ExtrinsicAran59_20261115_172757" / "ROW"
    _position(cam, 1, passed=False, reasons=("the POS lost accuracy (Few satellites)",))
    cs = oldschool.scan_old_school(str(cam))[0]
    res = run_camera(cs, site=None, K=np.eye(3), D=np.zeros(5), seeds={})
    sr = res.setups[0]
    assert sr.solve is None and not sr.passed
    assert "left out: rated NOT PASSED when collected (the POS lost accuracy (Few satellites))" in sr.problems
