r"""cli.py — Command-line calibration (no GUI).

Examples (from the app folder):
    python cli.py --list-boards
    python cli.py "F:\...\Board\Rear\Rear"                      # auto-detect board
    python cli.py "F:\...\Board\ROW" --board ikea_road
    python cli.py "F:\...\Board\Rear\Rear" --serial 262503744 --role PAVE --save
    python cli.py "F:\...\Images\ForwardRight" --van ARAN65 --role ForwardRight --serial 101324 --export out
    python cli.py --grade-all "F:\Camera Calibrations" --csv grades.csv --workers 8

--board takes "auto" (default) or a board name / Cal_board folder name.
--save writes the CAL_ YAML + PDF next to the images, exactly like the GUI's
Save.  The CLI never publishes to the calibration store; use the GUI for that.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

from src.boards import CAL_BOARD_DIR, find_board, list_boards
from src.pipeline import run_folder


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Camera intrinsic calibration (no GUI).")
    ap.add_argument("folder", nargs="?", help="folder of calibration images")
    ap.add_argument("--board", default="auto", help='"auto" or a board name')
    ap.add_argument("--list-boards", action="store_true", help="list the board library and exit")
    ap.add_argument("--serial", default="", help="camera serial (needed with --save)")
    ap.add_argument("--role", default="", help="camera role, e.g. PAVE or ROW")
    ap.add_argument("--save", action="store_true", help="write CAL_ YAML + PDF next to the images")
    ap.add_argument("--move-unused", action="store_true",
                    help="change the folder like the GUI does: convert .raw files to PNG and move "
                         "unreadable / no-board / wrong-size photos to a NotUsed subfolder")
    ap.add_argument("--van", default="", help="van name, e.g. ARAN65 (for --export)")
    ap.add_argument("--export", metavar="OUTDIR", help="write every format (fleet XML, PG RWC, OpenCV, ROS, "
                    "Kalibr, COLMAP, Metashape, JSON, CSV) into OUTDIR; needs --van, --role, --serial")
    ap.add_argument("--grade-all", metavar="ROOT", help="grade every image folder (>= 30 images) under ROOT")
    ap.add_argument("--csv", default="grades.csv", help="output CSV for --grade-all")
    ap.add_argument("--workers", type=int, default=1, help="parallel folders for --grade-all")
    ap.add_argument("--max-images", type=int, default=0, help="use at most N images, evenly spaced (0 = all)")
    a = ap.parse_args(argv)

    if a.grade_all:
        return grade_all(a.grade_all, a.csv, a.workers, a.max_images)

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
    if a.export and not (a.van and a.role and a.serial):
        ap.error("--export needs --van, --role and --serial")

    board = None
    if a.board.lower() != "auto":
        board = find_board(a.board, boards)
        if board is None:
            print(f"Unknown board {a.board!r}; see --list-boards.", file=sys.stderr)
            return 2

    run = run_folder(a.folder, a.max_images, boards=boards, board=board,
                     progress_cb=lambda m: print(m), change_folder=a.move_unused)
    if run.board_note:
        print(run.board_note)
    if run.error:
        print(run.error, file=sys.stderr)
        return 3
    cal = run.cal
    from src.auto_clean import removed_text
    for line in removed_text(cal):
        print("left out: " + line)
    K, D = cal.camera_matrix, cal.dist_coeffs.ravel()
    print(f"RMS {cal.rms:.3f} px   images {cal.image_count_used}   points {cal.point_count_used}")
    print(f"fx {K[0,0]:.3f}  fy {K[1,1]:.3f}  cx {K[0,2]:.3f}  cy {K[1,2]:.3f}")
    print("dist " + "  ".join(f"{v:.8f}" for v in D))
    print()
    print(cal.grade.as_text())
    board = run.board

    if a.export:
        from src.export_formats import Intrinsics, export_all
        from src.van_scan import camera_from_name
        cam = camera_from_name(a.role) or a.role
        files = export_all(Intrinsics.from_result(cal, a.van.upper(), cam, a.serial, board=board.name,
                                                  image_folder=os.path.abspath(a.folder)), a.export)
        print(f"Wrote {len(files)} files to {a.export}" + ("" if cal.grade.passed else "  (NOT_PASSED_ prefix)"))

    if a.save:
        from src.output_writer import write_outputs
        y, p = write_outputs(cal, board, a.serial, run.detections, run.filter_results, a.folder,
                             role=a.role.upper())
        print(f"Wrote {y}\nWrote {p}")
    return 0


def grade_folder(args) -> dict:
    """Auto-detect, calibrate and grade one folder; returns one CSV row."""
    folder, max_images = args
    import cv2
    cv2.setNumThreads(1)
    row = {"folder": folder}
    run = run_folder(folder, max_images, change_folder=False)
    row["images"] = len(run.detections)
    if run.board is not None:
        row["board"] = run.board.name
    if run.error:
        row["headline"] = f"ERROR: {run.error}"
        return row
    cal, g = run.cal, run.grade
    K, rp = cal.camera_matrix, g.repeatability
    row.update(passed=g.passed, headline=g.headline, used=cal.image_count_used,
               rms_px=round(cal.rms, 3), fx=round(K[0, 0], 2), cx=round(K[0, 2], 2), cy=round(K[1, 2], 2),
               repeat_10m_mm=None if rp is None else round(rp.at_10m_mm, 1),
               blur_px=None if g.blur_median_px != g.blur_median_px else round(g.blur_median_px, 2),
               areas_short=sum(c.points_status != 'good' for c in g.grid.flat) if g.grid else None,
               areas_low_tilt=sum(c.points > 0 and c.tilt_status != 'good' for c in g.grid.flat) if g.grid else None,
               more_photos=g.more_photos, hard_stops=' | '.join(g.hard_stops),
               reasons=' | '.join(g.reasons), coaching=' | '.join(g.coaching))
    return row


def grade_all(root: str, out_csv: str, workers: int, max_images: int) -> int:
    """Grade every folder under root that holds >= 30 images."""
    folders = [d for d, _, fs in os.walk(root)
               if os.path.basename(d).lower() != "notused" and sum(f.lower().endswith(('.jpg', '.jpeg', '.png')) for f in fs) >= 30]
    print(f"{len(folders)} image folders under {root}")
    cols = ["folder", "board", "passed", "headline", "images", "used", "rms_px", "repeat_10m_mm", "blur_px",
            "areas_short", "areas_low_tilt", "more_photos", "fx", "cx", "cy", "hard_stops", "reasons", "coaching"]
    jobs = [(f, max_images) for f in sorted(folders)]
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); wr.writeheader()
        if workers > 1:
            from multiprocessing import Pool
            with Pool(workers) as pool:
                it = pool.imap_unordered(grade_folder, jobs)
                for i, row in enumerate(it, 1):
                    wr.writerow(row); fh.flush(); print(f"[{i}/{len(jobs)}] {row.get('headline')}  {row['folder']}")
        else:
            for i, job in enumerate(jobs, 1):
                row = grade_folder(job)
                wr.writerow(row); fh.flush(); print(f"[{i}/{len(jobs)}] {row.get('headline')}  {row['folder']}")
    print(f"Wrote {out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
