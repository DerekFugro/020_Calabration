"""SurveyorCapture window, offscreen with FakeSource (docs/capture Phase 3): no capture card."""
import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from src.capture.source import FakeSource

PORTS = ["Video (00-1 Pro Capture Dual HDMI 4K+)", "Video (00-0 Pro Capture Dual HDMI 4K+)"]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait(app, cond, s=5.0):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def _window(app, tmp_path, **fake):
    from src.capture.window import CaptureWindow
    w = CaptureWindow(use_db=False, folder=str(tmp_path), names=PORTS,
                      source_factory=lambda cam, index: FakeSource(camera="ROW", **fake))
    w.camera_combo.setCurrentIndex(0)
    w.name_combo.setCurrentText("ROW"); w.serial_edit.setText("0103043")
    w.size_combo.setCurrentText("1920 x 1080")
    return w


def test_grab_three_photos_and_the_log(app, tmp_path):
    w = _window(app, tmp_path)
    assert not w.user_row.isHidden() and "inputs Windows reports" in w.list_label.text()
    assert wait(app, lambda: w.grab_btn.isEnabled())
    for _ in range(3):
        w._grab(False)
        assert wait(app, lambda: w.grab_btn.isEnabled() and not w._busy_saving)
    photos = sorted(tmp_path.glob("ROW_*.jpg"))
    assert len(photos) == 3 and w.count_label.text() == "3 photos"
    import cv2
    assert cv2.imread(str(photos[0])).shape == (1080, 1920, 3)
    log = json.loads(next(tmp_path.glob("CAPTURE_*.json")).read_text(encoding="utf-8"))
    assert log["camera"] == "ROW" and log["serial"] == "0103043" and log["camera_source"] == "user"
    assert log["van_database_used"] is False and len(log["photos"]) == 3 and log["port"] == PORTS[0]
    assert "delivered 1920 x 1080" in w.info.text()
    w.close()


def test_countdown_grabs_once(app, tmp_path):
    w = _window(app, tmp_path)
    w._countdown_s = 1
    assert wait(app, lambda: w.grab_btn.isEnabled())
    w._start_countdown()
    assert wait(app, lambda: len(list(tmp_path.glob("ROW_*.jpg"))) == 1, 4)
    log = json.loads(next(tmp_path.glob("CAPTURE_*.json")).read_text(encoding="utf-8"))
    assert log["photos"][0]["countdown"] is True
    w.close()


def test_no_signal_is_never_saved(app, tmp_path):
    w = _window(app, tmp_path, no_signal=True)
    assert wait(app, lambda: "no signal" in w.status.text())
    assert not w.grab_btn.isEnabled()
    w._worker.request_grab(str(tmp_path), 95)                 # even if asked directly
    assert wait(app, lambda: "Nothing was saved" in w.status.text())
    assert not list(tmp_path.glob("ROW_*.jpg"))
    w.close()


def test_busy_camera_message_and_try_again(app, tmp_path):
    w = _window(app, tmp_path, busy=True)
    assert wait(app, lambda: "is busy or has no signal" in w.status.text())
    assert w.try_btn.isEnabled() and not w.grab_btn.isEnabled()
    w.close()


def test_wrong_size_is_a_warning_not_a_stop(app, tmp_path):
    w = _window(app, tmp_path, deliver=(640, 480))
    assert wait(app, lambda: "should give 1920 x 1080 photos but gives 640 x 480" in w.status.text())
    assert w.grab_btn.isEnabled()
    w.close()


def test_unnamed_input_cant_grab(app, tmp_path):
    from src.capture.window import CaptureWindow
    w = CaptureWindow(use_db=False, folder=str(tmp_path), names=PORTS,
                      source_factory=lambda cam, index: FakeSource())
    w.camera_combo.setCurrentIndex(1); w.size_combo.setCurrentText("3840 x 2160")
    wait(app, lambda: w._delivered is not None)
    assert not w.grab_btn.isEnabled()
    w.name_combo.setCurrentText("ForwardRight")
    assert wait(app, lambda: w.grab_btn.isEnabled())
    w.close()


def test_closing_releases_the_camera_for_good(app, tmp_path):
    """2026-11-14: closing moved focus off the van box, which reloaded the list and reopened the
    camera in the hidden window - ARAN would then find the input busy."""
    w = _window(app, tmp_path)
    assert wait(app, lambda: w._worker is not None and w._delivered is not None)
    w.van_edit.setFocus()
    w.close()
    w.van_edit.editingFinished.emit()           # what focus leaving the box does
    wait(app, lambda: False, 0.5)
    assert w._worker is None


def test_settings_never_reach_the_registry():
    """Guard: the fixture is live, so a save in a test lands in the temp .ini file."""
    from src.capture import window
    s = window.QSettings(window.ORG, window.APP)
    assert s.format() == __import__('PySide6.QtCore', fromlist=['QSettings']).QSettings.Format.IniFormat and "qsettings" in s.fileName()
