"""Magewell camera signal, the ACS-size check, and reading once a second (2026-11-14).
No capture card needed: the signal bytes are the ones ROW gave on ARAN59."""
import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from src.capture import magewell, sizes
from src.capture.magewell import CameraSignal

# MWGetVideoSignalStatus bytes from ARAN59 ROW (01-0): locked, 1920x1080, interlaced, 29.97 fps
ROW_RAW = bytes.fromhex(
    "03000000 00000000 00000000 80070000 38040000 98080000 65040000 01 63170500 10000000 09000000 00 "
    "00000000 03000000 02000000 02000000".replace(" ", ""))
SIG_1K = CameraSignal("locked", 1920, 1080, 29.97, True)


def test_input_name_to_board_and_channel():
    assert magewell.board_channel("Video (01-0 Pro Capture Dual SDI 4K+)") == (1, 0)
    assert magewell.board_channel("Video (00-1 Pro Capture Dual HDMI 4K+)") == (0, 1)
    assert magewell.board_channel("OBS Virtual Camera") is None
    assert magewell.camera_signal("OBS Virtual Camera") is None


def test_decode_the_real_row_signal():
    s = magewell.decode_status(ROW_RAW)
    assert (s.state, s.width, s.height, s.interlaced) == ("locked", 1920, 1080, True)
    assert s.fps == 29.97 and s.text() == "1920 x 1080i at 29.97 frames/s"
    assert magewell.decode_status(bytes(64)).state == "no signal" and not magewell.decode_status(bytes(64)).locked


def test_no_dll_means_not_known(monkeypatch):
    monkeypatch.setattr(magewell, "DLL", r"C:\nowhere\LibMWCapture.dll")
    assert magewell.camera_signal("Video (01-0 Pro Capture Dual SDI 4K+)") is None


def test_scaling_kinds():
    assert sizes.scaling((1920, 1080), SIG_1K) is None
    assert sizes.scaling((3840, 2160), SIG_1K) == "upscaling"
    assert sizes.scaling((1920, 1080), CameraSignal("locked", 3840, 2160, 59.94)) == "downscaling"
    assert sizes.scaling((3840, 2160), None) is None
    assert sizes.scaling((3840, 2160), CameraSignal("no signal")) is None
    q = sizes.scaling_question((3840, 2160), SIG_1K, "ROW")
    assert "1920 x 1080i" in q and "3840 x 2160" in q and "upscaling" in q and "ACS" in q


def test_grabber_reads_once_per_interval_but_a_grab_reads_at_once(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from src.capture.grabber import GrabWorker
    from src.capture.source import FakeSource
    src = FakeSource(read_every_s=0.5)
    w = GrabWorker(src, 640, 480, "ROW")
    saved = []
    w.saved.connect(lambda *a: saved.append(a))
    w.start()
    time.sleep(1.6)
    reads = src.reads
    assert 3 <= reads <= 5                                   # ~ every 0.5 s (not hundreds)
    t0 = time.monotonic()
    w.request_grab(str(tmp_path), 90)
    while not list(tmp_path.glob("*.jpg")) and time.monotonic() - t0 < 2:
        time.sleep(0.01)
    assert list(tmp_path.glob("*.jpg")) and time.monotonic() - t0 < 0.3   # did not wait for the next second
    w.stop()


def test_auto_grab_never_looks_at_the_same_frame_twice():
    from src.capture.autograb import AutoGrabThread
    frame = np.zeros((10, 10, 3), np.uint8)
    worker = type("W", (), {"latest": lambda self: frame})()
    a = AutoGrabThread(worker, 3)
    assert a._new_frame() is frame and a._new_frame() is None


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(app, cond, s=5.0):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.parametrize("knew", [True, False])
def test_window_warns_asks_once_and_logs_upscaling(app, tmp_path, monkeypatch, knew):
    from src.capture.source import FakeSource
    from src.capture.window import CaptureWindow
    asked = []
    monkeypatch.setattr(CaptureWindow, "_ask_scaling", lambda self, text: asked.append(text) or knew)
    w = CaptureWindow(use_db=False, folder=str(tmp_path), names=["Video (01-0 Pro Capture Dual SDI 4K+)"],
                      source_factory=lambda cam, index: FakeSource(camera="ROW", signal=SIG_1K))
    w.camera_combo.setCurrentIndex(0)
    w.name_combo.setCurrentText("ROW"); w.serial_edit.setText("103032")
    w.size_combo.setCurrentText("3840 x 2160")
    assert _wait(app, lambda: w._scaling is not None)
    assert len(asked) == 1 and "upscaling" in asked[0]
    assert "upscaling" in w.status.text() and ("ACS settings" in w.status.text()) == (not knew)
    assert "camera sends 1920 x 1080i at 29.97 frames/s" in w.info.text()
    assert "delivered 3840 x 2160" in w.info.text()                    # photos stay at the ACS size
    w._start_camera()                                                  # Try again: not asked again
    assert _wait(app, lambda: w._scaling is not None) and len(asked) == 1
    assert _wait(app, lambda: w.grab_btn.isEnabled())
    w._grab(False)
    assert _wait(app, lambda: w._count == 1)
    log = json.loads(next(tmp_path.glob("ROW_103032_*/CAPTURE_*.json")).read_text(encoding="utf-8"))
    assert log["camera_signal"] == "1920 x 1080i at 29.97 frames/s"
    assert log["scaling"]["card"] == "upscaling" and log["scaling"]["crew_knew"] is knew
    assert log["scaling"]["photo_size"] == "3840x2160" and log["photos"][0]["width"] == 3840
    w.close()


def test_window_matching_size_asks_nothing(app, tmp_path, monkeypatch):
    from src.capture.source import FakeSource
    from src.capture.window import CaptureWindow
    monkeypatch.setattr(CaptureWindow, "_ask_scaling", lambda self, text: pytest.fail("must not ask"))
    w = CaptureWindow(use_db=False, folder=str(tmp_path), names=["Video (01-0 Pro Capture Dual SDI 4K+)"],
                      source_factory=lambda cam, index: FakeSource(camera="ROW", signal=SIG_1K))
    w.camera_combo.setCurrentIndex(0)
    w.name_combo.setCurrentText("ROW"); w.serial_edit.setText("103032")
    w.size_combo.setCurrentText("1920 x 1080")
    assert _wait(app, lambda: w._delivered is not None)
    for _ in range(5):
        app.processEvents(); time.sleep(0.02)
    assert w._scaling is None and "is live" in w.status.text()
    w.close()
