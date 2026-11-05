"""pipeline.py — one camera folder, start to finish, no GUI.

The ONE calibration path.  Load Intrinsic and the CLI both call
run_folder(), so a fix here fixes all three:

  raw -> PNG (if any) -> board (auto-detect or given) -> detect -> filter
  -> wrong-size check -> unusable photos to NotUsed -> calibrate (bad photos
  left out automatically) -> grade -> compare to the filed intrinsic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MIN_DOTS_PER_IMAGE = 12      # dot boards: enough dots for a stable homography
CHESS_MIN_CORNERS = 6
CHESS_MIN_BLUR = 20.0        # chessboards only; dot boards use the dot-edge blur check


def subsample(paths: list[str], n: int) -> list[str]:
    """At most n paths, evenly spaced (keeps the first and last)."""
    if not n or len(paths) <= n:
        return paths
    step = (len(paths) - 1) / (n - 1)
    return [paths[round(i * step)] for i in range(n)]


@dataclass
class FolderRun:
    folder: str
    board: object = None
    board_note: str = ""                    # auto-detect summary
    detections: list = field(default_factory=list)
    filter_results: list = field(default_factory=list)
    cal: object = None
    vs_filed_10m_mm: float | None = None    # p95 difference to filed XML at 10 m
    moved: list = field(default_factory=list)   # (file, reason) moved to NotUsed
    move_note: str = ""
    error: str = ""

    @property
    def grade(self):
        return getattr(self.cal, "grade", None)

    @property
    def passed(self) -> bool:
        g = self.grade
        return bool(g is not None and g.passed and not self.error)


def run_folder(folder: str, max_images: int = 0, boards=None, board=None,
               filed_xml: str = "", progress_cb=None, change_folder: bool = True) -> FolderRun:
    """Calibrate and grade one folder of board photos.  Never raises: errors land in .error.

    change_folder: allowed to write into the photo folder — convert .raw files to
    PNG and move unusable photos to NotUsed.  The GUI always does; the CLI only
    when asked, so old data can be checked without rearranging it.  A quick look
    (max_images > 0) never changes the folder.
    """
    change_folder = change_folder and not max_images
    say = progress_cb or (lambda _m: None)
    r = FolderRun(folder=folder)
    try:
        from src.utils import find_images
        if change_folder:
            from src.raw_loader import convert_folder, pending_conversions
            if pending_conversions(folder):
                converted, failed = convert_folder(folder, progress_cb=say)
                say(f"Raw conversion: {len(converted)} converted"
                    + (f", {len(failed)} FAILED" if failed else ""))
        paths = subsample(find_images(folder), max_images)
        if not paths:
            r.error = "No JPG, PNG or RAW photos in this folder."
            return r

        if board is None:
            from src.boards import list_boards
            from src.auto_detect import auto_detect_board
            say("Finding the board…")
            res = auto_detect_board(paths, boards if boards is not None else list_boards(),
                                    progress_cb=say)
            r.board_note = res.summary()
            if res.board is None:
                r.error = (res.summary() + ".  Pick the board under Advanced, or add it in "
                           "the Boards tab, and run again.")
                return r
            board = res.board
        r.board = board

        from src.detector import detect_images
        from src.image_filter import filter_detections
        say(f"Detecting {board.name} in {len(paths)} photos…")
        r.detections = detect_images(paths, board, verbose=False, progress_cb=say)
        r.filter_results = filter_detections(
            r.detections,
            min_corners=MIN_DOTS_PER_IMAGE if board.is_dots else CHESS_MIN_CORNERS,
            min_blur=0.0 if board.is_dots else CHESS_MIN_BLUR)

        from src.not_used import mark_wrong_size, move_unusable
        mark_wrong_size(r.detections, r.filter_results)
        if change_folder:
            r.moved, r.move_note = move_unusable(folder, r.detections, r.filter_results)
            if r.move_note:
                say(r.move_note)

        say("Calibrating…")
        from src.auto_clean import calibrate_auto
        r.cal = calibrate_auto(r.detections, r.filter_results, board, progress_cb=say)

        say("Grading: coverage and repeatability…")
        from src.grading import grade, ray_disagreement_mrad
        r.cal.grade = grade(r.cal)

        if filed_xml:
            from src.van_scan import read_filed_xml
            f = read_filed_xml(filed_xml)
            size = tuple(r.cal.image_size)
            if f and (f["width"], f["height"]) == size:
                K2 = np.array([[f["fx"], 0, f["cx"]], [0, f["fy"], f["cy"]], [0, 0, 1.0]])
                D2 = np.array([f["k1"], f["k2"], f["p1"], f["p2"], f["k3"]])
                d = ray_disagreement_mrad(r.cal.camera_matrix, r.cal.dist_coeffs, K2, D2, size)
                r.vs_filed_10m_mm = float(np.percentile(d, 95) * 10.0)
    except Exception as exc:  # noqa: BLE001
        r.error = str(exc)
    # Every run leaves a <photo>.dots.json beside each photo (src/dot_files.py), pass or
    # fail, saved or not.  Not on a read-only CLI check (change_folder off).
    if change_folder and r.detections and r.board is not None:
        try:
            from src.dot_files import write_dot_files
            write_dot_files(r.cal, r.board, r.detections, r.filter_results)
        except Exception:  # noqa: BLE001 - never costs the run
            pass
    return r
