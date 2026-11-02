"""GUI smoke test: the window builds, One camera is the default, one rating only."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def win():
    app = QApplication.instance() or QApplication([])
    from src.widgets.app_window import AppWindow
    w = AppWindow()
    yield w
    w.close()


def test_one_camera_is_default(win):
    assert win.load_intrinsic.tabText(0) == "One camera"
    assert win.load_intrinsic.currentWidget() is win.single


def test_setup_starts_blank(win):
    s = win.single.setup_screen
    assert s.camera_role == "" and s.serial_input.text() == ""
    assert not s.run_button.isEnabled()


def test_no_old_rating_anywhere(win):
    words = {"Excellent", "Acceptable", "Needs Improvement", "NOT GOOD ENOUGH"}
    texts = [lbl.text() for lbl in win.findChildren(QLabel)]
    assert not any(w in t for t in texts for w in words)


def test_report_shows_grade_banner(win, tmp_path):
    from types import SimpleNamespace
    import numpy as np
    from src.board import BoardConfig
    from src.calibrator import CalibrationResult
    cal = CalibrationResult(camera_matrix=np.array([[1000, 0, 960], [0, 1000, 540], [0, 0, 1.0]]),
                            dist_coeffs=np.zeros((1, 5)), rms=0.4, rvecs=[], tvecs=[],
                            image_count_used=30, image_size=(1920, 1080))
    cal.grade = SimpleNamespace(passed=False, headline="NOT PASSED: retake the photos, see the reasons.",
                                repeatability=None, hard_stops=[], reasons=["x"], warnings=[],
                                blur_median_px=float("nan"), coaching=[], worst_images=[])
    rs = win.single.report_screen
    rs.set_data(cal, BoardConfig(), str(tmp_path))
    assert rs.grade_banner.text().startswith("NOT PASSED")
