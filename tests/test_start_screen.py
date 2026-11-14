"""Start screen, Home and the van database choice (docs/capture Phase 0, 2026-11-13)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _db(found=True):
    from src.camera_db import CameraRow, DbResult
    if not found:
        return DbResult(error="Could not read the van database - ARAN99-SERVER: not found on the network.")
    return DbResult(cameras={"ROW": CameraRow("ROW", "101324", 2880, 1860),
                             "FORWARDLEFT": CameraRow("ForwardLeft", "2000713", 1920, 1080)},
                    server="ARAN99-SERVER", database="ARAN99")


def test_start_screen_database_found_ticked(app):
    from src.widgets.start_screen import StartScreen
    s = StartScreen()
    s.set_db(_db(True))
    assert not s.use_db.isHidden() and s.use_db.isChecked() and s.database_on
    assert "ARAN99 on ARAN99-SERVER" in s.db_label.text() and "ForwardLeft, ROW" in s.db_label.text()
    s.use_db.setChecked(False)
    assert not s.database_on
    s.set_db(_db(False))
    assert s.use_db.isHidden() and not s.database_on and "No van database" in s.db_label.text()


def test_start_screen_choices(app):
    from src.widgets.start_screen import StartScreen
    s = StartScreen()
    assert s.buttons["intrinsic"].isEnabled() and s.buttons["extrinsic"].isEnabled()
    assert s.buttons["capture"].isEnabled() and not s.buttons["capture_os"].isEnabled()
    got = []
    s.chosen.connect(got.append)
    s.buttons["extrinsic"].click(); s.boards_btn.click()
    assert got == ["extrinsic", "boards"]


def test_launcher_opens_chosen_tab_without_placeholder_tabs(app):
    from src.widgets.launcher import Launcher
    lch = Launcher()
    m = lch.open_main("extrinsic", use_db=False)
    assert m.tabs.currentWidget() is m.extrinsic
    assert [m.tabs.tabText(i) for i in range(m.tabs.count())] == ["Load Intrinsic", "Load Extrinsic", "Boards"]
    assert not m.home_btn.isHidden() and not m.bar.use_db
    assert "Van database: off" in m.bar.db_label.text()
    assert m.bar.van == ""            # another van's photos: the van comes from the photo folder
    assert lch.home() and lch.main is None
    m2 = lch.open_main("intrinsic", folder="C:/photos/ROW", use_db=False)
    assert m2 is not m and m2.tabs.currentWidget() is m2.single
    assert m2.single.setup_screen.folder_input.text() == "C:/photos/ROW"
    lch.home()


def test_home_leaves_nothing_behind(app, monkeypatch):
    """Lens, Old School folder and result on screen -> Home -> a fresh window with none of it."""
    import numpy as np
    from src.extrinsic.intrinsic_source import Intrinsic
    from src.widgets.launcher import Launcher
    lch = Launcher()
    m = lch.open_main("intrinsic", use_db=False)
    m.bar.role_combo.setEditText("ROW"); m.bar.serial_input.setText("101324")
    m.single.setup_screen.folder_input.setText("C:/photos/ROW")
    m.extrinsic.folder.setText("C:/Old School/ROW")
    m.extrinsic._set_lens(Intrinsic(np.eye(3), np.zeros(5), "101324", "a lens file", True, camera="ROW"))
    assert lch.home()
    m2 = lch.open_main("intrinsic", use_db=False)
    assert m2.bar.camera == "" and m2.bar.serial == ""
    assert m2.single.setup_screen.folder_input.text() == ""
    assert m2.extrinsic.folder.text() == "" and m2.extrinsic._intr is None and m2.extrinsic.lens.text() == ""
    assert m2.single.last_run is None and m2.extrinsic._res is None
    lch.home()


def test_home_refused_while_busy_and_asks_when_unsaved(app, monkeypatch):
    from src.widgets.launcher import Launcher
    lch = Launcher()
    m = lch.open_main("intrinsic", use_db=False)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(m, "busy", lambda: True)
    assert not lch.home() and lch.main is m
    monkeypatch.setattr(m, "busy", lambda: False)
    monkeypatch.setattr(m, "unsaved", lambda: "ROW has a lens result that is not saved.")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    assert not lch.home() and lch.main is m
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert lch.home() and lch.main is None


def test_database_off_means_typed_serial(app):
    from src.widgets.camera_bar import CameraBar
    b = CameraBar(use_db=False)
    b.van_edit.setText("ARAN99")
    assert b._db_worker is None and b.db_res is None and b.role_combo.isEditable()
    b.role_combo.setEditText("ROW")
    assert not b.serial_input.isReadOnly() and b.serial_edit.isHidden()


def test_collect_lens_photos_starts_capture_as_its_own_program(app, monkeypatch):
    """Phase 4: a separate process (QProcess.startDetached), never an import of src.capture."""
    import sys
    from src.widgets import launcher as L
    prog, args, cwd = L.capture_command("ARAN99", True)
    assert prog == sys.executable and args == ["-m", "src.capture", "--van", "ARAN99"]
    assert L.capture_command("", False)[1] == ["-m", "src.capture", "--no-db"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\\Program Files\\SurveyorCalibration\\SurveyorCalibration.exe")
    prog, args, _ = L.capture_command("ARAN69", False)
    assert prog.endswith("SurveyorCapture.exe") and args == ["--van", "ARAN69", "--no-db"]
    monkeypatch.undo()
    started = []
    monkeypatch.setattr(L.QProcess, "startDetached", staticmethod(lambda p, a, c: started.append((p, a)) or True))
    lch = L.Launcher()
    assert lch.start.buttons["capture"].isEnabled()
    lch.start.buttons["capture"].click()
    assert started and started[0][1][:2] == ["-m", "src.capture"] and lch.main is None


def test_collect_lens_photos_says_so_when_capture_is_missing(app, monkeypatch, tmp_path):
    """Phase 4 done-when: without src/capture the launch button reports it, nothing starts."""
    from src.widgets import launcher as L
    assert not L.capture_present("python", ["-m", "src.capture"], str(tmp_path))
    assert not L.capture_present(str(tmp_path / "SurveyorCapture.exe"), [], str(tmp_path))
    started, warned = [], []
    monkeypatch.setattr(L, "capture_present", lambda *a: False)
    monkeypatch.setattr(L.QProcess, "startDetached", staticmethod(lambda *a: started.append(a) or True))
    monkeypatch.setattr(L.QMessageBox, "warning", staticmethod(lambda *a: warned.append(a[2])))
    lch = L.Launcher()
    assert lch.start_capture() is False and not started and "not installed" in warned[0]
