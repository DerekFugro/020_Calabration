"""test_calibrator.py — Unit tests for the Phase 2 calibration engine.

Covers:
  - BoardConfig.get_all_object_points() shape, dtype, spacing
  - image_filter.filter_detection() acceptance / rejection logic
  - quality.evaluate() verdict thresholds and pass/fail logic
  - calibrator.calibrate() with synthetic point data
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.board import BoardConfig, DEFAULT_CELL_WIDTH_MM, DEFAULT_CELL_HEIGHT_MM
from src.detector import DetectionResult
from src.image_filter import filter_detection, filter_detections, MIN_CORNERS, MIN_BLUR_SCORE
from src.calibrator import CalibrationResult, calibrate
from src.quality import (
    evaluate,
    VERDICT_EXCELLENT,
    VERDICT_ACCEPTABLE,
    VERDICT_NEEDS_IMPROVEMENT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detection(
    corner_count: int = 20,
    blur_score: float = 200.0,
    load_error: bool = False,
    image_size: tuple[int, int] = (3840, 2160),
) -> DetectionResult:
    """Construct a synthetic DetectionResult for testing."""
    if load_error or corner_count == 0:
        return DetectionResult(
            image_path="fake.jpg",
            image_size=image_size,
            charuco_corners=None,
            charuco_ids=None,
            corner_count=0,
            blur_score=blur_score,
            load_error=load_error,
            load_error_msg="simulated load error" if load_error else "",
        )

    corners = np.zeros((corner_count, 1, 2), dtype=np.float32)
    ids = np.arange(corner_count, dtype=np.int32).reshape(-1, 1)
    return DetectionResult(
        image_path="fake.jpg",
        image_size=image_size,
        charuco_corners=corners,
        charuco_ids=ids,
        corner_count=corner_count,
        blur_score=blur_score,
    )


def _make_cal_result(rms: float, image_count: int = 20) -> CalibrationResult:
    """Construct a synthetic CalibrationResult for quality testing."""
    return CalibrationResult(
        camera_matrix=np.eye(3, dtype=np.float64),
        dist_coeffs=np.zeros((1, 5), dtype=np.float64),
        rms=rms,
        rvecs=[],
        tvecs=[],
        image_count_used=image_count,
        image_size=(3840, 2160),
    )


# ---------------------------------------------------------------------------
# BoardConfig.get_all_object_points
# ---------------------------------------------------------------------------

class TestBoardObjectPoints:

    def test_default_shape(self):
        cfg = BoardConfig()
        pts = cfg.get_all_object_points()
        expected = (cfg.squares_x - 1) * (cfg.squares_y - 1)
        assert pts.shape == (expected, 3), (
            f"Expected ({expected}, 3), got {pts.shape}"
        )

    def test_default_values(self):
        """Default board: 12×8 → 11×7 = 77 corners."""
        cfg = BoardConfig()
        pts = cfg.get_all_object_points()
        assert pts.shape[0] == 77

    def test_dtype_is_float32(self):
        pts = BoardConfig().get_all_object_points()
        assert pts.dtype == np.float32

    def test_z_column_is_zero(self):
        pts = BoardConfig().get_all_object_points()
        assert np.all(pts[:, 2] == 0.0)

    def test_first_corner_at_origin(self):
        pts = BoardConfig().get_all_object_points()
        assert pts[0, 0] == pytest.approx(0.0)
        assert pts[0, 1] == pytest.approx(0.0)

    def test_x_spacing_equals_cell_width(self):
        """Adjacent corners in the same row differ by cell_width_mm in X.

        Deliberately unrealistic 50 x 30 values: the point is that X and Y
        spacing are independent, and using the real board's numbers here would
        prove nothing.  (These were once 76.46 x 75.99 — the DEAD superseded
        cell sizes — which risked someone copying them back into the app.)
        """
        cfg = BoardConfig(cell_width_mm=50.0, cell_height_mm=30.0)
        pts = cfg.get_all_object_points()
        # Corner 0 → col=0, row=0; Corner 1 → col=1, row=0
        assert pts[1, 0] == pytest.approx(cfg.cell_width_mm)
        assert pts[1, 1] == pytest.approx(pts[0, 1])

    def test_y_spacing_equals_cell_height(self):
        """First corner of the second row differs by cell_height_mm in Y."""
        cfg = BoardConfig(cell_width_mm=50.0, cell_height_mm=30.0)
        pts = cfg.get_all_object_points()
        n_cols = cfg.squares_x - 1
        assert pts[n_cols, 1] == pytest.approx(cfg.cell_height_mm)
        assert pts[n_cols, 0] == pytest.approx(pts[0, 0])

    def test_non_square_cells_differ(self):
        """Default cells are square at the MEASURED 76.39 mm.

        Calipers, 2026-08-18: 152.78 mm across two cells -> 76.39 mm pitch
        (3.0075", so the print ran 0.25% over its nominal 3.000").  The old
        76.2 was the assumed nominal and was never measured.

        Squareness is the property that matters — only the width/height ratio
        reaches the intrinsics.  Non-square boards remain supported via explicit
        cell_width_mm/cell_height_mm, covered by the spacing tests above.
        See references/BoardTrueSize.md."""
        cfg = BoardConfig()
        assert cfg.cell_width_mm == pytest.approx(76.39)
        assert cfg.cell_height_mm == pytest.approx(76.39)
        assert cfg.cell_width_mm == cfg.cell_height_mm

    def test_id_indexing_selects_correct_point(self):
        """Indexing by corner ID must return the correct 3D point."""
        cfg = BoardConfig()
        all_pts = cfg.get_all_object_points()
        # Corner ID 12 (col=1, row=1 on 12×8 board: cols=11, so ID 11 = row 1 col 0)
        n_cols = cfg.squares_x - 1
        test_id = n_cols + 2   # row=1, col=2
        expected_x = 2 * cfg.cell_width_mm
        expected_y = 1 * cfg.cell_height_mm
        assert all_pts[test_id, 0] == pytest.approx(expected_x)
        assert all_pts[test_id, 1] == pytest.approx(expected_y)


# ---------------------------------------------------------------------------
# image_filter.filter_detection
# ---------------------------------------------------------------------------

class TestImageFilter:

    def test_accepted_with_good_values(self):
        det = _make_detection(corner_count=20, blur_score=200.0)
        result = filter_detection(det)
        assert result.accepted is True
        assert result.reason == ""

    def test_rejected_load_error(self):
        det = _make_detection(load_error=True)
        result = filter_detection(det)
        assert result.accepted is False
        assert "load error" in result.reason.lower()

    def test_rejected_zero_corners(self):
        det = _make_detection(corner_count=0, blur_score=200.0)
        result = filter_detection(det)
        assert result.accepted is False
        assert "corner" in result.reason.lower()

    def test_rejected_too_few_corners(self):
        det = _make_detection(corner_count=MIN_CORNERS - 1, blur_score=200.0)
        result = filter_detection(det)
        assert result.accepted is False
        assert "corner" in result.reason.lower()

    def test_accepted_at_exact_min_corners(self):
        det = _make_detection(corner_count=MIN_CORNERS, blur_score=200.0)
        result = filter_detection(det)
        assert result.accepted is True

    def test_rejected_blurry(self):
        det = _make_detection(corner_count=20, blur_score=MIN_BLUR_SCORE - 1.0)
        result = filter_detection(det)
        assert result.accepted is False
        assert "blur" in result.reason.lower()

    def test_accepted_at_exact_blur_threshold(self):
        det = _make_detection(corner_count=20, blur_score=MIN_BLUR_SCORE)
        result = filter_detection(det)
        assert result.accepted is True

    def test_blur_checked_after_corners(self):
        """Corner check must run before blur check (order matters for rejection reason)."""
        det = _make_detection(corner_count=2, blur_score=10.0)
        result = filter_detection(det)
        assert "corner" in result.reason.lower()

    def test_custom_thresholds(self):
        det = _make_detection(corner_count=30, blur_score=50.0)
        # Tighten blur threshold above 50 — should reject
        assert filter_detection(det, min_blur=200.0).accepted is False
        # Relax it — should accept
        assert filter_detection(det, min_blur=10.0).accepted is True

    def test_filter_detections_batch(self):
        dets = [
            _make_detection(corner_count=20, blur_score=200.0),
            _make_detection(corner_count=2,  blur_score=200.0),
            _make_detection(corner_count=20, blur_score=5.0),
        ]
        results = filter_detections(dets)
        assert len(results) == 3
        assert results[0].accepted is True
        assert results[1].accepted is False
        assert results[2].accepted is False


# ---------------------------------------------------------------------------
# quality.evaluate
# ---------------------------------------------------------------------------

class TestQualityVerdicts:

    def test_verdict_excellent(self):
        report = evaluate(_make_cal_result(0.3))
        assert report.verdict == VERDICT_EXCELLENT

    def test_verdict_excellent_boundary(self):
        """RMS just below 0.5 → Excellent."""
        report = evaluate(_make_cal_result(0.499))
        assert report.verdict == VERDICT_EXCELLENT

    def test_verdict_acceptable_at_threshold(self):
        """RMS exactly 0.5 → Acceptable (not Excellent)."""
        report = evaluate(_make_cal_result(0.5))
        assert report.verdict == VERDICT_ACCEPTABLE

    def test_verdict_acceptable_midrange(self):
        report = evaluate(_make_cal_result(0.7))
        assert report.verdict == VERDICT_ACCEPTABLE

    def test_verdict_acceptable_at_upper_boundary(self):
        """RMS exactly 1.0 → Acceptable (not Needs Improvement)."""
        report = evaluate(_make_cal_result(1.0))
        assert report.verdict == VERDICT_ACCEPTABLE

    def test_verdict_needs_improvement(self):
        report = evaluate(_make_cal_result(1.2))
        assert report.verdict == VERDICT_NEEDS_IMPROVEMENT

    def test_pass_verdict_requires_min_images(self):
        report = evaluate(_make_cal_result(0.3, image_count=10), min_images=15)
        assert report.pass_verdict is False

    def test_pass_verdict_with_sufficient_images(self):
        report = evaluate(_make_cal_result(0.3, image_count=20), min_images=15)
        assert report.pass_verdict is True

    def test_pass_verdict_false_when_rms_too_high(self):
        report = evaluate(_make_cal_result(1.2, image_count=20), min_images=15)
        assert report.pass_verdict is False

    def test_report_has_message(self):
        report = evaluate(_make_cal_result(0.3))
        assert isinstance(report.message, str)
        assert len(report.message) > 0

    def test_needs_improvement_message_contains_advice(self):
        report = evaluate(_make_cal_result(1.5, image_count=20))
        assert "1.0" in report.message or "RMS" in report.message


# ---------------------------------------------------------------------------
# calibrator.calibrate — synthetic round-trip
# ---------------------------------------------------------------------------

class TestCalibratorSynthetic:
    """
    Build a minimal synthetic dataset: a single flat board with known object
    points projected through a known camera.  After calibration the recovered
    RMS should be very small and the camera matrix should be close to the
    synthetic ground truth.

    This intentionally exercises calibrate() with the full data pipeline
    (board.py object points, detector-shaped inputs) rather than relying on
    real images.
    """

    @pytest.fixture(autouse=True)
    def _build_data(self):
        """Create synthetic object+image point data for 5 'images'."""
        cfg = BoardConfig()
        self.cfg = cfg

        # Synthetic camera matrix — typical 4K camera
        self.W, self.H = 3840, 2160
        fx = fy = 3500.0
        cx, cy = self.W / 2.0, self.H / 2.0
        self.K_true = np.array(
            [[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64
        )
        self.D_true = np.zeros((1, 5), dtype=np.float64)

        all_pts = cfg.get_all_object_points()
        # Use first 20 corner IDs only (simulates partial board view)
        n = 20
        self.ids_used = np.arange(n, dtype=np.int32)
        obj_pts_single = all_pts[self.ids_used]  # (20, 3)

        # Project through 5 slightly different poses
        self.detections: list[DetectionResult] = []
        self.filter_results = []

        from src.image_filter import FilterResult

        for i in range(5):
            angle = np.deg2rad(10 * (i - 2))          # -20° to +20°
            rvec = np.array([[angle], [0.0], [0.0]])
            tvec = np.array([[0.0], [0.0], [600.0]])   # 600 mm in front

            img_pts, _ = cv2.projectPoints(
                obj_pts_single, rvec, tvec, self.K_true, self.D_true
            )
            # img_pts has shape (20, 1, 2) — matches detector output

            det = DetectionResult(
                image_path=f"synthetic_{i}.jpg",
                image_size=(self.W, self.H),
                charuco_corners=img_pts.astype(np.float32),
                charuco_ids=self.ids_used.reshape(-1, 1),
                corner_count=n,
                blur_score=500.0,
            )
            self.detections.append(det)
            self.filter_results.append(
                FilterResult(accepted=True, reason="", corner_count=n, blur_score=500.0)
            )

    def test_calibrate_runs(self):
        result = calibrate(self.detections, self.filter_results, self.cfg)
        assert isinstance(result, CalibrationResult)

    def test_rms_is_small(self):
        result = calibrate(self.detections, self.filter_results, self.cfg)
        assert result.rms < 1.0, f"Expected RMS < 1.0, got {result.rms:.4f}"

    def test_image_count_matches(self):
        result = calibrate(self.detections, self.filter_results, self.cfg)
        assert result.image_count_used == 5

    def test_camera_matrix_shape(self):
        result = calibrate(self.detections, self.filter_results, self.cfg)
        assert result.camera_matrix.shape == (3, 3)

    def test_dist_coeffs_shape(self):
        result = calibrate(self.detections, self.filter_results, self.cfg)
        assert result.dist_coeffs.shape[1] in (4, 5, 8, 12, 14)

    def test_focal_lengths_reasonable(self):
        result = calibrate(self.detections, self.filter_results, self.cfg)
        fx = result.camera_matrix[0, 0]
        fy = result.camera_matrix[1, 1]
        # Should be in the same ballpark as the synthetic fx/fy=3500
        assert 1000.0 < fx < 8000.0, f"Unexpected fx: {fx}"
        assert 1000.0 < fy < 8000.0, f"Unexpected fy: {fy}"

    def test_raises_with_too_few_images(self):
        with pytest.raises(ValueError, match="(?i)calibration"):
            calibrate(self.detections[:1], self.filter_results[:1], self.cfg)

    def test_filtered_images_excluded(self):
        from src.image_filter import FilterResult
        # Mark all as rejected
        rejected = [
            FilterResult(accepted=False, reason="test", corner_count=20, blur_score=200.0)
            for _ in self.filter_results
        ]
        with pytest.raises(ValueError):
            calibrate(self.detections, rejected, self.cfg)
