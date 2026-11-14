"""Auto grab (Derek 2026-11-14): save when the board is found, held still, in a new spot;
stop at the target.  Logic with made-up board points; the window with a fake camera."""
import time

import numpy as np
import pytest

from src.capture import autograb
from src.capture.autograb import AutoGrabLogic

W = 1920


def board_at(x, y, size=400, tilt=0.0, n=(11, 7)):
    gx, gy = np.meshgrid(np.linspace(0, size, n[0]), np.linspace(0, size * 0.6 * (1 - tilt), n[1]))
    return np.c_[gx.ravel() + x, gy.ravel() + y]


def test_saves_only_after_holding_still():
    lg = AutoGrabLogic(target=5)
    p = board_at(100, 100)
    assert lg.look(p, W)[0] == "moving"           # first look: not known to be still yet
    assert lg.look(p, W)[0] == "hold still"       # still once
    what, sig = lg.look(p, W)
    assert what == "save"                         # still twice in a row
    lg.saved_one(sig)


def test_moving_board_is_never_saved():
    lg = AutoGrabLogic()
    for k in range(10):
        assert lg.look(board_at(100 + 40 * k, 100), W)[0] == "moving"


def test_same_spot_is_not_saved_twice_but_a_new_spot_or_tilt_is():
    lg = AutoGrabLogic()
    for _ in range(3):
        what, sig = lg.look(board_at(100, 100), W)
    assert what == "save"; lg.saved_one(sig)
    for _ in range(3):
        what, _ = lg.look(board_at(102, 101), W)  # a hair away: same spot
    assert what == "same spot"
    for _ in range(3):
        what, sig = lg.look(board_at(100, 100, tilt=0.35), W)   # same place, tilted
    assert what == "save"; lg.saved_one(sig)
    for _ in range(3):
        what, sig = lg.look(board_at(1300, 600), W)              # another corner
    assert what == "save"


def test_board_lost_starts_over_and_target_stops():
    lg = AutoGrabLogic(target=1)
    lg.look(board_at(100, 100), W); lg.look(board_at(100, 100), W)
    assert lg.look(None, W)[0] == "no board"
    assert lg.look(board_at(100, 100), W)[0] == "moving"          # the still count restarted
    lg.look(board_at(100, 100), W)
    what, sig = lg.look(board_at(100, 100), W)
    lg.saved_one(sig)
    assert lg.look(board_at(900, 500), W)[0] == "done"


def test_finds_a_real_chessboard_like_the_calibration_app():
    import cv2
    from src.board import BoardConfig
    b = BoardConfig()                                              # Chessboard 12 x 8
    sq = 60
    img = np.full((8 * sq + 200, 12 * sq + 200), 255, np.uint8)
    for r in range(8):
        for c in range(12):
            if (r + c) % 2 == 0:
                img[100 + r * sq:100 + (r + 1) * sq, 100 + c * sq:100 + (c + 1) * sq] = 0
    pts = autograb.find_board(img, b)
    assert pts is not None and pts.shape == (77, 2)
    assert autograb.find_board(np.full((400, 600), 180, np.uint8), b) is None


# ── the window, end to end, with a fake camera and a scripted board ─────────────────────

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait(app, cond, s=10.0):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_window_auto_grab_saves_three_spots_and_stops(app, tmp_path, monkeypatch):
    from src.capture.source import FakeSource
    from src.capture.window import CaptureWindow
    spots = [board_at(100, 100), board_at(1200, 100), board_at(600, 600)]
    looks = {"n": 0}

    def scripted(gray, board):
        looks["n"] += 1
        return spots[min((looks["n"] - 1) // 4, len(spots) - 1)]     # 4 looks per spot
    monkeypatch.setattr(autograb, "find_board", scripted)
    monkeypatch.setattr(autograb, "library_boards", lambda: [type("B", (), {"name": "Chessboard 12x8"})()])
    monkeypatch.setattr(autograb, "LOOK_EVERY_S", 0.01)
    w = CaptureWindow(use_db=False, folder=str(tmp_path), names=["Video (00-1 Pro Capture Dual HDMI 4K+)"],
                      source_factory=lambda cam, index: FakeSource(camera="ROW"))
    w.camera_combo.setCurrentIndex(0)
    w.name_combo.setCurrentText("ROW"); w.serial_edit.setText("88888888")
    w.size_combo.setCurrentText("1920 x 1080")
    assert wait(app, lambda: w.auto_btn.isEnabled())
    w.target_spin.setValue(5); w.target_spin.setValue(3)          # spin minimum is 5; set directly below
    monkeypatch.setattr(w.target_spin, "value", lambda: 3)
    w._toggle_auto()
    assert w.auto_btn.text() == "Stop auto" and not w.grab_btn.isEnabled()
    assert wait(app, lambda: w._auto is None, 15)                 # stopped by itself at the target
    photos = list(tmp_path.glob("ROW_88888888_*/ROW_*.jpg"))
    assert len(photos) == 3 and w.count_label.text() == "3 photos"
    assert "done" in w.status.text().lower() and w.auto_btn.text() == "Auto grab"
    w.close()


def test_window_stop_button_and_camera_change_stop_auto(app, tmp_path, monkeypatch):
    from src.capture.source import FakeSource
    from src.capture.window import CaptureWindow
    monkeypatch.setattr(autograb, "find_board", lambda g, b: None)            # never finds a board
    monkeypatch.setattr(autograb, "library_boards", lambda: [])
    monkeypatch.setattr(autograb, "LOOK_EVERY_S", 0.01)
    w = CaptureWindow(use_db=False, folder=str(tmp_path), names=["Video (00-1 Pro Capture Dual HDMI 4K+)"],
                      source_factory=lambda cam, index: FakeSource(camera="ROW"))
    w.camera_combo.setCurrentIndex(0)
    w.name_combo.setCurrentText("ROW"); w.serial_edit.setText("88888888")
    w.size_combo.setCurrentText("1920 x 1080")
    assert wait(app, lambda: w.auto_btn.isEnabled())
    w._toggle_auto()
    assert wait(app, lambda: "BOARD NOT FOUND" in w.auto_label.text() or "LOOKING" in w.auto_label.text(), 5)
    w._toggle_auto()                                                          # Stop auto
    assert w._auto is None and w.auto_btn.text() == "Auto grab" and w.auto_label.isHidden()
    w._toggle_auto()
    w._camera_chosen()                                                        # camera change stops it
    assert w._auto is None
    assert not list(tmp_path.rglob("*.jpg"))
    w.close()
