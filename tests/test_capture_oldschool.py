"""Old School collection in Capture (Phase 8, task 3): folder names, the position rating, and
the window's whole loop with a fake camera and a fake POS logger (tests/fake_pos_logger.py):
Save image -> Position<N> with photos + the POS CSV + a log with the rating."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from src.capture import oldschool as osc
from src.capture.pos_link import MarkResult, PosLink

FAKE = str(Path(__file__).with_name("fake_pos_logger.py"))
PORT = "Video (01-0 Pro Capture Dual SDI 4K+)"


# ── no Qt ────────────────────────────────────────────────────────────────────
def test_site_folder_name():
    when = datetime(2026, 11, 15, 16, 43, 0)
    assert osc.site_folder_name("ARAN59", when) == "ExtrinsicAran59_20261115_164300"
    assert osc.site_folder_name("aran 9", when) == "ExtrinsicAran9_20261115_164300"
    assert osc.site_folder_name("", when) == "Extrinsic_20261115_164300"
    assert osc.site_folder_name("Bench PC", when) == "ExtrinsicBenchPC_20261115_164300"


def test_position_folders_count_up_and_never_reuse(tmp_path):
    assert osc.make_position_folder(tmp_path, "ROW") == (1, tmp_path / "ROW" / "Position1")
    (tmp_path / "ROW" / "Position7").mkdir(); (tmp_path / "ROW" / "Position8.txt").write_text("x")
    assert osc.make_position_folder(tmp_path, "ROW")[0] == 8
    assert osc.make_position_folder(tmp_path, "RearLeft")[0] == 1


def _checker(blur=False):
    import cv2
    img = (np.indices((1080, 1920)).sum(axis=0) // 60 % 2 * 255).astype(np.uint8)
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return cv2.GaussianBlur(img, (0, 0), 25) if blur else img


def test_photo_quality_sharp_blurry_blank():
    sharp, blurry = osc.photo_quality(_checker()), osc.photo_quality(_checker(blur=True))
    assert sharp[0] > osc.MIN_SHARPNESS > blurry[0]
    assert osc.photo_quality(np.zeros((1080, 1920, 3), np.uint8))[1] < osc.MIN_CONTRAST
    assert osc.photo_quality(None) == (0.0, 0.0)


def _pos(**kw):
    d = dict(mark=1, label="ROW_Position1", seconds=300.0, rows=15000, complete=True, green_whole_time=True,
             worst_light="green", worst_message="POS ready", spread_deg=(0.01, 0.01, 0.02))
    d.update(kw)
    return MarkResult(**d)


GOOD = osc.PhotoCheck("a.jpg", 300.0, 60.0, False)
BLUR = osc.PhotoCheck("b.jpg", 3.0, 60.0, False)
BARS = osc.PhotoCheck("c.jpg", 900.0, 90.0, True)


@pytest.mark.parametrize("pos, photos, words", [
    (_pos(), [BLUR, GOOD], []),
    (_pos(green_whole_time=False, worst_message="Few satellites"), [GOOD], ["the POS lost accuracy (Few satellites)"]),
    (_pos(spread_deg=(0.01, 0.3, 0.02)), [GOOD], ["the van moved"]),
    (_pos(spread_deg=(0.024, 0.022, 0.21)), [GOOD], []),          # ARAN59 parked: heading wanders, not moved
    (_pos(complete=False, rows=300), [GOOD], ["the POS logging stopped early"]),
    (_pos(rows=5000), [GOOD], ["the POS logging stopped early"]),
    (None, [GOOD], ["the POS did not finish logging this position"]),
    (_pos(), [BLUR, BLUR], ["the photos are blurry"]),
    (_pos(), [BARS], ["the photos show no picture"]),
    (_pos(), [], ["no photos were saved"]),
])
def test_rating(pos, photos, words):
    r = osc.rate_position(pos, photos, {"move_m": 0.018, "max_speed_mps": 0.0})
    assert r.passed == (not words) and r.reasons == words
    if photos and not words:
        assert r.best_photo == "a.jpg"
    text = r.text(3)
    assert text == "Position 3: PASS" if not words else text.endswith("Redo this position.")


def test_van_still_from_the_pos_csv(tmp_path):
    p = tmp_path / "m.csv"
    head = "time1_s,time_type,lat_deg,lon_deg,height_m,roll_deg,pitch_deg,heading_deg,speed_mps,align_status,rms_n_m,rms_e_m,rms_d_m,light,message\n"
    rows = [f"{i},UTC,37.6055085,{-77.4918355 + i * 1e-7},28.9,0.30,0.23,{359.95 if i % 2 else 0.05},0.0,0,0.35,0.35,0.44,green,POS ready\n"
            for i in range(10)]
    p.write_text(head + "".join(rows), encoding="utf-8")
    s = osc.van_still(p)
    assert s["rows"] == 10 and 0.07 < s["move_m"] < 0.08 and abs(s["heading_spread_deg"] - 0.1) < 1e-6
    r = osc.rate_position(_pos(), [GOOD], s)
    assert r.passed and r.still["move_m"] == s["move_m"]
    assert osc.rate_position(_pos(), [GOOD], {"move_m": 0.5}).reasons == ["the van moved"]
    assert osc.rate_position(_pos(), [GOOD], {"max_speed_mps": 0.6}).reasons == ["the van moved"]
    assert osc.van_still(tmp_path / "none.csv") == {}


# ── the window ───────────────────────────────────────────────────────────────
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


def _window(app, tmp_path, monkeypatch, sharp=True, pos_args=()):
    from src.capture.source import FakeSource
    from src.capture.window import CaptureWindow

    class Source(FakeSource):
        def read(self):
            f = super().read()
            if f is not None and sharp and not self.no_signal:
                f = _checker().copy(); f[:8, :8] = self._n % 256     # a new frame each time
            return f

    monkeypatch.setattr(osc, "PHOTOS", 2)
    root = tmp_path / "root"; root.mkdir()
    pos_factory = lambda: PosLink(argv=[sys.executable, FAKE, "--surveyor", "--out", "{out}", *pos_args],  # noqa: E731
                                  cwd=str(tmp_path))                     # {out} = the site folder
    w = CaptureWindow(use_db=False, names=[PORT], source_factory=lambda cam, index: Source(camera="ROW"),
                      old_school=True, os_root=str(root), pos_factory=pos_factory)
    w._ask_close = lambda: True
    w.van_edit.setText("ARAN59")
    w.camera_combo.setCurrentIndex(0)
    w.name_combo.setCurrentText("ROW"); w.serial_edit.setText("103032")
    w.size_combo.setCurrentText("1920 x 1080")
    return w, root


def test_old_school_screen_shows_only_what_the_crew_needs(app, tmp_path, monkeypatch):
    w, root = _window(app, tmp_path, monkeypatch)
    try:
        assert wait(app, lambda: w._os._ready, 15)
        site = Path(w.folder_edit.text())
        assert site.parent == root and site.name.startswith("Extrinsic") and site.is_dir()
        assert w.windowTitle().endswith("Old School") and w.folder_title.text() == "Site folder:"
        for b in (w.grab_btn, w.countdown_btn, w.auto_btn, w.open_cal_btn, w.advanced_btn):
            assert b.isHidden()
        assert wait(app, lambda: w._os.save_btn.isEnabled())
        assert w._os.light.text() == "POS ready" and "Park at the first position" in w._os.big.text()
    finally:
        w.close()
    assert w._os.pos.bye and not w._os.pos.killed


def test_a_position_saved_and_rated(app, tmp_path, monkeypatch):
    w, root = _window(app, tmp_path, monkeypatch)
    try:
        assert wait(app, lambda: w._os.save_btn.isEnabled(), 15)
        w._os._mark_secs = 50                 # 0.5 s with the fake's time scale
        w._os.save_btn.click()
        w._refresh_cameras()                  # e.g. focus leaving the van box: must not change the camera
        w.van_edit.setText("ARAN99"); w.van_edit.editingFinished.emit()
        assert not w.camera_combo.isEnabled()                       # camera locked while collecting
        assert wait(app, lambda: not w._os.busy, 20)
        assert w.camera_combo.isEnabled()
        assert w._os.result.text() == "Position 1: PASS", w._os.result.text()
        assert w._cam is not None and w.camera_name() == "ROW"        # the camera never changed
        assert "Move to the next position" in w._os.big.text() and "1 position passed" in w._os.tally.text()
        p1 = Path(w.folder_edit.text()) / "ROW" / "Position1"
        assert len(list(p1.glob("ROW_*.jpg"))) == 2 and (p1 / "01_ROW_Position1.csv").exists()
        log = json.loads(next(p1.glob("CAPTURE_*.json")).read_text(encoding="utf-8"))
        os_ = log["old_school"]
        assert os_["position"] == 1 and os_["rating"]["passed"] and os_["pos_mark"]["green_whole_time"]
        assert len(os_["photos_checked"]) == 2 and os_["rating"]["best_photo"].startswith("ROW_")
        assert len(log["photos"]) == 2 and log["camera"] == "ROW" and log["serial"] == "103032"
        # the next Save makes Position2
        assert wait(app, lambda: w._os.save_btn.isEnabled())
        w._os.save_btn.click()
        assert wait(app, lambda: not w._os.busy, 20)
        assert (p1.parent / "Position2").is_dir() and "2 positions passed" in w._os.tally.text()
    finally:
        w.close()


def test_blurry_photos_say_redo(app, tmp_path, monkeypatch):
    w, root = _window(app, tmp_path, monkeypatch, sharp=False)
    try:
        assert wait(app, lambda: w._os.save_btn.isEnabled(), 15)
        w._os._mark_secs = 50
        w._os.save_btn.click()
        assert wait(app, lambda: not w._os.busy, 20)
        assert w._os.result.text() == "Position 1: NOT PASSED - the photos are blurry. Redo this position."
        assert "Redo this position" in w._os.big.text() and "0 positions passed" in w._os.tally.text()
    finally:
        w.close()


def test_no_save_while_the_pos_is_not_green(app, tmp_path, monkeypatch):
    w, root = _window(app, tmp_path, monkeypatch, pos_args=("--light", "orange"))
    try:
        assert wait(app, lambda: w._os._ready, 15)
        assert wait(app, lambda: w._ready_to_grab())
        app.processEvents()
        assert not w._os.save_btn.isEnabled() and w._os.light.text() == "Few satellites"
    finally:
        w.close()


def test_pos_app_missing_is_said_plainly(app, tmp_path, monkeypatch):
    from src.capture.window import CaptureWindow
    w = CaptureWindow(use_db=False, names=[PORT], old_school=True, os_root=str(tmp_path),
                      pos_factory=lambda: PosLink(app_dir=str(tmp_path / "nothing")),
                      source_factory=lambda cam, index: None)
    try:
        assert wait(app, lambda: "was not found" in w._os.light_text.text(), 10)
        assert w._os.light.text() == "No POS logging" and not w._os.save_btn.isEnabled()
    finally:
        w.close()
