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
    assert win.bar.camera_role == "" and win.bar.serial == ""
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


def test_no_database_button(win):
    """2026-11-10: the Database... box is gone; login is always Windows sign-in."""
    from PySide6.QtWidgets import QPushButton
    assert not any("Database" in b.text() for b in win.findChildren(QPushButton))


def test_top_bar_picks_camera_and_locks_serial(win):
    """2026-11-10: camera and serial in the bar on top, shared by both tabs.  Database answered
    -> only its enabled cameras; serial filled and locked; Edit unlocks it; no database -> the
    usual list, serial typed."""
    from src.camera_db import CameraRow, DbResult
    b = win.bar
    res = DbResult(cameras={"ROW": CameraRow("ROW", "101324", 2880, 1860),
                            "FORWARDLEFT": CameraRow("ForwardLeft", "2000713", 1920, 1080)},
                   server="ARAN69-SERVER", database="ARAN69")
    b.db_res = res
    b.set_db_cameras(res)
    items = [b.role_combo.itemText(i) for i in range(b.role_combo.count())]
    assert items == ["ForwardLeft", "ROW"] and not b.role_combo.isEditable()
    b.role_combo.setCurrentText("ROW")
    assert b.serial == "101324" and b.serial_input.isReadOnly() and b.serial_edit.isEnabled()
    assert b.serial_from == "van database" and win.single.setup_screen.serial_from == "van database"
    b.serial_edit.click()
    assert not b.serial_input.isReadOnly()
    b.serial_input.setText("999"); b.apply_db(res, "ROW")
    assert b.serial == "999" and "van database says 101324" in b.serial_from
    b.role_combo.setCurrentText("ForwardLeft")                                   # new camera: locked again
    assert b.serial == "2000713" and b.serial_input.isReadOnly()
    b.db_res = None; b.set_db_cameras(None); b.apply_db(None, "")
    assert b.role_combo.isEditable() and "ROW" in [b.role_combo.itemText(i) for i in range(b.role_combo.count())]
    assert not b.serial_input.isReadOnly() and not b.serial_edit.isVisible()
    b.serial_input.clear(); b.role_combo.setCurrentIndex(-1); b.role_combo.setEditText("")


def test_changing_camera_clears_both_tabs(win):
    import numpy as np
    from src.extrinsic.intrinsic_source import Intrinsic
    b, e, s = win.bar, win.extrinsic, win.single.setup_screen
    b.role_combo.setEditText("ROW"); b.serial_input.setText("101324")
    s.folder_input.setText("C:/photos/ROW")
    e.folder.setText("C:/Old School/ROW")
    e._set_lens(Intrinsic(np.eye(3), np.zeros(5), "101324", "a lens file", True, camera="ROW"))
    assert "ROW, serial 101324" in e.camera_lbl.text()
    b.role_combo.setEditText("FORWARDLEFT")
    assert s.folder_input.text() == "" and e.folder.text() == "" and e._intr is None and e.lens.text() == ""
    b.serial_input.clear(); b.role_combo.setEditText("")
