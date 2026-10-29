"""make_dot_board_pdf.py - draw a random-dot board as a true-scale vector PDF from its CSV.

CSV format (space separated, metres): 0, id, x, 0, z, 0, -1, 0, radius
x = right, z = up, origin = board centre.

Usage (from Cal_board):
  python make_dot_board_pdf.py <csv> <out.pdf> --page 1400 600 --frame 1360 540 --label roadware_140_60_003 --centre-from-top 309.5
"""
import argparse
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

ap = argparse.ArgumentParser()
ap.add_argument("csv"); ap.add_argument("out")
ap.add_argument("--page", nargs=2, type=float, default=[1400, 600], help="page W H in mm")
ap.add_argument("--frame", nargs=2, type=float, default=[1360, 540], help="blue frame W H in mm")
ap.add_argument("--label", default="")
ap.add_argument("--label-width", type=float, default=194.0, help="label text width in mm")
ap.add_argument("--centre-from-top", type=float, default=None, help="board centre distance from page top, mm (default: page middle)")
ap.add_argument("--halo", type=float, default=6.5, help="white gap around dots on blue lines, mm")
a = ap.parse_args()

dots = []
for line in open(a.csv):
    v = line.split()
    if len(v) >= 9:
        dots.append((float(v[2]) * 1000, float(v[4]) * 1000, float(v[8]) * 1000))

W, H = a.page; FW, FH = a.frame
cx = W / 2
cy = H / 2 if a.centre_from_top is None else H - a.centre_from_top
c = canvas.Canvas(a.out, pagesize=(W * mm, H * mm))
c.setTitle(a.label or "dot board")
blue = (0.35, 0.35, 0.95)

# blue centre lines (full page) and frame, 1 mm wide
c.setStrokeColorRGB(*blue); c.setLineWidth(1 * mm)
c.line(0, cy * mm, W * mm, cy * mm)
c.line(cx * mm, 0, cx * mm, H * mm)
c.rect((cx - FW / 2) * mm, (cy - FH / 2) * mm, FW * mm, FH * mm, stroke=1, fill=0)

# white halos, then black dots, then small grey centre marks
c.setFillColorRGB(1, 1, 1)
for x, z, r in dots:
    c.circle((cx + x) * mm, (cy + z) * mm, (r + a.halo) * mm, stroke=0, fill=1)
c.setFillColorRGB(0, 0, 0)
for x, z, r in dots:
    c.circle((cx + x) * mm, (cy + z) * mm, r * mm, stroke=0, fill=1)
c.setFillColorRGB(0.76, 0.76, 0.76)
for x, z, r in dots:
    c.circle((cx + x) * mm, (cy + z) * mm, 0.5 * mm, stroke=0, fill=1)

if a.label:
    fs = a.label_width * mm / stringWidth(a.label, "Helvetica", 1)
    c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica", fs)
    c.drawString(21 * mm, (H - 37.5) * mm, a.label)

c.showPage(); c.save()
print(f"wrote {a.out}: {len(dots)} dots, page {W} x {H} mm")
