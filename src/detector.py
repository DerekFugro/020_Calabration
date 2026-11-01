"""detector.py — Board point detection for a single image or a batch.

Chessboards: cv2.findChessboardCorners + cv2.cornerSubPix.
Dot boards (BoardConfig.kind == 'dots'): src/dot_detector.py; the matched dot
ids go in charuco_ids and the dot centres in charuco_corners, so the filter
and calibrator treat both kinds the same way.

Uses cv2.findChessboardCorners + cv2.cornerSubPix.  Each call returns a
DetectionResult that records corners, row-major IDs, blur score, and image
size — everything the filter and calibrator need downstream.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from src.board import BoardConfig


@dataclass
class DetectionResult:
    """All outputs from attempting to detect chessboard corners in one image."""

    image_path: str
    image_size: tuple[int, int]            # (width, height)
    charuco_corners: Optional[np.ndarray]  # shape (N, 1, 2), float32
    charuco_ids: Optional[np.ndarray]      # shape (N, 1), int32 — row-major 0-based
    corner_count: int                      # 0 if not found
    blur_score: float                      # Laplacian variance — higher = sharper
    load_error: bool = False
    load_error_msg: str = ""
    # Dot boards only: every blob found (N, 5: x, y, MA, ma, area), kept so the
    # calibrator can re-match on undistorted points (second pass).
    blobs: Optional[np.ndarray] = None
    match_rms_px: float = 0.0
    # Dot boards: edge blur (Gaussian sigma, px) measured on the matched dots.
    edge_blur_px: float = float("nan")


_SUBPIX_CRITERIA = (
    cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER,
    30,
    0.001,
)
_CB_FLAGS    = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
_CB_FLAGS_SB = cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY


def _compute_blur(gray: np.ndarray) -> float:
    """Laplacian variance as a sharpness proxy (higher = sharper)."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _detect_single(
    image_path: str,
    board_config: BoardConfig,
) -> DetectionResult:
    """Run chessboard detection on one image file."""

    image = cv2.imread(image_path)
    if image is None:
        return DetectionResult(
            image_path=image_path,
            image_size=(0, 0),
            charuco_corners=None,
            charuco_ids=None,
            corner_count=0,
            blur_score=0.0,
            load_error=True,
            load_error_msg=f"cv2.imread returned None for: {image_path}",
        )

    h, w = image.shape[:2]
    gray       = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur_score = _compute_blur(gray)

    if board_config.is_dots:
        return _detect_dots(image_path, gray, (w, h), blur_score, board_config)

    # CLAHE normalises uneven lighting (common with large boards under room lights)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray  = clahe.apply(gray)

    # Add white border — findChessboardCorners requires clear white margin around
    # the outermost squares; boards trimmed to the edge will fail without this.
    _PAD = 60
    gray_padded = cv2.copyMakeBorder(
        gray, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_CONSTANT, value=255
    )

    pattern = (board_config.squares_x - 1, board_config.squares_y - 1)

    # Try the more robust SB detector first, fall back to classic
    found, corners = cv2.findChessboardCornersSB(gray_padded, pattern, _CB_FLAGS_SB)
    if not found or corners is None:
        found, corners = cv2.findChessboardCorners(gray_padded, pattern, _CB_FLAGS)

    # Shift corners back to original (unpadded) coordinate space
    if found and corners is not None:
        corners = corners - np.array([_PAD, _PAD], dtype=np.float32)

    if not found or corners is None:
        return DetectionResult(
            image_path=image_path,
            image_size=(w, h),
            charuco_corners=None,
            charuco_ids=None,
            corner_count=0,
            blur_score=blur_score,
        )

    # Sub-pixel refinement
    corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), _SUBPIX_CRITERIA)

    n_corners = len(corners)  # always (squares_x-1)*(squares_y-1) when found
    ids = np.arange(n_corners, dtype=np.int32).reshape(n_corners, 1)

    return DetectionResult(
        image_path=image_path,
        image_size=(w, h),
        charuco_corners=corners,  # (N, 1, 2)
        charuco_ids=ids,          # (N, 1) matching get_all_object_points() order
        corner_count=n_corners,
        blur_score=blur_score,
    )


def _detect_dots(
    image_path: str,
    gray: np.ndarray,
    size: tuple[int, int],
    blur_score: float,
    board_config: BoardConfig,
) -> DetectionResult:
    """Find the dots of a random-dot board (first pass, distorted pixels)."""
    from src.dot_detector import detect_blobs, edge_blur_px, match_dots

    blobs = detect_blobs(gray)
    m = match_dots(blobs, board_config.dot_xy_mm, image_size=size)
    if m is None:
        return DetectionResult(
            image_path=image_path, image_size=size, charuco_corners=None,
            charuco_ids=None, corner_count=0, blur_score=blur_score,
            blobs=blobs,
        )
    n = len(m.ids)
    return DetectionResult(
        image_path=image_path,
        image_size=size,
        charuco_corners=m.image_points.astype(np.float32).reshape(n, 1, 2),
        charuco_ids=m.ids.astype(np.int32).reshape(n, 1),
        corner_count=n,
        blur_score=blur_score,
        blobs=blobs,
        match_rms_px=m.rms_px,
        edge_blur_px=edge_blur_px(gray, m.image_points, blobs),
    )


def detect_images(
    image_paths: list[str],
    board_config: BoardConfig,
    verbose: bool = True,
    progress_cb=None,
) -> list[DetectionResult]:
    """Detect chessboard corners in a list of image files.

    Parameters
    ----------
    image_paths:
        Absolute or relative paths to JPG/PNG calibration images.
    board_config:
        Board parameters (squares_x, squares_y determine the corner pattern).
    verbose:
        If True, print a one-line summary per image to stdout.

    Returns
    -------
    list[DetectionResult], one entry per input path (same order).
    """
    results: list[DetectionResult] = []

    for k, path in enumerate(image_paths, 1):
        result = _detect_single(path, board_config)
        results.append(result)
        if progress_cb is not None and (k % 10 == 0 or k == len(image_paths)):
            progress_cb(f"Detecting {board_config.name}: {k} / {len(image_paths)} images…")

        if verbose:
            name = os.path.basename(path)
            if result.load_error:
                print(f"  LOAD ERROR  {name}: {result.load_error_msg}")
            else:
                print(
                    f"  {name}: {result.corner_count} corners, "
                    f"blur={result.blur_score:.1f}"
                )

    return results
