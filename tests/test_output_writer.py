"""test_output_writer.py — Tests for Phase 3 output file generation.

Covers:
  - Correct filename format for both YAML and PDF
  - Collision avoidance: second write with same timestamp appends _2
  - YAML content: all required keys present, values round-trip correctly
  - PDF: file is created and non-zero bytes
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
import yaml

from src.board import BoardConfig
from src.calibrator import CalibrationResult
from src.detector import DetectionResult
from src.image_filter import FilterResult
from src.output_writer import write_yaml, write_pdf, write_outputs, _make_stem, _unique_path


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def cfg():
    return BoardConfig()


@pytest.fixture
def cal():
    return CalibrationResult(
        camera_matrix=np.array(
            [[3521.4, 0.0, 1923.1],
             [0.0, 3519.8, 1081.6],
             [0.0, 0.0,    1.0]],
            dtype=np.float64,
        ),
        dist_coeffs=np.array([[0.12, -0.34, 0.001, -0.002, 0.05]], dtype=np.float64),
        rms=0.412,
        rvecs=[],
        tvecs=[],
        image_count_used=18,
        image_size=(3840, 2160),
    )


@pytest.fixture
def detections():
    return [
        DetectionResult("img001.jpg", (3840, 2160), None, None, 40, 350.0),
        DetectionResult("img002.jpg", (3840, 2160), None, None,  3, 350.0),
        DetectionResult("img003.jpg", (3840, 2160), None, None, 40,  30.0),
        DetectionResult("a_very_long_filename_that_exceeds_normal_limits_0042.jpg",
                        (3840, 2160), None, None, 40, 400.0),
    ]


@pytest.fixture
def filters():
    return [
        FilterResult(True,  "",                              40, 350.0),
        FilterResult(False, "Too few corners detected (3 < 6)", 3, 350.0),
        FilterResult(False, "Image too blurry (blur score 30.0 < 100.0)", 40, 30.0),
        FilterResult(True,  "",                              40, 400.0),
    ]


_DT = datetime(2026, 6, 9, 14, 30, 0)
_SERIAL = "SN42"
_YAML_STEM = "CAL_SN42_20260609_143000"
_PDF_STEM  = "CAL_SN42_20260609_143000"


# ── _make_stem ────────────────────────────────────────────────────────────────

def test_make_stem_format():
    stem = _make_stem("ABC123", datetime(2026, 1, 15, 9, 5, 3))
    assert stem == "CAL_ABC123_20260115_090503"


def test_make_stem_pads_zeros():
    stem = _make_stem("X", datetime(2026, 1, 1, 0, 0, 0))
    assert stem == "CAL_X_20260101_000000"


# ── _unique_path ──────────────────────────────────────────────────────────────

def test_unique_path_no_collision(tmp_path):
    p = _unique_path(tmp_path, "CAL_X_20260101_000000", ".yaml")
    assert p.name == "CAL_X_20260101_000000.yaml"
    assert not p.exists()


def test_unique_path_one_collision(tmp_path):
    (tmp_path / "CAL_X_20260101_000000.yaml").touch()
    p = _unique_path(tmp_path, "CAL_X_20260101_000000", ".yaml")
    assert p.name == "CAL_X_20260101_000000_2.yaml"


def test_unique_path_two_collisions(tmp_path):
    (tmp_path / "CAL_X_20260101_000000.yaml").touch()
    (tmp_path / "CAL_X_20260101_000000_2.yaml").touch()
    p = _unique_path(tmp_path, "CAL_X_20260101_000000", ".yaml")
    assert p.name == "CAL_X_20260101_000000_3.yaml"


# ── write_yaml — filename ────────────────────────────────────────────────────

def test_yaml_filename_format(cal, cfg, tmp_path):
    p = write_yaml(cal, cfg, _SERIAL, tmp_path, _DT)
    assert p.name == f"{_YAML_STEM}.yaml"


def test_yaml_file_created(cal, cfg, tmp_path):
    p = write_yaml(cal, cfg, _SERIAL, tmp_path, _DT)
    assert p.exists()


def test_yaml_no_overwrite_on_collision(cal, cfg, tmp_path):
    p1 = write_yaml(cal, cfg, _SERIAL, tmp_path, _DT)
    p2 = write_yaml(cal, cfg, _SERIAL, tmp_path, _DT)
    assert p1 != p2
    assert p2.name == f"{_YAML_STEM}_2.yaml"
    assert p1.exists()
    assert p2.exists()


# ── write_yaml — content ─────────────────────────────────────────────────────

@pytest.fixture
def parsed_yaml(cal, cfg, tmp_path):
    p = write_yaml(cal, cfg, _SERIAL, tmp_path, _DT)
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class TestYamlContent:

    required_keys = [
        "serial_number",
        "calibration_datetime",
        "rms_reprojection_error",
        "image_count_used",
        "camera_matrix",
        "dist_coeffs",
        "image_resolution",
        "board",
    ]

    def test_all_required_keys_present(self, parsed_yaml):
        for key in self.required_keys:
            assert key in parsed_yaml, f"Missing key: {key}"

    def test_serial_number(self, parsed_yaml):
        assert parsed_yaml["serial_number"] == _SERIAL

    def test_datetime_format(self, parsed_yaml):
        # Should be ISO format string
        assert parsed_yaml["calibration_datetime"] == "2026-06-09T14:30:00"

    def test_rms_is_float(self, parsed_yaml):
        assert isinstance(parsed_yaml["rms_reprojection_error"], float)
        assert pytest.approx(parsed_yaml["rms_reprojection_error"], abs=1e-4) == 0.412

    def test_image_count(self, parsed_yaml):
        assert parsed_yaml["image_count_used"] == 18

    def test_camera_matrix_structure(self, parsed_yaml):
        cm = parsed_yaml["camera_matrix"]
        assert cm["rows"] == 3
        assert cm["cols"] == 3
        assert isinstance(cm["data"], list)
        assert len(cm["data"]) == 9

    def test_camera_matrix_fx_value(self, parsed_yaml):
        data = parsed_yaml["camera_matrix"]["data"]
        assert pytest.approx(data[0], abs=0.01) == 3521.4   # fx at [0,0]

    def test_dist_coeffs_structure(self, parsed_yaml):
        dc = parsed_yaml["dist_coeffs"]
        assert dc["rows"] == 1
        assert dc["cols"] == 5
        assert isinstance(dc["data"], list)
        assert len(dc["data"]) == 5

    def test_image_resolution(self, parsed_yaml):
        res = parsed_yaml["image_resolution"]
        assert res["width"] == 3840
        assert res["height"] == 2160

    def test_board_keys(self, parsed_yaml):
        board = parsed_yaml["board"]
        for key in ("squares_x", "squares_y", "cell_width_mm",
                    "cell_height_mm"):
            assert key in board, f"board.{key} missing"

    def test_board_squares(self, parsed_yaml):
        assert parsed_yaml["board"]["squares_x"] == 12
        assert parsed_yaml["board"]["squares_y"] == 8

    def test_board_omits_dead_aruco_fields(self, parsed_yaml):
        """Detection is plain chessboard — these describe a path that never runs.

        marker_size_mm was never measured (a default that reads like data) and
        aruco_dict names a module the calibration path does not call.
        """
        board = parsed_yaml["board"]
        assert "aruco_dict" not in board
        assert "marker_size_mm" not in board

    def test_board_keeps_cell_size(self, parsed_yaml):
        """Cell size stays: it is how a superseded 76.465 x 76.002 run is spotted.

        76.39 is the measured pitch (calipers 2026-08-18); 76.2 was the assumed
        nominal.  Both are square, so both give identical intrinsics."""
        assert parsed_yaml["board"]["cell_width_mm"] == 76.39
        assert parsed_yaml["board"]["cell_height_mm"] == 76.39


# ── write_pdf — filename and content ─────────────────────────────────────────

def test_pdf_filename_format(cal, cfg, detections, filters, tmp_path):
    p = write_pdf(cal, cfg, _SERIAL, detections, filters, tmp_path, _DT)
    assert p.name == f"{_PDF_STEM}.pdf"


def test_pdf_file_created(cal, cfg, detections, filters, tmp_path):
    p = write_pdf(cal, cfg, _SERIAL, detections, filters, tmp_path, _DT)
    assert p.exists()


def test_pdf_non_zero_bytes(cal, cfg, detections, filters, tmp_path):
    p = write_pdf(cal, cfg, _SERIAL, detections, filters, tmp_path, _DT)
    assert p.stat().st_size > 1024, "PDF is suspiciously small"


def test_pdf_no_overwrite_on_collision(cal, cfg, detections, filters, tmp_path):
    p1 = write_pdf(cal, cfg, _SERIAL, detections, filters, tmp_path, _DT)
    p2 = write_pdf(cal, cfg, _SERIAL, detections, filters, tmp_path, _DT)
    assert p1 != p2
    assert p2.name == f"{_PDF_STEM}_2.pdf"
    assert p1.exists() and p2.exists()


def test_pdf_starts_with_pdf_magic(cal, cfg, detections, filters, tmp_path):
    """All valid PDFs begin with %PDF."""
    p = write_pdf(cal, cfg, _SERIAL, detections, filters, tmp_path, _DT)
    header = p.read_bytes()[:5]
    assert header == b"%PDF-", f"Bad PDF header: {header!r}"


def test_pdf_not_passed_renders(cfg, detections, filters, tmp_path):
    """A calibration with no grade (or NOT PASSED) still produces a valid PDF."""
    bad_cal = CalibrationResult(
        camera_matrix=np.eye(3, dtype=np.float64) * 3500.0,
        dist_coeffs=np.zeros((1, 5), dtype=np.float64),
        rms=1.8,
        rvecs=[], tvecs=[],
        image_count_used=8,
        image_size=(3840, 2160),
    )
    p = write_pdf(bad_cal, cfg, "FAIL01", detections, filters, tmp_path, _DT)
    assert p.exists()
    assert p.stat().st_size > 1024


# ── write_outputs — shared timestamp ─────────────────────────────────────────

def test_write_outputs_returns_two_paths(cal, cfg, detections, filters, tmp_path):
    yaml_p, pdf_p = write_outputs(cal, cfg, _SERIAL, detections, filters, tmp_path)
    assert yaml_p.suffix == ".yaml"
    assert pdf_p.suffix == ".pdf"
    assert yaml_p.exists()
    assert pdf_p.exists()


def test_write_outputs_same_timestamp(cal, cfg, detections, filters, tmp_path):
    """Both files must share the same CAL_<serial>_<timestamp> stem."""
    yaml_p, pdf_p = write_outputs(cal, cfg, _SERIAL, detections, filters, tmp_path)
    yaml_ts = yaml_p.stem  # e.g. CAL_SN42_20260609_143000
    pdf_ts  = pdf_p.stem
    assert yaml_ts == pdf_ts, (
        f"Timestamp mismatch: {yaml_ts} vs {pdf_ts}"
    )


def test_dot_files_beside_each_photo(tmp_path):
    """Save writes <photo>.dots.json: status, dot numbers, px, board mm and fit."""
    import json
    from types import SimpleNamespace
    import cv2
    import numpy as np
    from src.dot_files import write_dot_files
    obj = np.array([[x * 30.0, y * 30.0, 0] for y in range(6) for x in range(8)], np.float32)
    board = SimpleNamespace(name="testboard", get_all_object_points=lambda: obj)
    K = np.array([[1000.0, 0, 960], [0, 1000.0, 540], [0, 0, 1]]); D = np.zeros(5)
    dets, filts, used = [], [], []
    for k in range(3):
        p = tmp_path / f"img{k}.jpg"; p.write_bytes(b"x")
        rv, tv = np.array([0.1 * k, 0.05, 0.0]), np.array([-100.0, -80.0, 600.0 + 50 * k])
        img, _ = cv2.projectPoints(obj, rv, tv, K, D)
        ids = np.arange(len(obj)).reshape(-1, 1)
        dets.append(SimpleNamespace(image_path=str(p), image_size=(1920, 1080), charuco_ids=ids,
                                    charuco_corners=img.astype(np.float32), load_error=False,
                                    load_error_msg="", edge_blur_px=1.2))
        filts.append(SimpleNamespace(accepted=k < 2, reason="" if k < 2 else "Too blurry"))
        if k == 0:
            used.append((str(p), obj, img.reshape(-1, 2)))
    cal = SimpleNamespace(camera_matrix=K, dist_coeffs=D, points_used=used,
                          auto_removed=[(str(tmp_path / "img1.jpg"), "fits far worse than the rest")])
    assert write_dot_files(cal, board, dets, filts) == 3
    d0 = json.loads((tmp_path / "img0.dots.json").read_text())
    assert d0["status"] == "used" and d0["dots_found"] == 48 and d0["dots"][9]["n"] == 9
    assert d0["dots"][9]["board_x_mm"] == 30.0 and d0["fit_rms_px"] < 0.01
    d1 = json.loads((tmp_path / "img1.dots.json").read_text())
    assert d1["status"] == "left out automatically" and "worse" in d1["why"]
    d2 = json.loads((tmp_path / "img2.dots.json").read_text())
    assert d2["status"] == "not used" and d2["why"] == "Too blurry"
