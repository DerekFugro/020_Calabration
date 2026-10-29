"""generate_ground_truth_pdf.py — PDF report of the board's ground-truth data.

Formats the measurement of record from references/BoardTrueSize.md (the
LIVE reference for cell pitch and how it was derived) into a printable PDF,
as a companion to the board PDF itself (calibration_board_plain.pdf).

Run from the project root:  python Cal_board/Chessboard_12x8/generate_ground_truth_pdf.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from fpdf import FPDF

from src.board import BoardConfig

OUTPUT_DIR = Path(__file__).resolve().parent

TITLE_SIZE = 16
H2_SIZE = 12
BODY_SIZE = 10
SMALL_SIZE = 8.5
MARGIN = 18


class GroundTruthPDF(FPDF):
    def header(self) -> None:
        pass

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def h1(self, text: str) -> None:
        self.set_font("Helvetica", "B", TITLE_SIZE)
        self.set_text_color(20, 20, 20)
        self.multi_cell(0, 8, text)
        self.ln(1)

    def h2(self, text: str) -> None:
        self.ln(3)
        self.set_font("Helvetica", "B", H2_SIZE)
        self.set_text_color(20, 20, 20)
        self.multi_cell(0, 7, text)
        self.ln(0.5)

    def body(self, text: str) -> None:
        self.set_font("Helvetica", "", BODY_SIZE)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def small(self, text: str) -> None:
        self.set_font("Helvetica", "I", SMALL_SIZE)
        self.set_text_color(90, 90, 90)
        self.multi_cell(0, 4.5, text)
        self.ln(1)

    def table(self, header: list[str], rows: list[list[str]], col_widths: list[float]) -> None:
        self.set_font("Helvetica", "B", SMALL_SIZE)
        self.set_fill_color(230, 230, 230)
        self.set_text_color(20, 20, 20)
        for w, h in zip(col_widths, header):
            self.cell(w, 6.5, h, border=1, fill=True)
        self.ln()
        self.set_font("Helvetica", "", SMALL_SIZE)
        self.set_fill_color(255, 255, 255)
        for row in rows:
            for w, val in zip(col_widths, row):
                self.cell(w, 6.5, val, border=1)
            self.ln()
        self.ln(2)


def main() -> None:
    config = BoardConfig()

    pdf = GroundTruthPDF(orientation="P", unit="mm", format="Letter")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, margin=MARGIN)
    pdf.add_page()

    pdf.h1("Calibration Board -- Ground Truth Measurement Data")
    pdf.small(
        "Status: LIVE reference for this app. Measurement of record for the "
        "physical board.\n"
        "Measured: 2026-08-18 by Derek, digital calipers.\n"
        "In force: src/board.py uses these values as of 2026-08-18 "
        f"(DEFAULT_CELL_WIDTH_MM = DEFAULT_CELL_HEIGHT_MM = {config.cell_width_mm} mm).\n"
        "Source: references/BoardTrueSize.md. Superseded history: "
        "references/CalibrationBoard.txt."
    )

    pdf.h2("1. The board")
    pdf.body(
        f"{config.squares_x} x {config.squares_y} squares, "
        f"{config.squares_x - 1} x {config.squares_y - 1} interior corners "
        f"({config.num_corners} corners total), printed on white stock mounted "
        "on cardboard, with four square-in-square fiducial markers in the "
        "corner cells.\n"
        "[measured] -- confirmed by running cv2.findChessboardCornersSB over "
        "H:\\Camera Calibration Files\\Pave\\TDR054S-C_234500499_260811190327_"
        f"image24.png: locks on at {config.squares_x - 1} x {config.squares_y - 1} "
        f"and returns {config.num_corners} corners.\n\n"
        "The corner fiducials are plain square-in-square marks, not ArUco "
        "patterns, and are not used for detection. Detection is plain "
        "chessboard; the ArUco module is never called (see src/detector.py)."
    )

    pdf.h2("2. Measurement of record")
    pdf.table(
        header=["Quantity", "Value", "How"],
        rows=[
            ["Cell pitch", "76.39 mm", "152.78 mm across 2 cells / 2  [measured]"],
            ["Cell pitch, inches", "3.0075 in", "= 76.39 / 25.4  [measured]"],
            ["Single square, own width", "76.59 mm", "calipers, edge to edge  [measured]"],
            ["Ink spread", "0.10 mm/edge", "(76.59 - 76.39) / 2  [inference]"],
        ],
        col_widths=[52, 32, 92],
    )
    pdf.body(
        "Cross-check, steel tape over 10 cells: 765 mm -> 76.50 mm/cell "
        "[measured], 0.14% above the caliper figure. Consistent within tape "
        "resolution."
    )
    pdf.body(
        "Method -- why 2 cells and not 1: measure the same edge on two cells "
        "two columns apart (white->grey to white->grey). Both jaws then sit "
        "on the same kind of transition and printed ink spread cancels. "
        "Measuring a single square's own width puts one jaw on a white->grey "
        "edge and the other on grey->white, so the spread is added to the "
        "reading -- the single square read 0.20 mm larger than the true "
        "pitch, every time, in one direction: a repeatable bias, not noise."
    )
    pdf.small(
        "Anyone re-measuring this board: span 2 cells, same edge to same "
        "edge. Do not measure one square."
    )

    pdf.h2("3. What the app uses, and why the change was safe")
    pdf.body(
        f"src/board.py sets DEFAULT_CELL_WIDTH_MM = DEFAULT_CELL_HEIGHT_MM = "
        f"{config.cell_width_mm} [measured] as of 2026-08-18. It previously "
        "held 76.2 (3.000 in), the assumed nominal, never measured.\n\n"
        "A uniform scale error in the board has no effect on the intrinsics "
        "[measured] -- tested directly by calibrating one fixed set of "
        "synthetic images while varying only the cell size given to "
        "calibrate()."
    )
    pdf.table(
        header=["Cell size entered", "fx/fy", "RMS"],
        rows=[
            ["76.2 x 76.2 (truth)", "0.999986", "0.046367"],
            ["77.2 x 77.2 (+1.3%)", "0.999986", "0.046367"],
            ["70.0 x 70.0 (-8.1%)", "0.999986", "0.046367"],
            ["3.0 x 3.0 (inches, not mm)", "0.999986", "0.046367"],
            ["76.465 x 76.002 (non-square)", "0.994037", "0.046376"],
            ["76.2 x 74.0 (3% off in y)", "0.971850", "0.046378"],
        ],
        col_widths=[76, 34, 34],
    )
    pdf.body(
        "The object points scale, the recovered translation vectors scale "
        "with them, and fx, fy, cx, cy and the distortion coefficients come "
        "out identical -- even for a 25x error. Only the ratio between cell "
        "width and cell height moves the result.\n\n"
        "So 76.39 and 76.2 produce identical intrinsics. The change was made "
        "because the app should state what was measured rather than what was "
        "assumed -- not because it improves anything numerically. The two "
        "calibrations already in the store were computed with 76.2 and "
        "remain valid; new calibrations record 76.39."
    )

    pdf.h2("4. Squareness -- the thing that actually matters")
    pdf.body(
        "The Pave calibration of record reports fx/fy = 0.999836 -- 0.016% "
        "from square [measured], across 53 images and 77 corners each. If "
        "the board were even 0.2% non-square, calibrating with square cells "
        "would have dragged fx/fy to about 0.998. It did not.\n\n"
        "The camera measures the board's squareness roughly 10x finer than "
        "calipers can. Hand measurement is a gross-error check here (wrong "
        "board, inches/mm mix-up, a warped or shrunken board), not a "
        "refinement."
    )

    pdf.h2("5. Open items")
    pdf.body(
        "1. Vertical 2-cell span not yet independently measured -- cell "
        "HEIGHT = 76.39 assumes the vertical matches the horizontal. The "
        "calibration's own fx/fy = 0.999836 says the two directions agree "
        "to 0.016%, far finer than calipers resolve. Worth one reading if "
        "the board is ever reprinted. Expect ~152.78 mm.\n\n"
        "2. Flatness not checked -- a bowed board is a real error source "
        "and no cell measurement detects it. Lay a straightedge across both "
        "diagonals."
    )

    pdf.h2("6. When the absolute size DOES matter")
    pdf.body(
        "Anything that solves distance, height or scale from the board's "
        "pose (rvecs/tvecs) rather than from a physical reference. Using "
        "76.2 where the truth is 76.39 biases such a result by +0.25% "
        "[inference].\n\n"
        "H:\\Camera Calibration Files\\barcheck.py measures a known-length "
        "bar, not the board, so it is unaffected today. If a board-pose "
        "method is ever added, use 76.39 mm and re-measure both directions "
        "first."
    )

    out_path = OUTPUT_DIR / "board_ground_truth.pdf"
    pdf.output(str(out_path))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
