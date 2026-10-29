"""generate_board_plain.py — Render a faithful copy of the PHYSICAL board.

Unlike generate_board.py (which renders a true ChArUco board with real ArUco
bit-pattern markers via cv2.aruco), this matches what the photographed board
actually has: a plain checkerboard with a simple hollow square-in-square
mark in each of the four corner cells (no ArUco bit pattern). Confirmed
against H:\\Camera Calibration Files\\Pave\\TDR054S-C_234500499_260811190327_image24.png.

Board geometry (squares_x, squares_y, cell size) is pulled from
src.board.BoardConfig so it stays in sync with the app's live values.

Produces:
  - Cal_board/Chessboard_12x8/calibration_board_plain.png  (300 DPI)
  - Cal_board/Chessboard_12x8/calibration_board_plain.pdf  (true physical size, for printing)

Run from the project root:  python Cal_board/Chessboard_12x8/generate_board_plain.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

from src.board import BoardConfig

OUTPUT_DIR = Path(__file__).resolve().parent
DPI = 300
MM_PER_IN = 25.4

DARK_SQUARE_RGB = (58, 58, 64)
WHITE_RGB = (255, 255, 255)
TEXT_RGB = (20, 20, 20)
MARGIN_CELLS = 1.0          # white margin around the checker pattern, in cell units
FIDUCIAL_HOLE_RATIO = 0.45  # inner white hole, as a fraction of the cell size
SCALE_BAR_MM = 50.0         # printed ruler for verifying print-at-100% scale

FONT_DIR = Path("C:/Windows/Fonts")


def mm_to_px(mm: float) -> int:
    return round(mm / MM_PER_IN * DPI)


def pt_to_px(pt: float) -> int:
    return round(pt * DPI / 72)


def load_font(name: str, size_pt: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), pt_to_px(size_pt))


def main() -> None:
    config = BoardConfig()
    cell_px_x = mm_to_px(config.cell_width_mm)
    cell_px_y = mm_to_px(config.cell_height_mm)
    margin_px_x = round(cell_px_x * MARGIN_CELLS)
    margin_px_y = round(cell_px_y * MARGIN_CELLS)

    board_px_w = config.squares_x * cell_px_x
    board_px_h = config.squares_y * cell_px_y
    img_w = board_px_w + 2 * margin_px_x
    img_h = board_px_h + 2 * margin_px_y

    img = Image.new("RGB", (img_w, img_h), WHITE_RGB)
    draw = ImageDraw.Draw(img)

    # Checkerboard squares
    for row in range(config.squares_y):
        for col in range(config.squares_x):
            if (row + col) % 2 == 1:
                continue  # leave white square unpainted
            x0 = margin_px_x + col * cell_px_x
            y0 = margin_px_y + row * cell_px_y
            draw.rectangle([x0, y0, x0 + cell_px_x, y0 + cell_px_y], fill=DARK_SQUARE_RGB)

    # Corner fiducials: solid cell + centered white hole, all four identical,
    # overriding whatever the checker pattern would have put there.
    corners = [(0, 0), (0, config.squares_x - 1), (config.squares_y - 1, 0),
               (config.squares_y - 1, config.squares_x - 1)]
    hole_w = round(cell_px_x * FIDUCIAL_HOLE_RATIO)
    hole_h = round(cell_px_y * FIDUCIAL_HOLE_RATIO)
    for row, col in corners:
        x0 = margin_px_x + col * cell_px_x
        y0 = margin_px_y + row * cell_px_y
        draw.rectangle([x0, y0, x0 + cell_px_x, y0 + cell_px_y], fill=DARK_SQUARE_RGB)
        hx0 = x0 + (cell_px_x - hole_w) // 2
        hy0 = y0 + (cell_px_y - hole_h) // 2
        draw.rectangle([hx0, hy0, hx0 + hole_w, hy0 + hole_h], fill=WHITE_RGB)

    # --- Top margin: title + key numbers ---
    title_font = load_font("arialbd.ttf", 26)
    subtitle_font = load_font("arial.ttf", 15)
    pattern_mm_w = config.squares_x * config.cell_width_mm
    pattern_mm_h = config.squares_y * config.cell_height_mm
    title = (
        f"Calibration Board -- {config.squares_x} x {config.squares_y} squares, "
        f"{config.cell_width_mm:g} mm cell pitch"
    )
    subtitle = (
        f"Interior corners {config.squares_x - 1} x {config.squares_y - 1} "
        f"({config.num_corners} total)  |  Checker pattern "
        f"{pattern_mm_w:.2f} x {pattern_mm_h:.2f} mm  |  Measured 2026-08-18, "
        f"digital calipers  |  src/board.py DEFAULT_CELL_WIDTH_MM = "
        f"DEFAULT_CELL_HEIGHT_MM = {config.cell_width_mm:g}"
    )
    draw.text((margin_px_x, mm_to_px(6)), title, font=title_font, fill=TEXT_RGB)
    draw.text((margin_px_x, mm_to_px(6) + pt_to_px(26) + mm_to_px(3)), subtitle,
              font=subtitle_font, fill=TEXT_RGB)

    # --- Bottom margin: printed ruler (verify print came out at 100% scale) ---
    bar_font = load_font("arial.ttf", 13)
    dims_font = load_font("arialbd.ttf", 14)
    bar_px_len = mm_to_px(SCALE_BAR_MM)
    bar_x0 = margin_px_x
    bar_y = img_h - margin_px_y + mm_to_px(14)
    tick_h = mm_to_px(3)
    draw.line([(bar_x0, bar_y), (bar_x0 + bar_px_len, bar_y)], fill=TEXT_RGB, width=3)
    for mm_mark in range(0, int(SCALE_BAR_MM) + 1, 10):
        x = bar_x0 + mm_to_px(mm_mark)
        draw.line([(x, bar_y - tick_h), (x, bar_y + tick_h)], fill=TEXT_RGB, width=3)
        label = f"{mm_mark}"
        draw.text((x, bar_y + tick_h + mm_to_px(1.5)), label, font=bar_font,
                   fill=TEXT_RGB, anchor="ma")
    draw.text((bar_x0 + bar_px_len + mm_to_px(4), bar_y), "<- 50 mm ruler: "
              "measure this on the printed page to confirm 100% scale",
              font=bar_font, fill=TEXT_RGB, anchor="lm")

    dims_line = (
        f"Full sheet {img_w / DPI * MM_PER_IN:.2f} x {img_h / DPI * MM_PER_IN:.2f} mm"
        f"  |  PRINT AT 100% SCALE -- do not use 'fit to page'"
    )
    draw.text((margin_px_x, img_h - margin_px_y + mm_to_px(24)), dims_line,
               font=dims_font, fill=TEXT_RGB)

    png_path = OUTPUT_DIR / "calibration_board_plain.png"
    img.save(png_path, dpi=(DPI, DPI))
    print(f"Wrote {png_path}  ({img_w}x{img_h}px @ {DPI} DPI)")

    board_mm_w = img_w / DPI * MM_PER_IN
    board_mm_h = img_h / DPI * MM_PER_IN
    pdf_path = OUTPUT_DIR / "calibration_board_plain.pdf"
    orientation = "L" if board_mm_w >= board_mm_h else "P"
    pdf = FPDF(orientation=orientation, unit="mm", format=(board_mm_w, board_mm_h))
    pdf.add_page()
    pdf.image(str(png_path), x=0, y=0, w=board_mm_w, h=board_mm_h)
    pdf.output(str(pdf_path))
    print(f"Wrote {pdf_path}  ({board_mm_w:.2f}mm x {board_mm_h:.2f}mm, true size)")

    print(
        f"\nBoard: {config.squares_x}x{config.squares_y} squares, "
        f"{config.cell_width_mm}mm cell pitch, plain square-in-square corner "
        f"fiducials (no ArUco pattern). Print the PDF at 100% scale."
    )


if __name__ == "__main__":
    main()
