"""test_integration.py — End-to-end pipeline test using synthetic board images.

Generates a set of plain chessboard images via OpenCV, saves them to a temp
folder, then runs the full detect → filter → calibrate → write pipeline and
verifies that YAML and PDF output files are produced with the expected structure.
"""

from __future__ import annotations

import pathlib
import re

import cv2
import numpy as np
import pytest
import yaml

from src.board import BoardConfig
from src.calibrator import calibrate
from src.detector import detect_images
from src.image_filter import filter_detections
from src.output_writer import write_outputs


# ── Synthetic image generation ────────────────────────────────────────────────

def _make_chessboard_image(
    squares_x: int,
    squares_y: int,
    sq_px: int = 60,
    border_px: int = 40,
) -> np.ndarray:
    """Render a plain chessboard with a white border (required by findChessboardCorners)."""
    h = squares_y * sq_px + 2 * border_px
    w = squares_x * sq_px + 2 * border_px
    img = np.full((h, w, 3), 255, dtype=np.uint8)  # white background
    for row in range(squares_y):
        for col in range(squares_x):
            if (row + col) % 2 == 1:  # black squares
                y1 = border_px + row * sq_px
                y2 = border_px + (row + 1) * sq_px
                x1 = border_px + col * sq_px
                x2 = border_px + (col + 1) * sq_px
                img[y1:y2, x1:x2] = 0
    return img


def _generate_board_images(
    tmp_dir: pathlib.Path,
    board_config: BoardConfig,
    n_images: int = 20,
    canvas_w: int = 1280,
    canvas_h: int = 960,
) -> list[str]:
    """Render the chessboard at different rotation angles and scales, save as JPEG.

    Uses affine transforms (rotation + scale + translation) to guarantee the
    full board stays in frame — required by findChessboardCorners.
    """
    board_bgr = _make_chessboard_image(
        board_config.squares_x, board_config.squares_y, sq_px=55, border_px=35
    )
    bh, bw = board_bgr.shape[:2]
    cx, cy = bw // 2, bh // 2  # board center

    paths: list[str] = []
    for i in range(n_images):
        # Cycle through angles -15° … +15° and scales 0.80 … 1.00
        angle = -15.0 + 30.0 * i / max(n_images - 1, 1)
        scale = 0.80 + 0.20 * abs(np.sin(np.pi * i / n_images))

        M = cv2.getRotationMatrix2D((cx, cy), angle, scale)

        # Translate so the board center lands at the canvas centre
        M[0, 2] += canvas_w / 2 - cx
        M[1, 2] += canvas_h / 2 - cy

        canvas = cv2.warpAffine(
            board_bgr, M, (canvas_w, canvas_h),
            borderValue=(200, 200, 200),
        )

        path = str(tmp_dir / f"synth_{i:02d}.jpg")
        cv2.imwrite(path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 95])
        paths.append(path)

    return paths


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def board_cfg():
    return BoardConfig()


@pytest.fixture(scope="module")
def synth_images(tmp_path_factory, board_cfg):
    d = tmp_path_factory.mktemp("synth_images")
    return _generate_board_images(d, board_cfg, n_images=20)


@pytest.fixture(scope="module")
def pipeline_results(synth_images, board_cfg):
    """Run detect → filter on synthetic images. Returns (detections, filters)."""
    detections    = detect_images(synth_images, board_cfg, verbose=False)
    filter_results = filter_detections(detections)
    return detections, filter_results


# ── Detection tests ───────────────────────────────────────────────────────────

class TestSyntheticDetection:
    def test_detection_runs_on_all_images(self, pipeline_results, synth_images):
        detections, _ = pipeline_results
        assert len(detections) == len(synth_images)

    def test_no_load_errors_on_valid_images(self, pipeline_results):
        detections, _ = pipeline_results
        errors = [d for d in detections if d.load_error]
        assert errors == [], f"Load errors on: {[e.image_path for e in errors]}"

    def test_majority_of_images_have_corners_detected(self, pipeline_results):
        detections, _ = pipeline_results
        with_corners = sum(1 for d in detections if d.corner_count >= 6)
        assert with_corners >= len(detections) // 2, (
            f"Expected corners in ≥ half of images; got {with_corners}/{len(detections)}"
        )


# ── Filter tests ──────────────────────────────────────────────────────────────

class TestSyntheticFilter:
    def test_filter_has_same_length_as_detections(self, pipeline_results):
        detections, filter_results = pipeline_results
        assert len(filter_results) == len(detections)

    def test_accepted_images_all_have_sufficient_corners(self, pipeline_results):
        detections, filter_results = pipeline_results
        for det, flt in zip(detections, filter_results):
            if flt.accepted:
                assert det.corner_count >= 6


# ── Full pipeline: calibrate + write ─────────────────────────────────────────

class TestFullPipeline:
    """Run calibration and output writing on synthetic data.

    The test is skipped if not enough images are accepted (the threshold for
    calibration is 4 accepted images).
    """

    @pytest.fixture(scope="class")
    def calibrated(self, pipeline_results, board_cfg):
        detections, filter_results = pipeline_results
        accepted = sum(f.accepted for f in filter_results)
        if accepted < 4:
            pytest.skip(
                f"Only {accepted} image(s) accepted — need ≥ 4 for calibration."
            )
        cal_result = calibrate(detections, filter_results, board_cfg)
        return cal_result, None

    def test_calibration_returns_3x3_camera_matrix(self, calibrated):
        cal_result, _ = calibrated
        assert cal_result.camera_matrix.shape == (3, 3)

    def test_calibration_rms_is_finite_positive(self, calibrated):
        cal_result, _ = calibrated
        assert np.isfinite(cal_result.rms)
        assert cal_result.rms > 0

    def test_dist_coeffs_shape(self, calibrated):
        cal_result, _ = calibrated
        rows, cols = cal_result.dist_coeffs.shape
        assert rows == 1
        assert 4 <= cols <= 14

    def test_write_outputs_creates_yaml_and_pdf(
        self, tmp_path, calibrated, pipeline_results, board_cfg, synth_images
    ):
        cal_result, _ = calibrated
        detections, filter_results = pipeline_results
        output_dir = str(tmp_path)

        yaml_path, pdf_path = write_outputs(
            cal_result,
            board_cfg,
            serial="INTTEST001",
            detections=detections,
            filter_results=filter_results,
            image_folder=output_dir,
        )

        assert yaml_path.exists(), f"YAML not found: {yaml_path}"
        assert pdf_path.exists(),  f"PDF not found:  {pdf_path}"

    def test_yaml_parses_and_has_required_keys(
        self, tmp_path, calibrated, pipeline_results, board_cfg
    ):
        cal_result, _ = calibrated
        detections, filter_results = pipeline_results

        yaml_path, _ = write_outputs(
            cal_result,
            board_cfg,
            serial="INTTEST002",
            detections=detections,
            filter_results=filter_results,
            image_folder=str(tmp_path),
        )

        with open(yaml_path) as fh:
            data = yaml.safe_load(fh)

        required = {
            "serial_number",
            "calibration_datetime",
            "rms_reprojection_error",
            "image_count_used",
            "camera_matrix",
            "dist_coeffs",
            "image_resolution",
            "board",
        }
        missing = required - data.keys()
        assert not missing, f"YAML missing keys: {missing}"

    def test_yaml_camera_matrix_is_3x3(
        self, tmp_path, calibrated, pipeline_results, board_cfg
    ):
        cal_result, _ = calibrated
        detections, filter_results = pipeline_results

        yaml_path, _ = write_outputs(
            cal_result,
            board_cfg,
            serial="INTTEST003",
            detections=detections,
            filter_results=filter_results,
            image_folder=str(tmp_path),
        )

        with open(yaml_path) as fh:
            data = yaml.safe_load(fh)

        cm = data["camera_matrix"]
        assert cm["rows"] == 3
        assert cm["cols"] == 3
        assert len(cm["data"]) == 9

    def test_pdf_is_non_empty(
        self, tmp_path, calibrated, pipeline_results, board_cfg
    ):
        cal_result, _ = calibrated
        detections, filter_results = pipeline_results

        _, pdf_path = write_outputs(
            cal_result,
            board_cfg,
            serial="INTTEST004",
            detections=detections,
            filter_results=filter_results,
            image_folder=str(tmp_path),
        )

        content = pdf_path.read_bytes()
        assert content[:4] == b"%PDF", "Output does not start with PDF magic bytes"
        assert len(content) > 1024, "PDF suspiciously small"

    def test_output_filename_matches_convention(
        self, tmp_path, calibrated, pipeline_results, board_cfg
    ):
        cal_result, _ = calibrated
        detections, filter_results = pipeline_results

        yaml_path, pdf_path = write_outputs(
            cal_result,
            board_cfg,
            serial="SN-CONV",
            detections=detections,
            filter_results=filter_results,
            image_folder=str(tmp_path),
        )

        pattern = re.compile(r"CAL_SN-CONV_\d{8}_\d{6}(_\d+)?\.(yaml|pdf)")
        assert pattern.match(yaml_path.name), f"Unexpected YAML name: {yaml_path.name}"
        assert pattern.match(pdf_path.name),  f"Unexpected PDF name:  {pdf_path.name}"

