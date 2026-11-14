"""test_boards_and_dots.py — Board library, dot-board detection, auto-detect, CLI.

Synthetic dot-board images are rendered from the real Cal_board layout CSVs
through a known pinhole camera, so the true dot ids and positions are known.
"""

from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from src.auto_detect import auto_detect_board
from src.board import BoardConfig, KIND_CHESSBOARD, KIND_DOTS
from src.boards import find_board, list_boards, load_board_folder
from src.calibrator import calibrate
from src.detector import detect_images
from src.dot_detector import detect_blobs, match_dots
from src.image_filter import filter_detections
from tests.test_integration import _generate_board_images

W, H = 1440, 930
K_TRUE = np.array([[1100.0, 0, 720.0], [0, 1100.0, 465.0], [0, 0, 1]])
PX_PER_MM = 2.0                     # board raster resolution


@pytest.fixture(scope="module")
def boards():
    return list_boards()


def _render_board(board: BoardConfig) -> tuple[np.ndarray, np.ndarray]:
    """White raster of the dot board; returns (image, mm->raster 3x3)."""
    xy, r = board.dot_xy_mm, board.dot_radius_mm
    lo = (xy - r[:, None]).min(0) - 40
    hi = (xy + r[:, None]).max(0) + 40
    size = ((hi - lo) * PX_PER_MM).astype(int)
    img = np.full((size[1], size[0]), 255, np.uint8)
    for (x, y), rr in zip(xy, r):
        c = ((np.array([x, y]) - lo) * PX_PER_MM * 16).astype(int)
        cv2.circle(img, tuple(int(v) for v in c), int(rr * PX_PER_MM * 16), 0, -1,
                   cv2.LINE_AA, shift=4)
    S = np.array([[PX_PER_MM, 0, -lo[0] * PX_PER_MM],
                  [0, PX_PER_MM, -lo[1] * PX_PER_MM], [0, 0, 1]])
    return img, S


def _views(n: int):
    """n board poses: tilts up to ~35 deg, 1.3-1.8 m away."""
    rng = np.random.default_rng(7)
    for i in range(n):
        rv = np.array([rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), rng.uniform(-0.2, 0.2)])
        tv = np.array([rng.uniform(-80, 80), rng.uniform(-60, 60), rng.uniform(1300, 1800)])
        yield rv, tv


def _write_dot_images(board: BoardConfig, folder: pathlib.Path, n: int) -> list:
    """Render n views; returns [(path, rvec, tvec)]."""
    raster, S = _render_board(board)
    out = []
    for i, (rv, tv) in enumerate(_views(n)):
        R, _ = cv2.Rodrigues(rv)
        Hmm = K_TRUE @ np.c_[R[:, :2], tv]             # board mm -> image
        Hr = Hmm @ np.linalg.inv(S)                     # raster -> image
        img = cv2.warpPerspective(raster, Hr, (W, H), flags=cv2.INTER_AREA,
                                  borderValue=200)
        p = folder / f"{board.name}_{i:02d}.png"
        cv2.imwrite(str(p), img)
        out.append((str(p), rv, tv))
    return out


@pytest.fixture(scope="module")
def dot_sets(tmp_path_factory, boards):
    sets = {}
    for b in boards:
        if b.is_dots:
            d = tmp_path_factory.mktemp(b.name.replace(" ", "_"))
            sets[b.name] = (b, _write_dot_images(b, d, 12))
    return sets


# ── Library ───────────────────────────────────────────────────────────────────

def test_library_lists_all_three_boards(boards):
    names = {b.name: b for b in boards}
    assert {"Chessboard 12x8", "Randot-003", "ikea_road"} <= set(names)
    assert names["Randot-003"].kind == KIND_DOTS and names["Randot-003"].num_corners == 40
    assert names["ikea_road"].kind == KIND_DOTS and names["ikea_road"].num_corners == 62
    assert names["Chessboard 12x8"].kind == KIND_CHESSBOARD
    assert boards[0].kind == KIND_CHESSBOARD          # chessboards listed first


def test_default_boardconfig_unchanged():
    b = BoardConfig()
    assert b.kind == KIND_CHESSBOARD and b.num_corners == 77 and not b.is_dots


def test_find_board_by_name_or_folder(boards):
    assert find_board("randot-003", boards).name == "Randot-003"
    assert find_board("Randot-003_roadware_140_60_003", boards).name == "Randot-003"
    assert find_board("nope", boards) is None


def test_dot_object_points_in_mm(boards):
    b = find_board("Randot-003", boards)
    pts = b.get_all_object_points()
    assert pts.shape == (40, 3) and np.all(pts[:, 2] == 0)
    assert np.allclose(pts[0, :2], 0)                  # dot 0 is the centre dot
    assert np.allclose(pts[1, :2], [-79.4486, -46.7570], atol=1e-3)   # Y = -z


def test_bad_board_folder_is_skipped(tmp_path):
    (tmp_path / "Bad").mkdir()
    (tmp_path / "Bad" / "board.yaml").write_text("type: dots\nlayout_csv: missing.csv\n")
    errors: list[str] = []
    boards = list_boards(tmp_path, errors=errors)
    assert len(errors) == 1 and "missing.csv" in errors[0]
    assert [b.kind for b in boards] == [KIND_CHESSBOARD]   # built-in fallback
    with pytest.raises(ValueError):
        load_board_folder(tmp_path / "Bad")


# ── Dot detection ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["Randot-003", "ikea_road"])
def test_match_dots_finds_true_ids(dot_sets, boards, name):
    board, imgs = dot_sets[name]
    other = next(b for b in boards if b.is_dots and b.name != name)
    for path, rv, tv in imgs[:4]:
        g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        blobs = detect_blobs(g)
        m = match_dots(blobs, board.dot_xy_mm, image_size=(W, H))
        assert m is not None and len(m.ids) >= 0.9 * board.num_corners
        truth, _ = cv2.projectPoints(board.get_all_object_points()[m.ids], rv, tv, K_TRUE, None)
        err = np.linalg.norm(truth.reshape(-1, 2) - m.image_points, axis=1)
        # Right dot: a wrong dot would be tens of px away.  Up to ~2 px is the
        # ellipse-centre perspective bias of the big dots at 35 deg tilt.
        assert err.max() < 3.0
        assert np.median(err) < 0.6
        assert match_dots(blobs, other.dot_xy_mm, image_size=(W, H)) is None


@pytest.mark.parametrize("name", ["Randot-003", "ikea_road"])
def test_dot_calibration_recovers_camera(dot_sets, name):
    board, imgs = dot_sets[name]
    dets = detect_images([p for p, _, _ in imgs], board, verbose=False)
    filts = filter_detections(dets, min_corners=12, min_blur=0)
    cal = calibrate(dets, filts, board)
    K = cal.camera_matrix
    assert cal.image_count_used == len(imgs)
    assert abs(K[0, 0] - 1100) < 11 and abs(K[1, 1] - 1100) < 11      # within 1%
    assert abs(K[0, 2] - 720) < 10 and abs(K[1, 2] - 465) < 10
    assert cal.rms < 1.0
    assert cal.point_count_used >= 0.9 * board.num_corners * len(imgs)


# ── Auto-detect ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["Randot-003", "ikea_road"])
def test_auto_detect_dot_boards(dot_sets, boards, name):
    _, imgs = dot_sets[name]
    res = auto_detect_board([p for p, _, _ in imgs], boards, n_samples=4)
    assert res.board is not None and res.board.name == name
    assert name in res.summary()


def test_auto_detect_chessboard(tmp_path, boards):
    paths = _generate_board_images(tmp_path, BoardConfig(), n_images=6)
    res = auto_detect_board(paths, boards, n_samples=4)
    assert res.board is not None and res.board.kind == KIND_CHESSBOARD


def test_auto_detect_chessboard_when_the_fast_check_misses(tmp_path, boards, monkeypatch):
    """2026-11-14: the fast classic check missed every GOX sample the detector reads fine;
    auto-detect then tries the detector's own full-size SB finder."""
    import src.auto_detect as ad
    paths = _generate_board_images(tmp_path, BoardConfig(), n_images=4)
    monkeypatch.setattr(ad.cv2, "findChessboardCorners", lambda *a, **k: (False, None))
    res = auto_detect_board(paths, boards, n_samples=4)
    assert res.board is not None and res.board.kind == KIND_CHESSBOARD


def test_auto_detect_gives_up_on_blank_images(tmp_path, boards):
    paths = []
    for i in range(3):
        p = tmp_path / f"blank_{i}.png"
        cv2.imwrite(str(p), np.full((H, W), 180, np.uint8))
        paths.append(str(p))
    res = auto_detect_board(paths, boards)
    assert res.board is None and "could not identify" in res.summary()


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_cli_list_boards(capsys):
    import cli
    assert cli.main(["--list-boards"]) == 0
    out = capsys.readouterr().out
    assert "Randot-003" in out and "ikea_road" in out and "Chessboard 12x8" in out


def test_cli_auto_on_dot_images(dot_sets, capsys):
    import cli
    _, imgs = dot_sets["Randot-003"]
    folder = str(pathlib.Path(imgs[0][0]).parent)
    assert cli.main([folder]) == 0
    out = capsys.readouterr().out
    assert "Auto-detected board: Randot-003" in out and "RMS" in out
