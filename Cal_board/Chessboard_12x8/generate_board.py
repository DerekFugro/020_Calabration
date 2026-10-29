"""generate_board.py — Render the physical calibration board to PNG and PDF.

Uses BoardConfig.get_charuco_board() from src/board.py (12x8 squares,
76.39 mm cell pitch, DICT_5X5_50 markers, 60 mm marker size) to produce:
  - Cal_board/Chessboard_12x8/calibration_board.png  (pixel image, 300 DPI)
  - Cal_board/Chessboard_12x8/calibration_board.pdf  (true physical size, for printing)

Run from the project root:  python Cal_board/Chessboard_12x8/generate_board.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
from fpdf import FPDF

from src.board import BoardConfig

OUTPUT_DIR = Path(__file__).resolve().parent
DPI = 300
MM_PER_IN = 25.4


def main() -> None:
    config = BoardConfig()
    board = config.get_charuco_board()

    board_width_mm = config.squares_x * config.cell_width_mm
    board_height_mm = config.squares_y * config.cell_height_mm

    px_width = round(board_width_mm / MM_PER_IN * DPI)
    px_height = round(board_height_mm / MM_PER_IN * DPI)

    img = board.generateImage((px_width, px_height), marginSize=0, borderBits=1)

    png_path = OUTPUT_DIR / "calibration_board.png"
    cv2.imwrite(str(png_path), img)
    print(f"Wrote {png_path}  ({px_width}x{px_height}px @ {DPI} DPI)")

    pdf_path = OUTPUT_DIR / "calibration_board.pdf"
    orientation = "L" if board_width_mm >= board_height_mm else "P"
    pdf = FPDF(orientation=orientation, unit="mm", format=(board_width_mm, board_height_mm))
    pdf.add_page()
    pdf.image(str(png_path), x=0, y=0, w=board_width_mm, h=board_height_mm)
    pdf.output(str(pdf_path))
    print(f"Wrote {pdf_path}  ({board_width_mm:.2f}mm x {board_height_mm:.2f}mm, true size)")

    print(
        f"\nBoard: {config.squares_x}x{config.squares_y} squares, "
        f"{config.cell_width_mm}mm cell pitch. Print the PDF at 100% scale "
        f"(no 'fit to page')."
    )


if __name__ == "__main__":
    main()
