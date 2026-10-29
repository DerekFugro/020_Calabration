"""calibrator.py — Run OpenCV camera calibration from accepted corner detections.

Uses cv2.calibrateCamera with object points built manually by
BoardConfig.get_all_object_points(), which takes separate X and Y cell
spacing.  The current board is square at 76.39 mm × 76.39 mm (measured
2026-08-11), but keeping separate spacing means a non-square board can still
be entered on the Setup screen without a code change.

Corners come from src/detector.py, which uses plain chessboard detection —
not the ArUco module.  The `charuco_*` field names on DetectionResult are
historical; see the naming caveat in README.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from src.board import BoardConfig
from src.detector import DetectionResult
from src.image_filter import FilterResult

_MIN_IMAGES_FOR_CALIBRATION = 4  # hard minimum; quality verdict applies separately


@dataclass
class CalibrationResult:
    """Outputs from a successful camera calibration run."""

    camera_matrix: np.ndarray    # shape (3, 3), float64
    dist_coeffs: np.ndarray      # shape (1, N), float64  (N=5 by default)
    rms: float                   # RMS reprojection error in pixels
    rvecs: list                  # per-image rotation vectors
    tvecs: list                  # per-image translation vectors
    image_count_used: int
    image_size: tuple[int, int]  # (width, height) of calibration images
    per_image_errors: list = field(default_factory=list)  # (image_path, rms_px) sorted worst-first
    point_count_used: int = 0    # total board points (corners or dots) used


def _refine_dot_matches(detections, filter_results, board_config, image_size,
                        object_points, image_points, first):
    """Re-match dot-board images on undistorted points and recalibrate.

    An image whose re-match fails keeps its first-pass points, so the image
    list (and its order) never changes here.
    """
    from src.dot_detector import DotMatch, rematch_dots

    rms, K, D, rvecs, tvecs = first
    all_obj = board_config.get_all_object_points()
    used = [det for det, filt in zip(detections, filter_results)
            if filt.accepted and det.charuco_ids is not None
            and det.charuco_corners is not None
            and det.charuco_ids.flatten().max() < len(all_obj)]
    for _round in range(2):
        new_obj, new_img = [], []
        for det, obj, img in zip(used, object_points, image_points):
            m = None
            if det.blobs is not None and len(det.blobs):
                obj_ids = det.charuco_ids.flatten()
                prev = DotMatch(ids=obj_ids, image_points=img.reshape(-1, 2).astype(np.float64),
                                n_blobs=len(det.blobs), rms_px=0.0)
                m = rematch_dots(det.blobs, board_config.dot_xy_mm, prev, K, D)
            if m is None:
                new_obj.append(obj)
                new_img.append(img)
            else:
                det.charuco_ids = m.ids.astype(np.int32).reshape(-1, 1)
                det.charuco_corners = m.image_points.astype(np.float32).reshape(-1, 1, 2)
                det.corner_count = len(m.ids)
                new_obj.append(all_obj[m.ids])
                new_img.append(det.charuco_corners)
        object_points, image_points = new_obj, new_img
        rms, K, D, rvecs, tvecs = cv2.calibrateCamera(
            object_points, image_points, image_size, None, None)
    return object_points, image_points, rms, K, D, rvecs, tvecs


def calibrate(
    detections: list[DetectionResult],
    filter_results: list[FilterResult],
    board_config: BoardConfig,
) -> CalibrationResult:
    """Compute camera intrinsics from a set of detected board images.

    Parameters
    ----------
    detections:
        Full list of DetectionResults (one per image, from detector.py).
    filter_results:
        Corresponding FilterResults (same length and order).
    board_config:
        Board geometry; used to look up 3D object points by corner ID.

    Returns
    -------
    CalibrationResult

    Raises
    ------
    ValueError
        If fewer than _MIN_IMAGES_FOR_CALIBRATION images are accepted.
    """
    if len(detections) != len(filter_results):
        raise ValueError(
            "detections and filter_results must have the same length."
        )

    all_obj_pts = board_config.get_all_object_points()  # (num_corners, 3), float32

    object_points: list[np.ndarray] = []
    image_points: list[np.ndarray] = []
    image_size: tuple[int, int] | None = None

    for det, filt in zip(detections, filter_results):
        if not filt.accepted:
            continue
        if det.charuco_ids is None or det.charuco_corners is None:
            continue

        ids = det.charuco_ids.flatten()

        # Validate IDs are within the expected range
        if ids.max() >= len(all_obj_pts):
            continue

        # Select object points for the corners that were actually detected
        obj_pts = all_obj_pts[ids]            # (N, 3), float32
        img_pts = det.charuco_corners         # (N, 1, 2), float32

        object_points.append(obj_pts)
        image_points.append(img_pts)

        if image_size is None:
            image_size = det.image_size

    accepted_count = len(object_points)
    if accepted_count < _MIN_IMAGES_FOR_CALIBRATION:
        raise ValueError(
            f"Only {accepted_count} usable images found; "
            f"need at least {_MIN_IMAGES_FOR_CALIBRATION} for calibration."
        )

    if image_size is None:
        raise ValueError("No accepted image had a valid size.")

    rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        object_points,
        image_points,
        image_size,
        None,  # initial camera matrix (None = auto-estimate)
        None,  # initial distortion coefficients
    )

    if board_config.is_dots:
        # Second pass for dot boards: the first-pass matches were made on
        # distorted pixels with a loose tolerance.  Re-match every accepted
        # image on undistorted points (tight tolerance, picks up edge dots)
        # and calibrate again.  Done twice; the second round rarely changes
        # anything.
        object_points, image_points, rms, camera_matrix, dist_coeffs, rvecs, tvecs = (
            _refine_dot_matches(detections, filter_results, board_config,
                                image_size, object_points, image_points,
                                (rms, camera_matrix, dist_coeffs, rvecs, tvecs))
        )

    # Compute per-image reprojection error
    accepted_paths = [
        det.image_path
        for det, filt in zip(detections, filter_results)
        if filt.accepted
        and det.charuco_ids is not None
        and det.charuco_corners is not None
        and det.charuco_ids.flatten().max() < len(all_obj_pts)
    ]
    per_image_errors: list[tuple[str, float]] = []
    for i, (obj_pts, img_pts, rvec, tvec, path) in enumerate(
        zip(object_points, image_points, rvecs, tvecs, accepted_paths)
    ):
        projected, _ = cv2.projectPoints(
            obj_pts.reshape(-1, 1, 3), rvec, tvec, camera_matrix, dist_coeffs
        )
        # Both must be flattened to (N, 2) before subtracting: detected corners
        # are (N, 2) while projectPoints returns (N, 1, 2), and the mismatch
        # would broadcast to (N, N, 2) and inflate the error ~1000x.
        diff = img_pts.reshape(-1, 2) - projected.reshape(-1, 2)
        # Per-point Euclidean residual, RMS over the image (same convention as
        # cv2.calibrateCamera's overall RMS).
        err = float(np.sqrt(np.mean(np.sum(diff ** 2, axis=1))))
        per_image_errors.append((path, err))
    per_image_errors.sort(key=lambda x: x[1], reverse=True)

    return CalibrationResult(
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
        rms=float(rms),
        rvecs=list(rvecs),
        tvecs=list(tvecs),
        image_count_used=accepted_count,
        image_size=image_size,
        per_image_errors=per_image_errors,
        point_count_used=int(sum(len(p) for p in object_points)),
    )
