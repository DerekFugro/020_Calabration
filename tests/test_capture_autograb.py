"""Take photos (Derek 2026-11-14): a batch of 50, one every 2 s, no board finding; only the
card's "no signal" picture is skipped.  Adding mode: the calibration app's "Take 50 more"
puts new photos straight into the folder it graded.  The window with a fake camera."""
import json
import time

import numpy as np
import pytest

from src.capture import autograb

PORT = "Video (00-1 Pro Capture Dual HDMI 4K+)"


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


def _window(app, tmp_path, **kw):
    from src.capture.source import FakeSource
    from src.capture.window import CaptureWindow
    fake = kw.pop("fake", {})
    w = CaptureWindow(use_db=False, folder=str(tmp_path), names=[PORT],
                      source_factory=lambda cam, index: FakeSource(camera="ROW", **fake), **kw)
    w.camera_combo.setCurrentIndex(0)
    w.name_combo.setCurrentText("ROW"); w.serial_edit.setText("88888888")
    w.size_combo.setCurrentText("1920 x 1080")
    return w


def test_defaults_are_50_photos_every_2_seconds_and_no_board_finder(app, tmp_path):
    assert (autograb.BATCH, autograb.EVERY_S) == (50, 2.0)
    assert not hasattr(autograb, "find_board") and not hasattr(autograb, "AutoGrabLogic")
    w = _window(app, tmp_path)
    assert w.target_spin.value() == 50 and w.every_spin.value() == 2.0
    assert w.auto_btn.text() == "Take 50 photos" and not hasattr(w, "auto_mode")
    w.target_spin.setValue(30); assert w.auto_btn.text() == "Take 30 photos"
    w.close()


def test_takes_the_batch_and_stops(app, tmp_path, monkeypatch):
    w = _window(app, tmp_path)
    assert wait(app, lambda: w.auto_btn.isEnabled())
    w.every_spin.setValue(1.0)
    monkeypatch.setattr(w.target_spin, "value", lambda: 4)
    t0 = time.time()
    w._toggle_auto()
    assert "4 PHOTOS, ONE EVERY 1 S" in w.auto_label.text() and w.auto_btn.text() == "Stop"
    assert not w.grab_btn.isEnabled()
    assert wait(app, lambda: w._auto is None, 15)
    assert len(list(tmp_path.glob("ROW_88888888_*/ROW_*.jpg"))) == 4 and time.time() - t0 >= 2.8   # ~1 s apart
    assert "Done: 4 photos" in w.status.text() and w.auto_btn.text() == "Take 4 photos"
    w.close()


def test_stop_button_and_camera_change_stop_it(app, tmp_path):
    w = _window(app, tmp_path)
    assert wait(app, lambda: w.auto_btn.isEnabled())
    w.every_spin.setValue(30.0)
    w._toggle_auto()
    assert wait(app, lambda: w._count == 1, 5)                   # the first photo at once
    w._toggle_auto()                                              # Stop
    assert w._auto is None and w.auto_label.isHidden() and w.status.text() == "Stopped."
    w._toggle_auto()
    w._camera_chosen()                                            # camera change stops it
    assert w._auto is None
    w.close()


def test_no_signal_is_skipped(app, tmp_path):
    w = _window(app, tmp_path, fake={"no_signal": True})
    assert wait(app, lambda: w._delivered is not None)
    a = autograb.AutoGrabThread(w._worker, 3, every_s=0.5)
    seen = []
    a.state.connect(lambda what, n, t: seen.append(what)); a.want_save.connect(lambda f, s: seen.append("asked"))
    a.start()
    assert wait(app, lambda: seen.count("no picture") >= 2, 5)
    a.stop()
    assert "asked" not in seen and not list(tmp_path.rglob("*.jpg"))
    w.close()


def test_never_saves_the_same_frame_twice():
    frame = np.zeros((10, 10, 3), np.uint8)
    worker = type("W", (), {"latest": lambda self: frame})()
    a = autograb.AutoGrabThread(worker, 3)
    assert a._new_frame() is frame and a._new_frame() is None


def test_adding_mode_saves_straight_into_the_graded_folder(app, tmp_path, monkeypatch):
    graded = tmp_path / "ROW_88888888_20261114_120000"; graded.mkdir()
    (graded / "ROW_old.jpg").write_bytes(b"x")
    base = tmp_path / "base"; base.mkdir()
    from src.capture.window import QSettings          # the test copy (tests/conftest.py), never the registry
    QSettings("SidewalkProfiler", "SurveyorCapture").setValue("folder", str(base))
    w = _window(app, tmp_path, camera="ROW", add_to=str(graded))
    assert w.folder_title.text() == "Adding to:" and w.folder_edit.text() == str(graded)
    assert w.folder_edit.isReadOnly() and not w.browse_btn.isEnabled()
    assert wait(app, lambda: w.grab_btn.isEnabled())
    w.every_spin.setValue(1.0)
    monkeypatch.setattr(w.target_spin, "value", lambda: 2)
    w._toggle_auto()
    assert wait(app, lambda: w._auto is None, 15)
    new = [p for p in graded.glob("ROW_*.jpg") if p.name != "ROW_old.jpg"]
    assert len(new) == 2 and not [d for d in graded.iterdir() if d.is_dir()]     # no new subfolder
    log = json.loads(next(graded.glob("CAPTURE_*.json")).read_text(encoding="utf-8"))
    assert log["added_to_folder"] is True and len(log["photos"]) == 2
    assert QSettings("SidewalkProfiler", "SurveyorCapture").value("folder") == str(base)   # base folder kept
    w.close()


def test_adding_mode_refuses_another_camera(app, tmp_path):
    graded = tmp_path / "RearLeft_1_20261114_120000"; graded.mkdir()
    w = _window(app, tmp_path, camera="RearLeft", add_to=str(graded))      # but the input is named ROW
    assert wait(app, lambda: w.grab_btn.isEnabled())
    w._grab(False)
    assert "These photos are for RearLeft" in w.status.text()
    assert not list(graded.glob("*.jpg"))
    w.close()
