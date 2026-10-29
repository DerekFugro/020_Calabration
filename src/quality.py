"""quality.py — Evaluate calibration quality and produce a verdict.

Thresholds (from references/Calibration_Instructions.md):
    RMS < 0.5 px  →  Excellent     (green)
    RMS 0.5–1.0   →  Acceptable    (yellow)
    RMS > 1.0     →  Needs Improvement (red)

A calibration also fails if fewer than MIN_IMAGES images were accepted.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.calibrator import CalibrationResult

# RMS thresholds
RMS_EXCELLENT: float = 0.5
RMS_ACCEPTABLE: float = 1.0

# Minimum accepted images for the calibration to be considered valid
MIN_IMAGES: int = 15

# Verdict strings (used in GUI badges and PDF report)
VERDICT_EXCELLENT = "Excellent"
VERDICT_ACCEPTABLE = "Acceptable"
VERDICT_NEEDS_IMPROVEMENT = "Needs Improvement"


@dataclass
class QualityReport:
    """Full quality assessment of a completed calibration run."""

    verdict: str                  # VERDICT_* constant
    rms: float                    # RMS reprojection error in px
    image_count_used: int
    image_count_needed: int       # minimum accepted images required
    pass_verdict: bool            # True if rms ≤ RMS_ACCEPTABLE and image count OK
    message: str                  # Human-readable summary / recommended action


def evaluate(
    result: CalibrationResult,
    min_images: int = MIN_IMAGES,
) -> QualityReport:
    """Produce a QualityReport from a CalibrationResult.

    Parameters
    ----------
    result:
        Output of calibrator.calibrate().
    min_images:
        Minimum accepted images for the run to be considered valid.

    Returns
    -------
    QualityReport
    """
    rms = result.rms
    image_count = result.image_count_used

    # Determine RMS verdict
    if rms < RMS_EXCELLENT:
        verdict = VERDICT_EXCELLENT
    elif rms <= RMS_ACCEPTABLE:
        verdict = VERDICT_ACCEPTABLE
    else:
        verdict = VERDICT_NEEDS_IMPROVEMENT

    # Overall pass requires both RMS and image count thresholds
    enough_images = image_count >= min_images
    rms_ok = rms <= RMS_ACCEPTABLE
    pass_verdict = rms_ok and enough_images

    # Build message
    lines: list[str] = [
        f"RMS reprojection error: {rms:.4f} px  ({verdict})",
        f"Images used: {image_count}  (need ≥ {min_images})",
    ]

    if not enough_images:
        lines.append(
            f"WARNING: Only {image_count} images accepted. "
            f"Capture at least {min_images - image_count} more images of the board "
            "at varied angles and positions."
        )

    if verdict == VERDICT_NEEDS_IMPROVEMENT:
        lines.append(
            "WARNING: RMS error is above 1.0 px. "
            "Recapture images closer to the board, with the board sharply in focus, "
            "at more varied angles. Remove any blurry or partially occluded shots."
        )

    if pass_verdict and verdict == VERDICT_EXCELLENT:
        lines.append("Calibration quality is excellent — ready for deployment.")
    elif pass_verdict and verdict == VERDICT_ACCEPTABLE:
        lines.append(
            "Calibration quality is acceptable. "
            "For higher accuracy, capture additional images at steeper angles."
        )

    return QualityReport(
        verdict=verdict,
        rms=rms,
        image_count_used=image_count,
        image_count_needed=min_images,
        pass_verdict=pass_verdict,
        message="\n".join(lines),
    )
