"""image_filter.py — Accept or reject detected images before calibration.

An image is rejected if it fails any of these checks (in order):
  1. Load error — cv2.imread returned None.
  2. Too few corners — fewer than MIN_CORNERS chessboard corners detected.
  3. Too blurry   — Laplacian-variance blur score below MIN_BLUR_SCORE.

Note: detection is all-or-nothing — cv2.findChessboardCorners returns either
the full (squares_x-1) x (squares_y-1) grid or nothing.  So in practice check
2 rejects only images where the board was not found at all.  MIN_CORNERS is
kept configurable in case a partial-grid detector is used later.

MIN_BLUR_SCORE is the fallback default; the GUI passes the user's value from
the Setup screen's Min Blur Score spinbox (same 20.0 default).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.detector import DetectionResult

# Configurable thresholds (can be overridden at call sites)
MIN_CORNERS: int = 6
MIN_BLUR_SCORE: float = 20.0


@dataclass
class FilterResult:
    """Outcome of applying the acceptance filter to one DetectionResult."""

    accepted: bool
    reason: str    # Human-readable rejection reason; empty string if accepted.
    corner_count: int
    blur_score: float


def filter_detection(
    detection: DetectionResult,
    min_corners: int = MIN_CORNERS,
    min_blur: float = MIN_BLUR_SCORE,
) -> FilterResult:
    """Apply acceptance criteria to a single DetectionResult.

    Parameters
    ----------
    detection:
        Output from detector.detect_images().
    min_corners:
        Minimum number of detected chessboard corners required.
    min_blur:
        Minimum Laplacian-variance score required (higher = sharper).

    Returns
    -------
    FilterResult with accepted=True if all checks pass.
    """
    if detection.load_error:
        return FilterResult(
            accepted=False,
            reason=f"Load error: {detection.load_error_msg}",
            corner_count=0,
            blur_score=0.0,
        )

    if detection.corner_count < min_corners:
        return FilterResult(
            accepted=False,
            reason=(
                f"Too few corners detected ({detection.corner_count} < {min_corners})"
            ),
            corner_count=detection.corner_count,
            blur_score=detection.blur_score,
        )

    if detection.blur_score < min_blur:
        return FilterResult(
            accepted=False,
            reason=(
                f"Image too blurry (blur score {detection.blur_score:.1f} < {min_blur:.1f})"
            ),
            corner_count=detection.corner_count,
            blur_score=detection.blur_score,
        )

    return FilterResult(
        accepted=True,
        reason="",
        corner_count=detection.corner_count,
        blur_score=detection.blur_score,
    )


def filter_detections(
    detections: list[DetectionResult],
    min_corners: int = MIN_CORNERS,
    min_blur: float = MIN_BLUR_SCORE,
) -> list[FilterResult]:
    """Apply filter_detection to every entry in a detection list."""
    return [filter_detection(d, min_corners, min_blur) for d in detections]
