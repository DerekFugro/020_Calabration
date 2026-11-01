"""report.py — one-camera extrinsic PDF (fpdf2)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
from fpdf import FPDF

from src.output_writer import _ascii


def write_pdf(cam, data: dict, path: Path) -> None:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    W = 186
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(W, 9, _ascii(f"Old School extrinsic: {cam.van} {cam.camera}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=8)
    for line in (f"Created {data['created']}   serial {data['serial']}",
                 f"Old School folder: {data['old_school_folder']}",
                 f"Intrinsic: {data['intrinsic']}"):
        pdf.multi_cell(W, 4.2, _ascii(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    g = data["grade"]
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*((27, 94, 32) if g["passed"] else (183, 28, 28)))
    pdf.multi_cell(W, 6, _ascii(g["headline"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=8)
    for r in g["reasons"]:
        pdf.multi_cell(W, 4.2, _ascii("- " + r), new_x="LMARGIN", new_y="NEXT")
    for w in g["warnings"]:
        pdf.multi_cell(W, 4.2, _ascii("! " + w), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pt, lv, rw = data["pointing_deg"], data["lever_arm_m"], data["rwc_angles_unverified_deg"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(W, 5, "Camera on the van", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=8)
    rows = [("Pan (+ right of straight ahead)", f"{pt['pan_right']:.3f} deg"),
            ("Tilt (+ up)", f"{pt['tilt_up']:.3f} deg"),
            ("Roll (+ clockwise from behind)", f"{pt['roll_cw']:.3f} deg"),
            ("Setups disagree by up to", f"{pt['spread_between_setups_max']:.2f} deg"),
            ("Forward lever arm (rough, VBS)", f"{lv['forward']} m   spread {lv['forward_right_spread'][0] if lv['forward_right_spread'] else ''} m"),
            ("Right lever arm (rough, VBS)", f"{lv['right']} m   spread {lv['forward_right_spread'][1] if lv['forward_right_spread'] else ''} m"),
            ("Up: camera above the pavement", f"{lv['up_above_pavement']} m   spread {lv['up_spread']} m"),
            ("Camera height (NAVD88)", f"{lv['camera_height_navd88_m']} m"),
            ("RWC Heading/Pitch/Roll (UNVERIFIED)", f"{rw['heading_offset']} / {rw['pitch_offset']} / {rw['roll_offset']} deg")]
    for k, v in rows:
        pdf.cell(70, 4.5, _ascii(k)); pdf.cell(W - 70, 4.5, _ascii(v), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(W, 5, "Setups", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 7)
    cols = [("Setup", 30), ("Pass", 10), ("Targets", 13), ("Miss mm", 14), ("Range m", 14),
            ("Pan", 14), ("Tilt", 13), ("Roll", 13), ("Fwd m", 13), ("Right m", 13), ("Up m", 13), ("Seed", 26)]
    for c, w in cols:
        pdf.cell(w, 4.5, c, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", size=7)
    for s in data["setups"]:
        pt3 = s["pointing_deg"] or ["", "", ""]
        lv2 = s["lever_forward_right_m"] or ["", ""]
        vals = [s["name"], "yes" if s["passed"] else "NO", s["targets"], s["miss_rms_mm"], s["range_m"],
                *pt3, *lv2, s["up_above_pavement_m"], s["seed"]]
        for (c, w), v in zip(cols, vals):
            pdf.cell(w, 4.2, _ascii("" if v is None else str(v)), border=1)
        pdf.ln()
    for s in data["setups"]:
        for t in s["problems"] + s["old_click_checks"]:
            pdf.multi_cell(W, 4, _ascii(f"{s['name']}: {t}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", size=6.5)
    for n in data["notes"]:
        pdf.multi_cell(W, 3.4, _ascii(n), new_x="LMARGIN", new_y="NEXT")
    # overlays
    from src.extrinsic.outputs import overlay
    with tempfile.TemporaryDirectory() as td:
        for sr in cam.setups:
            img = overlay(sr, None, cam.K, cam.D)
            if img is None:
                continue
            p = Path(td) / f"{sr.setup.name}.jpg"
            cv2.imwrite(str(p), cv2.resize(img, (1280, int(1280 * img.shape[0] / img.shape[1]))),
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(W, 5, _ascii(sr.setup.name), new_x="LMARGIN", new_y="NEXT")
            pdf.image(str(p), w=W)
    pdf.output(str(path))
