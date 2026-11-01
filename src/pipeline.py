"""pipeline.py — one camera folder, start to finish, no GUI.

auto-detect board -> detect -> filter -> calibrate -> grade -> compare to the
filed intrinsic.  Used by the van table (Load Intrinsic tab) and the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.auto_detect import auto_detect_board
from src.boards import list_boards
from src.calibrator import calibrate
from src.detector import detect_images
from src.image_filter import filter_detections
from src.quality import evaluate
from src.utils import find_images

MIN_DOTS_PER_IMAGE = 12


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
    detections: list = field(default_factory=list)
    filter_results: list = field(default_factory=list)
    cal: object = None
    quality: object = None
    vs_filed_10m_mm: float | None = None   # p95 difference to filed XML at 10 m
    moved: list = field(default_factory=list)   # (file, reason) moved to NotUsed
    move_note: str = ""
    error: str = ""

    @property
    def grade(self):
        return getattr(self.cal, "grade", None)


def run_folder(folder: str, max_images: int = 0, boards=None, board=None,
               filed_xml: str = "", min_blur: float = 20.0,
               progress_cb=None, move_unused: bool = False) -> FolderRun:
    say = progress_cb or (lambda _m: None)
    r = FolderRun(folder=folder)
    try:
        boards = boards if boards is not None else list_boards()
        paths = subsample(find_images(folder), max_images)
        if not paths:
            r.error = "no photos"; return r
        if board is None:
            say("finding the board")
            res = auto_detect_board(paths, boards)
            if res.board is None:
                r.error = "no calibration board found"; return r
            board = res.board
        r.board = board
        say(f"detecting {board.name} in {len(paths)} photos")
        r.detections = detect_images(paths, board, verbose=False)
        r.filter_results = filter_detections(
            r.detections,
            min_corners=MIN_DOTS_PER_IMAGE if board.is_dots else 6,
            min_blur=0.0 if board.is_dots else min_blur)
        from src.not_used import mark_wrong_size, move_unusable
        mark_wrong_size(r.detections, r.filter_results)
        if move_unused and not max_images:
            r.moved, r.move_note = move_unusable(folder, r.detections, r.filter_results)
            if r.move_note:
                say(r.move_note)
        say("calibrating")
        from src.auto_clean import calibrate_auto
        r.cal = calibrate_auto(r.detections, r.filter_results, board, progress_cb=say)
        r.quality = evaluate(r.cal)
        say("grading")
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
    return r
