"""output_writer.py — Write the YAML calibration file and PDF report.

Filename convention:  CAL_<SerialNumber>_<YYYYMMDD_HHMMSS>[_N].<ext>
  where the optional _N suffix prevents overwriting an existing file.

These files are the app's own working record, written next to the images.
Publishing a calibration to the shared store
(`H:\\001_Mahine_App_Specs\\Calibrations`, master doc §11) is a separate
step — see src/calibration_store.py.

Public API
----------
write_yaml(...)  -> Path
write_pdf(...)   -> Path
write_outputs(...) -> tuple[Path, Path]   # YAML + PDF, same timestamp
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from pathlib import Path

import yaml

from src.photo_folders import folder_lines as _folder_lines, folder_summary as _folder_summary
from fpdf import FPDF

from src.board import BoardConfig
from src.calibrator import CalibrationResult
from src.detector import DetectionResult
from src.image_filter import FilterResult
from src.quality import QualityReport


# ── Verdict colours (R, G, B) ────────────────────────────────────────────────
_VERDICT_COLOUR = {
    "Excellent":          (46, 125, 50),
    "Acceptable":         (230, 119, 0),
    "Needs Improvement":  (183, 28, 28),
}

# ── Page geometry (A4 portrait, mm) ─────────────────────────────────────────
_PAGE_W = 210
_MARGIN = 15
_CW = _PAGE_W - 2 * _MARGIN   # usable content width = 180 mm


# ══════════════════════════════════════════════════════════════════════════════
#  Filename helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_stem(serial: str, dt: datetime) -> str:
    return f"CAL_{serial}_{dt.strftime('%Y%m%d_%H%M%S')}"


def _unique_path(folder: Path, stem: str, ext: str) -> Path:
    """Return a non-existent path; append _2, _3 … if the name is taken."""
    candidate = folder / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = folder / f"{stem}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


# ══════════════════════════════════════════════════════════════════════════════
#  YAML writer
# ══════════════════════════════════════════════════════════════════════════════

def write_yaml(
    cal_result: CalibrationResult,
    quality: QualityReport,
    board_config: BoardConfig,
    serial: str,
    image_folder: str | Path,
    dt: datetime | None = None,
    role: str = "",
) -> Path:
    """Serialise calibration results to a YAML file.

    *role* is the camera's rig role (e.g. PAVE, ROW).  It is recorded in the
    file and is what keys the calibration in the shared store; blank is allowed
    for bench runs that are never published.

    Returns the path of the written file.
    """
    dt = dt or datetime.now()
    folder = Path(image_folder)
    out_path = _unique_path(folder, _make_stem(serial, dt), ".yaml")

    cam = cal_result.camera_matrix
    dist = cal_result.dist_coeffs

    payload = {
        "serial_number":            serial,
        "camera_role":              role,
        "calibration_datetime":     dt.isoformat(timespec="seconds"),
        "rms_reprojection_error":   round(float(cal_result.rms), 6),
        "image_count_used":         cal_result.image_count_used,
        "verdict":                  quality.verdict,
        "photos":                   _folder_summary(cal_result, folder),
        "camera_matrix": {
            "rows": 3,
            "cols": 3,
            "data": [round(float(v), 6) for v in cam.flatten()],
        },
        "dist_coeffs": {
            "rows": 1,
            "cols": int(dist.shape[1]),
            "data": [round(float(v), 8) for v in dist.flatten()],
        },
        "image_resolution": {
            "width":  cal_result.image_size[0],
            "height": cal_result.image_size[1],
        },
        "board": {
            "squares_x":      board_config.squares_x,
            "squares_y":      board_config.squares_y,
            "cell_width_mm":  round(board_config.cell_width_mm, 4),
            "cell_height_mm": round(board_config.cell_height_mm, 4),
            # marker_size_mm and aruco_dict are deliberately NOT written
            # (Derek, 2026-08-15): detection is plain chessboard, so the ArUco
            # dictionary describes a code path that never runs, and the marker
            # size was never measured — a default that reads like data.
        },
        # Detection is a plain chessboard — the ArUco markers on the printed
        # board are ignored (see src/detector.py and master doc §8).
        "detection_method": "chessboard",
    }

    g = getattr(cal_result, "grade", None)
    if g is not None:
        rp = g.repeatability
        payload["grade"] = {
            "passed":   bool(g.passed),
            "headline": g.headline,
            "hard_stops": list(g.hard_stops),
            "reasons":  list(g.reasons),
            "warnings": list(getattr(g, "warnings", [])),
            "left_out_automatically": [f"{Path(p).name}: {why}" for p, why in getattr(g, "left_out", [])],
            "repeatability_p95_mrad": None if rp is None else round(rp.est_error_p95_mrad, 3),
            "repeatability_at_10m_mm": None if rp is None else round(rp.at_10m_mm, 1),
            "more_photos_needed": int(g.more_photos),
            "dot_edge_blur_median_px": None if math.isnan(getattr(g, "blur_median_px", float("nan")))
                                       else round(g.blur_median_px, 2),
            "blurry_photos": [Path(p).name for p, _ in getattr(g, "blurry_images", [])],
            "rules": "src/grading.py 2026-10-31: no hard stop, repeatability <= 1 mrad, "
                     "all 3x3 areas with enough points and tilt, RMS < 2 px",
        }

    if board_config.is_dots:
        # Random-dot board: same block shape as the 2026-10-08 AranSW1 files.
        payload["board"] = {
            "type":           "random_dot",
            "name":           board_config.name,
            "layout_file":    Path(board_config.layout_csv).name,
            "label_on_board": board_config.label,
            "dots":           board_config.num_corners,
        }
        payload["detection_method"] = "dot_centroid"
        payload["point_count_used"] = int(cal_result.point_count_used)

    with open(out_path, "w", encoding="utf-8") as fh:
        yaml.dump(payload, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return out_path


# ══════════════════════════════════════════════════════════════════════════════
#  PDF helpers
# ══════════════════════════════════════════════════════════════════════════════

def _section(pdf: FPDF, title: str) -> None:
    """Draw a grey section-heading bar."""
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(220, 220, 220)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(_CW, 6, f"  {title}", border="B", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _kv(pdf: FPDF, key: str, value: str) -> None:
    """One label + value line."""
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(62, 5.5, key)
    pdf.set_font("Helvetica", size=9)
    pdf.cell(_CW - 62, 5.5, value, new_x="LMARGIN", new_y="NEXT")


def _th(pdf: FPDF, headers: list[str], widths: list[float], row_h: float = 6.5) -> None:
    """Table header row (dark background, white text)."""
    pdf.set_fill_color(55, 55, 55)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    for hdr, w in zip(headers, widths):
        pdf.cell(w, row_h, hdr, border=1, fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)


def _tr(
    pdf: FPDF,
    cells: list[str],
    widths: list[float],
    fill: bool = False,
    fill_rgb: tuple[int, int, int] = (245, 245, 245),
    row_h: float = 5.5,
) -> None:
    """One table data row."""
    if fill:
        pdf.set_fill_color(*fill_rgb)
    pdf.set_font("Helvetica", size=7)
    for cell, w in zip(cells, widths):
        pdf.cell(w, row_h, cell, border=1, fill=fill)
    pdf.ln()


def _ascii(text: str) -> str:
    """Core PDF fonts are Latin-1 only."""
    return (text.replace("\u2014", "-").replace("\u00b0", " deg")
                .replace("\u00b7", "|").replace("\u2265", ">="))


def _grade_pdf(pdf: FPDF, cal_result: CalibrationResult) -> None:
    """Grade banner: pass/fail, reasons, what to shoot next (src/grading.py)."""
    g = getattr(cal_result, "grade", None)
    if g is None:
        return
    _section(pdf, "Grade")
    pdf.set_font("Helvetica", "B", 11)
    if g.passed:
        pdf.set_text_color(27, 94, 32)
    else:
        pdf.set_text_color(183, 28, 28)
    pdf.multi_cell(_CW, 6, _ascii(g.headline), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=8)
    rp = g.repeatability
    if rp is not None:
        pdf.multi_cell(_CW, 4.2, _ascii(f"Repeatability: about {rp.at_10m_mm:.0f} mm at 10 m "
                                        f"({rp.est_error_p95_mrad:.2f} mrad, 95% of the image)."),
                       new_x="LMARGIN", new_y="NEXT")
    if not math.isnan(getattr(g, "blur_median_px", float("nan"))):
        pdf.multi_cell(_CW, 4.2, _ascii(f"Sharpness: dot edge blur {g.blur_median_px:.1f} px "
                                        "(sharp is about 1 px)."), new_x="LMARGIN", new_y="NEXT")
    for s in g.hard_stops:
        pdf.multi_cell(_CW, 4.2, _ascii("STOP: " + s), new_x="LMARGIN", new_y="NEXT")
    for r in g.reasons:
        pdf.multi_cell(_CW, 4.2, _ascii("- " + r), new_x="LMARGIN", new_y="NEXT")
    for w in getattr(g, "warnings", []):
        pdf.multi_cell(_CW, 4.2, _ascii("! " + w), new_x="LMARGIN", new_y="NEXT")
    if g.coaching:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(_CW, 4.5, "What to do:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=8)
        for c in g.coaching:
            pdf.multi_cell(_CW, 4.2, _ascii("* " + c), new_x="LMARGIN", new_y="NEXT")
    for p, e in g.worst_images:
        pdf.multi_cell(_CW, 4.2, _ascii(f"  worst photo: {Path(p).name}  {e:.2f} px"), new_x="LMARGIN", new_y="NEXT")
    for p, why in getattr(g, "left_out", [])[:20]:
        pdf.multi_cell(_CW, 4.2, _ascii(f"  left out automatically: {Path(p).name}  ({why})"),
                       new_x="LMARGIN", new_y="NEXT")
    for p, b in getattr(g, "blurry_images", [])[:10]:
        pdf.multi_cell(_CW, 4.2, _ascii(f"  blurry photo: {Path(p).name}  edge blur {b:.1f} px"),
                       new_x="LMARGIN", new_y="NEXT")


def _coverage_grid_pdf(pdf: FPDF, cal_result: CalibrationResult) -> None:
    """3x3 coloured grid of how well each part of the image is calibrated."""
    from src.coverage import GOOD, POOR, WEAK, compute_grid, limits_text

    _section(pdf, "Image Coverage (3 x 3)")
    try:
        grid = compute_grid(cal_result)
    except Exception as exc:  # noqa: BLE001 — never block the report
        _kv(pdf, "Not available:", _ascii(str(exc)))
        return
    fills = {GOOD: (200, 230, 201), WEAK: (255, 224, 178), POOR: (255, 205, 210)}
    cw, ch = 50.0, 17.0
    if pdf.get_y() + 3 * ch + 30 > pdf.h - pdf.b_margin:
        pdf.add_page()
    x0, y0 = pdf.l_margin, pdf.get_y()
    for row in grid.cells:
        for cell in row:
            x, y = x0 + cell.col * cw, y0 + cell.row * ch
            pdf.set_fill_color(*fills[cell.status])
            pdf.rect(x, y, cw, ch, style="DF")
            err = "-" if cell.points == 0 else f"{cell.rms_px:.2f} px"
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_xy(x, y + 1.5)
            pdf.cell(cw, 4.5, f"{cell.name}  ({cell.status})", align="C")
            pdf.set_font("Helvetica", size=8)
            pdf.set_xy(x, y + 6.5)
            pdf.cell(cw, 4.5, f"{cell.points} points | {err}", align="C")
            pdf.set_xy(x, y + 11)
            pdf.cell(cw, 4.5, f"angles {cell.tilt_spread_deg:.0f} deg", align="C")
    pdf.set_xy(x0, y0 + 3 * ch + 2)
    pdf.set_font("Helvetica", size=7)
    pdf.multi_cell(_CW, 3.6, _ascii(limits_text()), new_x="LMARGIN", new_y="NEXT")
    advice = grid.advice()
    pdf.set_font("Helvetica", size=8)
    pdf.ln(1)
    if advice:
        for line in advice:
            pdf.multi_cell(_CW, 4.2, _ascii("- " + line), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.multi_cell(_CW, 4.2, "All 9 areas are green.", new_x="LMARGIN", new_y="NEXT")


# ══════════════════════════════════════════════════════════════════════════════
#  PDF writer
# ══════════════════════════════════════════════════════════════════════════════

def write_pdf(
    cal_result: CalibrationResult,
    quality: QualityReport,
    board_config: BoardConfig,
    serial: str,
    detections: list[DetectionResult],
    filter_results: list[FilterResult],
    image_folder: str | Path,
    dt: datetime | None = None,
) -> Path:
    """Generate the calibration PDF report.

    Returns the path of the written file.
    """
    dt = dt or datetime.now()
    folder = Path(image_folder)
    out_path = _unique_path(folder, _make_stem(serial, dt), ".pdf")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.set_auto_page_break(auto=True, margin=_MARGIN)
    pdf.add_page()

    # ── Title ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(_CW, 10, "Camera Calibration Report",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    pdf.cell(_CW, 5,
             f"Generated: {dt.strftime('%Y-%m-%d  %H:%M:%S')}    "
             f"Camera Serial: {serial}",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=8)
    for line in _folder_lines(cal_result, folder):
        pdf.multi_cell(_CW, 4.2, _ascii(line), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ── Verdict badge ──────────────────────────────────────────────────────
    verdict = quality.verdict
    vr, vg, vb = _VERDICT_COLOUR.get(verdict, (100, 100, 100))
    pdf.set_fill_color(vr, vg, vb)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    badge_w = 80.0
    pdf.set_x((_PAGE_W - badge_w) / 2)
    pdf.cell(badge_w, 9, verdict, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    # ── Summary ────────────────────────────────────────────────────────────
    cam = cal_result.camera_matrix
    fx, fy = cam[0, 0], cam[1, 1]
    cx, cy = cam[0, 2], cam[1, 2]

    _grade_pdf(pdf, cal_result)

    _section(pdf, "Calibration Summary")
    _kv(pdf, "RMS Reprojection Error:", f"{cal_result.rms:.4f} px")
    _kv(pdf, "Images Used:",
        f"{cal_result.image_count_used}  (need >= {quality.image_count_needed})")
    _kv(pdf, "Focal Length:",   f"fx = {fx:.2f} px     fy = {fy:.2f} px")
    _kv(pdf, "Principal Point:", f"cx = {cx:.2f} px     cy = {cy:.2f} px")
    _kv(pdf, "Image Resolution:",
        f"{cal_result.image_size[0]} x {cal_result.image_size[1]} px")

    # ── Camera matrix ──────────────────────────────────────────────────────
    _section(pdf, "Camera Matrix  (3 x 3)")
    col_w = _CW / 3
    _th(pdf, ["Column 0", "Column 1", "Column 2"], [col_w] * 3)
    for r in range(3):
        _tr(pdf,
            [f"{cam[r, c]:.4f}" for c in range(3)],
            [col_w] * 3,
            fill=(r % 2 == 1))

    # ── Distortion coefficients ────────────────────────────────────────────
    dist_flat = cal_result.dist_coeffs.flatten().tolist()
    n = len(dist_flat)
    _section(pdf, f"Distortion Coefficients  (1 x {n})")
    coeff_labels = ["k1", "k2", "p1", "p2", "k3",
                    "k4", "k5", "k6", "s1", "s2",
                    "s3", "s4", "tx", "ty"][:n]
    cw = _CW / max(n, 1)
    _th(pdf, coeff_labels, [cw] * n)
    _tr(pdf, [f"{v:.6f}" for v in dist_flat], [cw] * n)

    # ── 3x3 image coverage ────────────────────────────────────────────────
    _coverage_grid_pdf(pdf, cal_result)

    # ── Board parameters ──────────────────────────────────────────────────
    _section(pdf, "Board Parameters")
    if board_config.is_dots:
        _kv(pdf, "Board:",        board_config.name)
        _kv(pdf, "Layout file:",  Path(board_config.layout_csv).name)
        _kv(pdf, "Dots:",         str(board_config.num_corners))
        _kv(pdf, "Detection:",    "Random-dot board, dot centroids")
    else:
        _kv(pdf, "Squares X x Y:",
            f"{board_config.squares_x} x {board_config.squares_y}")
        _kv(pdf, "Cell Width (mm):",   f"{board_config.cell_width_mm:.4f}")
        _kv(pdf, "Cell Height (mm):",  f"{board_config.cell_height_mm:.4f}")
        _kv(pdf, "Detection:",         "Plain chessboard (ArUco markers ignored)")

    # ── Recommended action (Needs Improvement only) ───────────────────────
    if verdict == "Needs Improvement":
        pdf.ln(3)
        pdf.set_fill_color(255, 235, 238)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(_CW, 6, "  [!]  Recommended Action",
                 fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=8)
        advice = (
            "RMS error exceeds 1.0 px. To improve:\n"
            "  - Capture 20-30 images at varied board angles (+/-30-45 degrees)\n"
            "  - Ensure the board is sharply in focus in every shot\n"
            "  - Cover all corners and edges of the camera frame\n"
            "  - Do not change focal length or aperture between shots"
        )
        pdf.set_fill_color(255, 248, 249)
        pdf.multi_cell(_CW, 5, advice, border=1, fill=True)

    # ── Per-image results table ────────────────────────────────────────────
    _section(pdf, "Per-Image Results")
    reason_w = _CW - 58 - 20 - 20 - 22
    col_ws = [58.0, 20.0, 20.0, 22.0, reason_w]
    _th(pdf, ["Filename", "Status", "Corners", "Blur", "Rejection Reason"], col_ws)

    _ACCEPTED_FILL = (232, 245, 233)   # light green
    _REJECTED_FILL = (255, 243, 224)   # light amber

    for i, (det, filt) in enumerate(zip(detections, filter_results)):
        name = os.path.basename(det.image_path)
        if len(name) > 34:
            name = "..." + name[-31:]
        status   = "Accepted" if filt.accepted else "Rejected"
        corners  = str(filt.corner_count)
        blur     = f"{filt.blur_score:.0f}"
        reason   = "" if filt.accepted else filt.reason
        # Truncate long reason text for PDF
        if len(reason) > 45:
            reason = reason[:42] + "..."
        fill_rgb = _ACCEPTED_FILL if filt.accepted else _REJECTED_FILL
        _tr(pdf, [name, status, corners, blur, reason], col_ws,
            fill=True, fill_rgb=fill_rgb)

    pdf.output(str(out_path))
    return out_path


# ══════════════════════════════════════════════════════════════════════════════
#  Convenience wrapper
# ══════════════════════════════════════════════════════════════════════════════

def write_outputs(
    cal_result: CalibrationResult,
    quality: QualityReport,
    board_config: BoardConfig,
    serial: str,
    detections: list[DetectionResult],
    filter_results: list[FilterResult],
    image_folder: str | Path,
    dt: datetime | None = None,
    role: str = "",
) -> tuple[Path, Path]:
    """Write YAML + PDF with a shared timestamp.  Returns (yaml_path, pdf_path).

    Pass *dt* when the caller also needs that datetime — publishing to the
    calibration store must stamp the store file with the SAME datetime.
    """
    dt = dt or datetime.now()
    yaml_path = write_yaml(cal_result, quality, board_config, serial, image_folder, dt, role)
    pdf_path = write_pdf(
        cal_result, quality, board_config, serial,
        detections, filter_results, image_folder, dt,
    )
    return yaml_path, pdf_path
