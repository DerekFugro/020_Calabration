r"""cli.py — Command-line calibration (no GUI).

Examples (from the app folder):
    python cli.py --list-boards
    python cli.py "F:\...\Board\Rear\Rear"                      # auto-detect board
    python cli.py "F:\...\Board\ROW" --board ikea_road
    python cli.py "F:\...\Board\Rear\Rear" --serial 262503744 --role PAVE --save

--board takes "auto" (default) or a board name / Cal_board folder name.
--save writes the CAL_ YAML + PDF next to the images, exactly like the GUI's
Save.  The CLI never publishes to the calibration store; use the GUI for that.
"""

from __future__ import annotations

import argparse
import sys

from src.auto_detect import auto_detect_board
from src.boards import CAL_BOARD_DIR, find_board, list_boards
from src.calibrator import calibrate
from src.detector import detect_images
from src.image_filter import filter_detections
from src.quality import evaluate
from src.utils import find_images
from src.workers import MIN_DOTS_PER_IMAGE


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Camera intrinsic calibration (no GUI).")
    ap.add_argument("folder", nargs="?", help="folder of calibration images")
    ap.add_argument("--board", default="auto", help='"auto" or a board name')
    ap.add_argument("--list-boards", action="store_true", help="list the board library and exit")
    ap.add_argument("--min-blur", type=float, default=20.0)
    ap.add_argument("--serial", default="", help="camera serial (needed with --save)")
    ap.add_argument("--role", default="", help="camera role, e.g. PAVE or ROW")
    ap.add_argument("--save", action="store_true", help="write CAL_ YAML + PDF next to the images")
    a = ap.parse_args(argv)

    errors: list[str] = []
    boards = list_boards(errors=errors)
    for e in errors:
        print(f"WARNING: skipped board folder: {e}", file=sys.stderr)

    if a.list_boards:
        print(f"Board library: {CAL_BOARD_DIR}")
        for b in boards:
            extra = b.layout_csv if b.is_dots else f"{b.squares_x}x{b.squares_y} squares, {b.cell_width_mm} mm"
            print(f"  {b.name:<20} {b.kind:<10} {b.num_corners:>3} points   {extra}")
        return 0

    if not a.folder:
        ap.error("folder is required (or use --list-boards)")
    if a.save and not a.serial:
        ap.error("--save needs --serial")

    paths = find_images(a.folder)
    if not paths:
        print(f"No JPG/PNG images in {a.folder}", file=sys.stderr)
        return 2

    if a.board.lower() == "auto":
        res = auto_detect_board(paths, boards, progress_cb=lambda m: print(m, end="\r"))
        print(" " * 60, end="\r")
        print(res.summary())
        if res.board is None:
            print("Pick one with --board NAME (see --list-boards).", file=sys.stderr)
            return 3
        board = res.board
    else:
        board = find_board(a.board, boards)
        if board is None:
            print(f"Unknown board {a.board!r}; see --list-boards.", file=sys.stderr)
            return 2

    print(f"Detecting {board.name} in {len(paths)} images…")
    dets = detect_images(paths, board, verbose=False,
                         progress_cb=lambda m: print(m, end="\r"))
    print()
    min_pts = MIN_DOTS_PER_IMAGE if board.is_dots else 6
    filts = filter_detections(dets, min_corners=min_pts, min_blur=a.min_blur)
    n_ok = sum(f.accepted for f in filts)
    print(f"Accepted {n_ok} / {len(paths)} images")

    cal = calibrate(dets, filts, board)
    q = evaluate(cal)
    K, D = cal.camera_matrix, cal.dist_coeffs.ravel()
    print(f"RMS {cal.rms:.3f} px   {q.verdict}   images {cal.image_count_used}   points {cal.point_count_used}")
    print(f"fx {K[0,0]:.3f}  fy {K[1,1]:.3f}  cx {K[0,2]:.3f}  cy {K[1,2]:.3f}")
    print("dist " + "  ".join(f"{v:.8f}" for v in D))
    print("worst images: " + ", ".join(f"{p.split(chr(92))[-1].split('/')[-1]} {e:.2f}px"
                                       for p, e in cal.per_image_errors[:5]))

    if a.save:
        from src.output_writer import write_outputs
        y, p = write_outputs(cal, q, board, a.serial, dets, filts, a.folder, role=a.role.upper())
        print(f"Wrote {y}\nWrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
