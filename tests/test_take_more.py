"""Derek 2026-11-14: NOT PASSED -> "Take 50 more" opens SurveyorCapture on the same camera and
folder (--add-to), as its own process.  PASS or a hard stop -> no button."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication


def test_capture_command_adds_camera_and_folder():
    from src.widgets.launcher import capture_command
    prog, args, cwd = capture_command("ARAN59", True, camera="ROW", add_to=r"E:\photos\ROW_1")
    assert args[-6:] == ["--van", "ARAN59", "--camera", "ROW", "--add-to", r"E:\photos\ROW_1"]
    _, args, _ = capture_command("", False)
    assert args[-1] == "--no-db" and "--add-to" not in args


@pytest.fixture(scope="module")
def win():
    QApplication.instance() or QApplication([])
    from src.widgets.app_window import AppWindow
    w = AppWindow(use_db=False)
    yield w
    w.close()


def _show(win, tmp_path, grade):
    from src.board import BoardConfig
    from src.calibrator import CalibrationResult
    cal = CalibrationResult(camera_matrix=np.array([[1000, 0, 960], [0, 1000, 540], [0, 0, 1.0]]),
                            dist_coeffs=np.zeros((1, 5)), rms=0.4, rvecs=[], tvecs=[],
                            image_count_used=30, image_size=(1920, 1080))
    cal.grade = grade
    one = win.single
    one._role, one._serial = "ROW", "103032"
    one._show(SimpleNamespace(cal=cal, board=BoardConfig(), folder=str(tmp_path), grade=grade))
    return one


@pytest.mark.parametrize("passed, stops, shown", [(False, [], True), (True, [], False), (False, ["bad"], False)])
def test_button_only_when_more_photos_can_fix_it(win, tmp_path, passed, stops, shown):
    from src.grading import GradeReport
    g = GradeReport(passed=passed, headline="", hard_stops=stops, reasons=[] if passed else ["x"],
                    missing=["the board in Top-left"])
    one = _show(win, tmp_path, g)
    r = one.report_screen
    assert (not r.more_button.isHidden()) == shown and r.more_button.text() == "Take 50 more"
    if shown:
        assert r.grade_banner.text() == "NOT PASSED — take another 50 photos. Missing: the board in Top-left."


def test_button_opens_capture_on_this_folder(win, tmp_path, monkeypatch):
    from src.grading import GradeReport
    one = _show(win, tmp_path, GradeReport(passed=False, headline="", reasons=["x"]))
    started = []
    from PySide6.QtCore import QProcess
    monkeypatch.setattr(QProcess, "startDetached", lambda prog, args, cwd: started.append(args) or True)
    one.report_screen.more_button.click()
    assert started and started[0][-5:] == ["--no-db", "--camera", "ROW", "--add-to", str(tmp_path)]
