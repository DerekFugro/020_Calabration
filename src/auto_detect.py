"""auto_detect.py — Work out which library board appears in an image folder.

One board per calibration run (Derek, 2026-10-29), so the board is decided
once, from a spread of sample images, not per image.

For each sample image every board in the library is tried:
  * chessboards: cv2.findChessboardCorners on a reduced-size copy (fast check), then -
    if that misses - the same full-size findChessboardCornersSB the detector uses.  The
    fast check alone missed every sample of Derek's GOX photos (3840x2160, board close
    to the camera) that the detector reads fine (2026-11-14);
  * dot boards:  blobs are found once, then matched against each layout CSV.
    A wrong layout matches only a few dots by chance and is rejected by
    match_dots' "half the visible dots" rule.
The board found in the most sample images wins; ties go to the board whose
matches cover more of its points.  At least two sample images (or all of
them when fewer than two were sampled) must agree, otherwise no board is
chosen and the user must pick one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from src.board import BoardConfig
from src.dot_detector import detect_blobs, match_dots

DEFAULT_SAMPLES = 8
_CHESS_MAX_W = 1440


@dataclass
class AutoDetectResult:
    board: BoardConfig | None
    # per board name: (images found in, mean fraction of board points matched)
    scores: dict = field(default_factory=dict)
    samples: int = 0

    def summary(self) -> str:
        parts = [f"{n}: {c}/{self.samples} images" + (f" ({f:.0%} of points)" if c else "")
                 for n, (c, f) in sorted(self.scores.items(), key=lambda kv: -kv[1][0])]
        head = (f"Auto-detected board: {self.board.name}" if self.board
                else "Auto-detect could not identify the board")
        return f"{head}  —  " + "; ".join(parts)


def _sample(paths: list[str], n: int) -> list[str]:
    if len(paths) <= n:
        return list(paths)
    idx = np.linspace(0, len(paths) - 1, n).round().astype(int)
    return [paths[i] for i in sorted(set(idx))]


def _chessboard_found(gray: np.ndarray, board: BoardConfig) -> bool:
    pattern = (board.squares_x - 1, board.squares_y - 1)
    h, w = gray.shape[:2]
    small = gray
    if w > _CHESS_MAX_W:
        s = _CHESS_MAX_W / w
        small = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    small = cv2.copyMakeBorder(small, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
    flags = (cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
             | cv2.CALIB_CB_FAST_CHECK)
    found, _ = cv2.findChessboardCorners(small, pattern, flags)
    if found:
        return True
    # What the detector does (src/detector.py): SB on the full-size picture, white border.
    from src.detector import _CB_FLAGS_SB
    full = cv2.copyMakeBorder(gray, 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=255)
    found, _ = cv2.findChessboardCornersSB(full, pattern, _CB_FLAGS_SB)
    return bool(found)


def auto_detect_board(image_paths: list[str], boards: list[BoardConfig],
                      n_samples: int = DEFAULT_SAMPLES,
                      progress_cb=None) -> AutoDetectResult:
    """Pick the library board that appears in these images (or None)."""
    samples = _sample(sorted(image_paths), n_samples)
    hits = {b.name: [] for b in boards}
    for k, path in enumerate(samples, 1):
        if progress_cb:
            progress_cb(f"Auto-detecting board: image {k} / {len(samples)}…")
        gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        size = (gray.shape[1], gray.shape[0])
        blobs = None
        for b in boards:
            if b.is_dots:
                if blobs is None:
                    blobs = detect_blobs(gray)
                m = match_dots(blobs, b.dot_xy_mm, image_size=size)
                if m is not None:
                    hits[b.name].append(len(m.ids) / b.num_corners)
            elif _chessboard_found(gray, b):
                hits[b.name].append(1.0)

    scores = {n: (len(v), float(np.mean(v)) if v else 0.0) for n, v in hits.items()}
    need = min(2, len(samples))
    ranked = sorted(boards, key=lambda b: scores[b.name], reverse=True)
    best = ranked[0] if ranked and scores[ranked[0].name][0] >= max(need, 1) else None
    return AutoDetectResult(board=best, scores=scores, samples=len(samples))
