"""test_edge_cases.py — Edge-case and boundary tests for the calibration engine."""

from __future__ import annotations

import pathlib

import pytest

from src.board import BoardConfig
from src.calibrator import calibrate
from src.detector import DetectionResult, detect_images
from src.image_filter import FilterResult, filter_detections
from src.utils import find_images


# ── find_images ───────────────────────────────────────────────────────────────

class TestFindImages:
    def test_empty_folder_returns_empty_list(self, tmp_path):
        result = find_images(str(tmp_path))
        assert result == []

    def test_nonexistent_folder_returns_empty_list(self, tmp_path):
        missing = str(tmp_path / "does_not_exist")
        result = find_images(missing)
        assert result == []

    def test_finds_jpg_files(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"")
        (tmp_path / "b.JPG").write_bytes(b"")
        result = find_images(str(tmp_path))
        names = {pathlib.Path(p).name for p in result}
        assert {"a.jpg", "b.JPG"}.issubset(names)

    def test_finds_png_files(self, tmp_path):
        (tmp_path / "c.png").write_bytes(b"")
        result = find_images(str(tmp_path))
        assert any("c.png" in p for p in result)

    def test_ignores_non_image_files(self, tmp_path):
        (tmp_path / "notes.txt").write_bytes(b"")
        (tmp_path / "data.yaml").write_bytes(b"")
        result = find_images(str(tmp_path))
        assert result == []

    def test_no_duplicates_from_case_variants(self, tmp_path):
        # On case-insensitive file systems there are no duplicates because
        # you can't have both 'x.jpg' and 'x.JPG'; on case-sensitive systems
        # they are distinct files — either way the returned list must be unique.
        (tmp_path / "x.jpeg").write_bytes(b"")
        result = find_images(str(tmp_path))
        assert len(result) == len(set(result))

    def test_returns_sorted_list(self, tmp_path):
        for name in ("c.jpg", "a.jpg", "b.png"):
            (tmp_path / name).write_bytes(b"")
        result = find_images(str(tmp_path))
        assert result == sorted(result)

    def test_does_not_recurse_into_subdirectories(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "nested.jpg").write_bytes(b"")
        result = find_images(str(tmp_path))
        assert result == []


# ── detect_images with bad paths ─────────────────────────────────────────────

class TestDetectImagesEdgeCases:
    def test_nonexistent_file_produces_load_error(self, tmp_path):
        cfg = BoardConfig()
        missing = str(tmp_path / "ghost.jpg")
        results = detect_images([missing], cfg, verbose=False)
        assert len(results) == 1
        assert results[0].load_error is True

    def test_corrupt_file_produces_load_error(self, tmp_path):
        corrupt = tmp_path / "bad.jpg"
        corrupt.write_bytes(b"not an image")
        cfg = BoardConfig()
        results = detect_images([str(corrupt)], cfg, verbose=False)
        assert len(results) == 1
        assert results[0].load_error is True

    def test_empty_image_list_returns_empty(self):
        cfg = BoardConfig()
        results = detect_images([], cfg, verbose=False)
        assert results == []


# ── filter_detections edge cases ──────────────────────────────────────────────

class TestFilterEdgeCases:
    def _make_detection(self, *, load_error=False, corner_count=0, blur_score=0.0):
        return DetectionResult(
            image_path="fake.jpg",
            image_size=(1920, 1080),
            charuco_corners=None,
            charuco_ids=None,
            corner_count=corner_count,
            blur_score=blur_score,
            load_error=load_error,
            load_error_msg="err" if load_error else None,
        )

    def test_load_error_is_rejected(self):
        det = self._make_detection(load_error=True)
        results = filter_detections([det])
        assert not results[0].accepted

    def test_zero_corners_is_rejected(self):
        det = self._make_detection(corner_count=0, blur_score=500.0)
        results = filter_detections([det])
        assert not results[0].accepted

    def test_exactly_min_corners_is_accepted(self):
        # MIN_CORNERS = 6; blur good; should pass
        det = self._make_detection(corner_count=6, blur_score=200.0)
        results = filter_detections([det])
        assert results[0].accepted

    def test_one_below_min_corners_is_rejected(self):
        det = self._make_detection(corner_count=5, blur_score=200.0)
        results = filter_detections([det])
        assert not results[0].accepted

    def test_blurry_image_is_rejected(self):
        det = self._make_detection(corner_count=20, blur_score=10.0)
        results = filter_detections([det])
        assert not results[0].accepted

    def test_all_load_errors_returns_all_rejected(self):
        dets = [self._make_detection(load_error=True) for _ in range(5)]
        results = filter_detections(dets)
        assert all(not r.accepted for r in results)


# ── calibrate with insufficient accepted images ───────────────────────────────

class TestCalibratorEdgeCases:
    def _good_filter() -> FilterResult:
        return FilterResult(accepted=True, reason="ok", corner_count=20, blur_score=300.0)

    def _bad_filter() -> FilterResult:
        return FilterResult(
            accepted=False, reason="too few corners", corner_count=2, blur_score=300.0
        )

    def _stub_detection(n_corners: int = 20) -> DetectionResult:
        """Detection with no actual corner data — used only to check rejection."""
        import numpy as np

        ids = np.arange(n_corners, dtype=np.int32).reshape(n_corners, 1)
        corners = np.zeros((n_corners, 1, 2), dtype=np.float32)
        return DetectionResult(
            image_path="fake.jpg",
            image_size=(1920, 1080),
            charuco_corners=corners,
            charuco_ids=ids,
            corner_count=n_corners,
            blur_score=300.0,
            load_error=False,
            load_error_msg=None,
        )

    def test_zero_accepted_raises_value_error(self):
        cfg = BoardConfig()
        det = self._stub_detection()
        flt = FilterResult(
            accepted=False, reason="too few corners", corner_count=2, blur_score=0.0
        )
        with pytest.raises(ValueError, match="at least"):
            calibrate([det], [flt], cfg)

    def test_three_accepted_raises_value_error(self):
        """calibrate requires ≥ 4 images — 3 should raise."""
        cfg = BoardConfig()
        dets = [self._stub_detection() for _ in range(3)]
        flts = [
            FilterResult(
                accepted=False, reason="too few corners", corner_count=2, blur_score=0.0
            )
            for _ in range(3)
        ]
        with pytest.raises(ValueError):
            calibrate(dets, flts, cfg)

    _stub_detection = staticmethod(_stub_detection)
    _bad_filter = staticmethod(_bad_filter)
