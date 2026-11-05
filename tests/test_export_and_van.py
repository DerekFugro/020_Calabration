"""Tests for src/export_formats.py and src/van_scan.py."""
import json
import xml.etree.ElementTree as ET
from datetime import datetime

import cv2
import numpy as np
import pytest

from src.export_formats import FORMATS, Intrinsics, export_all, fleet_xml, pg_rwc
from src.van_scan import camera_from_name, read_filed_xml, scan, van_from_path


def _c(passed=True):
    return Intrinsics(van="ARAN65", camera="ForwardRight", serial="101324", width=1920,
                      height=1080, fx=1533.27, fy=1533.50, cx=939.32, cy=557.86,
                      k1=-0.0147, k2=0.2055, p1=0.00148, p2=0.00105, k3=-0.2323,
                      rms_px=0.51, passed=passed, date=datetime(2026, 11, 1, 9, 5))


def test_fleet_xml_round_trips(tmp_path):
    p = tmp_path / "a.xml"; p.write_text(fleet_xml(_c()))
    f = read_filed_xml(str(p))
    assert f["fx"] == pytest.approx(1533.27) and f["cy"] == pytest.approx(557.86)
    assert f["p2"] == pytest.approx(0.00105) and f["width"] == 1920
    assert ET.parse(p).getroot().find("VehicleName").text == "ARAN65"


def test_pg_rwc_matches_old_layout():
    hdr, row = pg_rwc(_c()).split("\r\n")
    h, v = hdr.split(","), row.split(",")
    assert len(h) == len(v) == 14 and h[0] == "IDPGInteriorCalibration"
    d = dict(zip(h, v))
    assert d["EffectiveDate"] == "11/1/2026 9:05 AM"
    assert float(d["PixelWidth"]) == 0.0036
    assert float(d["RadialDistorsion3"]) == pytest.approx(-0.2323)
    assert float(d["TangentialDistorsion3"]) == 0


def test_opencv_files_load_in_opencv(tmp_path):
    files = export_all(_c(), tmp_path)
    for suffix in ("_opencv.yml", "_opencv.xml"):
        p = next(f for f in files if f.name.endswith(suffix))
        fs = cv2.FileStorage(str(p), cv2.FILE_STORAGE_READ)
        K = fs.getNode("camera_matrix").mat(); D = fs.getNode("distortion_coefficients").mat()
        fs.release()
        assert K[0, 0] == pytest.approx(1533.27) and K[1, 2] == pytest.approx(557.86)
        assert D.ravel()[4] == pytest.approx(-0.2323)


def test_export_all_writes_every_format_and_flags_failures(tmp_path):
    good = export_all(_c(True), tmp_path / "g")
    bad = export_all(_c(False), tmp_path / "b")
    assert len(good) == len(FORMATS) + 1          # + README
    assert all(p.name.startswith("NOT_PASSED_") for p in bad)
    assert not any(p.name.startswith("NOT_PASSED_") for p in good)
    j = json.loads(next(p for p in good if p.suffix == ".json").read_text())
    assert j["serial"] == "101324" and len(j["distortion_opencv"]) == 5


def test_metashape_swaps_tangential_and_centres():
    from src.export_formats import metashape_xml
    r = ET.fromstring(metashape_xml(_c()))
    assert float(r.find("p1").text) == pytest.approx(0.00105)
    assert float(r.find("cx").text) == pytest.approx(939.32 - 960)


@pytest.mark.parametrize("name,cam", [("ForwardRight", "ForwardRight"), ("FR", "ForwardRight"),
                                      ("Row", "ROW"), ("RL", "RearLeft"), ("Rear Right", "RearRight"),
                                      ("Images", "")])
def test_camera_from_name(name, cam):
    assert camera_from_name(name) == cam


def test_van_from_path():
    assert van_from_path(r"F:\x\20260403_Aran 68_Surveyor\Intrinsic") == "ARAN68"
    assert van_from_path("/a/20251207_ARAN_62_SC26/b") == "ARAN62"
    assert van_from_path("/a/b") == ""


def test_scan_finds_camera_and_serial(tmp_path):
    img = np.zeros((20, 20, 3), np.uint8)
    base = tmp_path / "20260213_ARAN65_LA26_Surveyor" / "Intrinsic" / "Images"
    for cam in ("ForwardRight", "RearLeft"):
        d = base / cam; d.mkdir(parents=True)
        for i in range(16):
            cv2.imwrite(str(d / f"{i:04d}.jpg"), img)
    (base / "ARAN65_ForwardRight_101324_intrinsic_cal.xml").write_text(fleet_xml(_c()))
    found = scan(str(tmp_path))
    assert [f.camera for f in found] == ["ForwardRight", "RearLeft"]
    assert found[0].serial == "101324" and found[0].van == "ARAN65" and found[0].filed_xml
    assert found[1].serial == "" and found[1].notes


def test_van_from_computer(monkeypatch):
    from src.van_scan import van_from_computer
    for name, van in (("ARAN69-SERVER", "ARAN69"), ("ARAN69-ROW", "ARAN69"), ("aran 62-row", "ARAN62"), ("DESKTOP-12AB", "")):
        monkeypatch.setenv("COMPUTERNAME", name)
        assert van_from_computer() == van, name


def test_photo_date_from_folder_name(tmp_path):
    from datetime import datetime
    from src.utils import FROM_FILES, FROM_FOLDER, date_from_path, photos_taken
    assert date_from_path(r"F:\x\AK26\ARAN62_2026-04-04\Intrinsic\ROW") == datetime(2026, 4, 4)
    assert date_from_path(r"F:\D\20260403_ARAN62_Surveyor_AK26\Intrinsic\FL") == datetime(2026, 4, 3)
    assert date_from_path(r"F:\a\20261399_bad\b") is None and date_from_path(r"F:\a\b") is None
    d = tmp_path / "20250619_ARAN54" / "ROW"; d.mkdir(parents=True)
    assert photos_taken(str(d))[2] == FROM_FOLDER
    e = tmp_path / "plain"; e.mkdir(); (e / "1.jpg").write_bytes(b"x")
    assert photos_taken(str(e))[2] == FROM_FILES
