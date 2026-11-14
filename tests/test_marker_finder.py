"""The 12x8 board's own finder (src/marker_finder.py): hollow corner markers sit where a
white square would be (the physical board, 2026-11-14)."""
import cv2
import numpy as np

from src.board import BoardConfig
from src.marker_finder import find_marker_corners, outer_ids

SX, SY, CELL = 12, 8, 60


def board_picture(cell=CELL, margin=120, shift=(0, 0), angle=0.0, size=(1600, 1000)):
    """The physical board: chessboard with (0, 0) white; each corner cell dark with a centred
    white hole 45 % wide.  Returns (picture, true inside-corner positions in row-major order)."""
    bw, bh = SX * cell + 2 * margin, SY * cell + 2 * margin
    img = np.full((bh, bw), 235, np.uint8)
    for r in range(SY):
        for c in range(SX):
            if (r + c) % 2 == 1:
                img[margin + r * cell:margin + (r + 1) * cell, margin + c * cell:margin + (c + 1) * cell] = 25
    hole = int(round(0.45 * cell)); off = (cell - hole) // 2
    for r, c in ((0, 0), (0, SX - 1), (SY - 1, 0), (SY - 1, SX - 1)):
        y0, x0 = margin + r * cell, margin + c * cell
        img[y0:y0 + cell, x0:x0 + cell] = 25
        img[y0 + off:y0 + off + hole, x0 + off:x0 + off + hole] = 235
    # an edge drawn at pixel k lies at k - 0.5 in pixel-centre coordinates
    pts = np.array([[margin + c * cell - 0.5, margin + r * cell - 0.5] for r in range(1, SY) for c in range(1, SX)], np.float32)
    W, H = size
    M = cv2.getRotationMatrix2D((bw / 2, bh / 2), angle, 1.0)
    M[:, 2] += (W / 2 - bw / 2 + shift[0], H / 2 - bh / 2 + shift[1])
    out = cv2.warpAffine(img, M, (W, H), borderValue=150)
    true = (pts @ M[:, :2].T + M[:, 2]).astype(np.float32)
    return cv2.GaussianBlur(out, (3, 3), 0), true


def _check(img, true):
    corners, ids = find_marker_corners(img, SX, SY)
    assert corners is not None
    assert len(ids) == 73 and not (set(ids.tolist()) & outer_ids(SX, SY))     # 4 marker corners left out
    got = corners.reshape(-1, 2)
    d1 = np.linalg.norm(got - true[ids], axis=1).max()
    d2 = np.linalg.norm(got - true[::-1][ids], axis=1).max()                   # 180 deg: same board
    assert min(d1, d2) < 0.3


def test_finds_the_board_straight_and_turned():
    _check(*board_picture())
    _check(*board_picture(angle=18))


def test_finds_it_with_one_marker_cut_off():
    img, true = board_picture(shift=(0, 155), angle=4)    # bottom markers run off the picture
    _check(img, true)


def test_plain_chessboard_and_blank_are_not_found():
    img, _ = board_picture()
    plain = img.copy()                                    # same board, holes filled: no markers
    for r, c in ((0, 0), (0, SX - 1), (SY - 1, 0), (SY - 1, SX - 1)):
        pass
    plain = cv2.morphologyEx(np.where(img < 128, 0, 255).astype(np.uint8), cv2.MORPH_ERODE,
                             np.ones((int(0.5 * CELL),) * 2, np.uint8))   # erode white: small holes vanish
    assert find_marker_corners(np.where(plain > 0, img, 25).astype(np.uint8), SX, SY) == (None, None)
    blank = np.full((1000, 1600), 180, np.uint8)
    assert find_marker_corners(blank, SX, SY) == (None, None)


def test_detector_uses_it_only_for_boards_that_ask(tmp_path, monkeypatch):
    import src.detector as D
    img, _ = board_picture(angle=18)
    p = tmp_path / "b.png"; cv2.imwrite(str(p), cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    monkeypatch.setattr(D.cv2, "findChessboardCornersSB", lambda *a, **k: (False, None))   # OpenCV misses
    monkeypatch.setattr(D.cv2, "findChessboardCorners", lambda *a, **k: (False, None))
    plain = BoardConfig()
    assert D._detect_single(str(p), plain).corner_count == 0
    marked = BoardConfig(); marked.finder = "corner_markers"
    r = D._detect_single(str(p), marked)
    assert r.corner_count == 73 and r.charuco_ids.max() < 77


def test_library_12x8_board_uses_the_marker_finder():
    from src.boards import find_board, list_boards
    b = find_board("Chessboard 12x8", list_boards())
    assert b is not None and b.finder == "corner_markers"
