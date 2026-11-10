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


def test_one_camera_at_a_time(win):
    """2026-11-03: no Whole van table; Load Intrinsic is the one-camera screen."""
    assert win.tabs.tabText(0) == "Load Intrinsic" and win.tabs.widget(0) is win.single
    assert not hasattr(win, "van_screen")


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


def test_van_database_picks_camera_and_locks_serial(win):
    """2026-11-10: database answered -> only its enabled cameras; serial filled and locked;
    Edit unlocks it; no database -> the usual list, serial typed."""
    from src.camera_db import CameraRow, DbResult
    s = win.single.setup_screen
    res = DbResult(cameras={"ROW": CameraRow("ROW", "101324", 2880, 1860),
                            "FORWARDLEFT": CameraRow("ForwardLeft", "2000713", 1920, 1080)},
                   server="ARAN69-SERVER", database="ARAN69")
    s.set_db_cameras(res)
    items = [s.role_combo.itemText(i) for i in range(s.role_combo.count())]
    assert items == ["ForwardLeft", "ROW"] and not s.role_combo.isEditable()
    s.role_combo.setCurrentText("ROW")
    s.apply_db(res, "ROW")
    assert s.serial_input.text() == "101324" and s.serial_input.isReadOnly() and s.serial_edit.isEnabled()
    assert s.serial_from == "van database"
    s.serial_edit.click()
    assert not s.serial_input.isReadOnly()
    s.serial_input.setText("999"); s.apply_db(res, "ROW")
    assert s.serial_input.text() == "999" and "van database says 101324" in s.serial_from
    s.role_combo.setCurrentText("ForwardLeft"); s.apply_db(res, "ForwardLeft")   # new camera: locked again
    assert s.serial_input.text() == "2000713" and s.serial_input.isReadOnly()
    s.set_db_cameras(None); s.apply_db(None, "")
    assert s.role_combo.isEditable() and "ROW" in [s.role_combo.itemText(i) for i in range(s.role_combo.count())]
    assert not s.serial_input.isReadOnly() and not s.serial_edit.isVisible()
    s.serial_input.clear(); s.role_combo.setCurrentIndex(-1); s.role_combo.setEditText("")


def test_extrinsic_camera_and_serial_from_the_lens(win):
    import numpy as np
    from src.extrinsic.intrinsic_source import Intrinsic
    e = win.extrinsic
    e._set_lens(Intrinsic(np.eye(3), np.zeros(5), "2000713", "test lens", True, camera="ForwardLeft"))
    assert e.serial.text() == "2000713" and e.serial.isReadOnly()
    e._set_lens(Intrinsic(np.eye(3), np.zeros(5), "", "old lens", False, camera=""))
    assert e.serial.text() == "" and not e.serial.isReadOnly()
