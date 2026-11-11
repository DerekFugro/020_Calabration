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


def test_extrinsic_buttons_in_top_bar_only_on_that_tab(win):
    """2026-11-11: View photos, Solve, Save all formats, Open report sit in the top bar row."""
    a = win.extrinsic.actions
    assert a.parent() is win.bar
    win.tabs.setCurrentWidget(win.extrinsic)
    assert not a.isHidden()
    win.tabs.setCurrentWidget(win.single)
    assert a.isHidden()
    assert not win.extrinsic.report_btn.isEnabled()          # nothing saved yet


def test_extrinsic_opens_saved_results(win, tmp_path):
    """A saved Extrinsic_<date> result shows from its files; Open report opens its PDF."""
    import cv2
    import numpy as np
    e = win.extrinsic
    d = tmp_path / "Extrinsic_20260401_100000"
    (d / "20260404.102502").mkdir(parents=True)
    cv2.imwrite(str(d / "20260404.102502" / "1_targets.png"), np.zeros((40, 60, 3), np.uint8))
    (d / "ARAN99_ROW_88888888_extrinsic.pdf").write_bytes(b"%PDF")
    data = {"camera": "ROW", "serial": "88888888",
            "grade": {"passed": True, "headline": "PASS: good", "reasons": [], "warnings": []},
            "pointing_deg": {"pan_right": 0.5, "tilt_up": -10.0, "roll_cw": 0.1},
            "lever_arm_m": {"forward": 1.2, "right": 0.0, "up_above_pavement": 2.5},
            "setups": [{"name": "20260404.102502", "passed": True, "targets": 22, "photo": "",
                        "pointing_deg": [0.5, -10.0, 0.1], "lever_forward_right_m": [1.2, 0.0],
                        "up_above_pavement_m": 2.5, "problems": []}]}
    pdf = d / "ARAN99_ROW_88888888_extrinsic.pdf"
    e._show_saved(d, data, pdf)
    assert "PASS" in e.result.text() and e.setups.count() == 1 and e.report_btn.isEnabled()
    e.setups.setCurrentRow(0)
    assert "22 targets" in e.details.toPlainText()
    e.new_camera()
    assert not e.report_btn.isEnabled() and e._loaded is None


def test_version_in_window_title(win):
    """2026-11-11: the version shows beside the app name in the window frame."""
    from src.version import app_version
    assert win.windowTitle() == f"SurveyorCalibration   {app_version()}"


def test_intrinsic_buttons_in_top_bar_like_extrinsic(win):
    """2026-11-11: Load Intrinsic's buttons sit in the top bar row too, shown only on that tab;
    New Calibration / View photos / Save only with a report on screen."""
    one = win.single
    r, s = one.report_screen, one.setup_screen
    assert one.actions.parent() is win.bar and s.run_button.parent() is one.actions
    win.tabs.setCurrentWidget(win.single)
    assert not one.actions.isHidden() and win.extrinsic.actions.isHidden()
    one.stack.setCurrentWidget(s)
    assert r.save_button.isHidden() and r.new_cal_button.isHidden() and not s.run_button.isHidden()
    assert r.save_button.text() == "Save all formats" and not one.report_btn.isEnabled()
    one.stack.setCurrentWidget(r)
    assert not r.save_button.isHidden() and not r.new_cal_button.isHidden() and not r.view_button.isHidden()
    assert s.run_button.isHidden()                       # the top bar must not squeeze the van and serial boxes
    one.stack.setCurrentWidget(s)
    win.tabs.setCurrentWidget(win.extrinsic)
    assert one.actions.isHidden() and not win.extrinsic.actions.isHidden()
