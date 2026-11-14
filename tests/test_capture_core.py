"""SurveyorCapture core (docs/capture Phase 2): all with FakeSource, no capture card needed."""
import json
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from src.capture import cameras, sizes
from src.capture.capture_log import CaptureLog
from src.capture.errors import log_error
from src.capture.nosignal import colour_bars, is_no_signal
from src.capture.saver import photo_path, safe_camera, save_jpeg
from src.capture.source import FakeSource

PORTS = ["Video (00-1 Pro Capture Dual HDMI 4K+)", "Video (00-0 Pro Capture Dual HDMI 4K+)", "OBS Virtual Camera"]


@pytest.mark.parametrize("w,h", [(1920, 1080), (3840, 2160), (2448, 2048)])
def test_any_size(w, h):
    s = FakeSource()
    r = s.open(w, h)
    f = s.read()
    assert r.ok and (r.width, r.height) == (w, h) and f.shape == (h, w, 3)
    assert not is_no_signal(f)


def test_busy_says_so_in_plain_words():
    r = FakeSource(busy=True, camera="ROW").open(1920, 1080)
    assert not r.ok and r.message.startswith("ROW is busy or has no signal") and "Try again" in r.message


@pytest.mark.parametrize("w,h", [(640, 480), (1920, 1080), (3840, 2160)])
def test_no_signal_colour_bars_are_recognised(w, h):
    """bench_results.md: the card's own picture with nothing on the input."""
    import cv2
    bars = colour_bars(w, h)
    assert is_no_signal(bars)
    ok, buf = cv2.imencode(".jpg", bars, [cv2.IMWRITE_JPEG_QUALITY, 80])     # survives JPEG
    assert is_no_signal(cv2.imdecode(buf, cv2.IMREAD_COLOR))
    s = FakeSource(no_signal=True); s.open(w, h)
    assert is_no_signal(s.read())
    assert not is_no_signal(np.full((h, w, 3), 128, np.uint8))               # a grey wall is a picture


def test_wrong_size_warning():
    s = FakeSource(deliver=(1920, 1080)); r = s.open(3840, 2160)
    assert (r.width, r.height) == (1920, 1080)
    w = sizes.size_warning((3840, 2160), (r.width, r.height), "ROW")
    assert "3840 x 2160" in w and "1920 x 1080" in w
    assert sizes.size_warning((1920, 1080), (1920, 1080)) is None
    assert "640 x 480" in sizes.size_warning(None, (640, 480))
    assert sizes.expected_size(SimpleNamespace(width=2448, height=2048)) == (2448, 2048)
    assert sizes.expected_size(SimpleNamespace(width=0, height=0)) is None


def test_inputs_found_by_name_not_number():
    assert cameras.resolve_index("Video (00-0 Pro Capture Dual HDMI 4K+)", PORTS) == 1      # listed second
    assert cameras.resolve_index("video (00-1 pro capture dual hdmi 4k+)", PORTS) == 0
    assert cameras.resolve_index("Video (02-1 Pro Capture Dual SDI 4K+)", PORTS) is None


def test_database_list_bitflow_greyed_without_card(monkeypatch):
    """BitFlow cameras: greyed with the reason when the SDK or board is missing (Phase 9)."""
    monkeypatch.setattr("src.capture.bitflow.support", lambda port: (False, "BitFlow camera: board 0 is not on this PC."))
    from src.camera_db import CameraRow, DbResult
    res = DbResult(cameras={
        "ROW": CameraRow("ROW", "88888888", 1920, 1080, PORTS[0], "Aran99-Server"),
        "FORWARDRIGHT": CameraRow("ForwardRight", "0103043", 1920, 1080, PORTS[1], "Aran99-Server"),
        "RIGHT": CameraRow("Right", "312", 1920, 1080, "0-GOX-16205C-CXP", "Aran99-Server")},
        server="ARAN99-SERVER", database="ARAN99")
    monkeypatch.setattr("src.camera_db.lookup_cached", lambda van: res)
    cams, msg = cameras.from_database("ARAN99", PORTS)
    by = {c.name: c for c in cams}
    assert msg == "" and set(by) == {"ROW", "ForwardRight", "Right"}
    assert by["ROW"].supported and by["ROW"].source == "database"
    assert by["ForwardRight"].serial == "0103043"                                 # leading zero kept
    assert not by["Right"].supported and "BitFlow" in by["Right"].why
    assert cameras.other_pc_warning(by["ROW"], "ARAN99-SERVER") is None
    assert "ARAN69-ROW" in cameras.other_pc_warning(by["ROW"], "ARAN69-ROW")


def test_database_error_and_ports_only(monkeypatch):
    from src.camera_db import DbResult
    monkeypatch.setattr("src.camera_db.lookup_cached", lambda van: DbResult(error="Could not read the van database."))
    cams, msg = cameras.from_database("ARAN99", PORTS)
    assert cams == [] and "Could not read" in msg
    ports = cameras.from_ports(PORTS)
    assert [c.port for c in ports] == PORTS and all(c.name == "" and c.source == "user" for c in ports)


def test_never_overwrite(tmp_path):
    when = datetime(2026, 11, 14, 2, 30, 5, 123000)
    assert safe_camera("Forward Left/../x") == "Forward_Left_x" and safe_camera("") == "Camera"
    p1 = save_jpeg(np.zeros((1080, 1920, 3), np.uint8), tmp_path, "ROW", when=when)
    p2 = save_jpeg(np.zeros((1080, 1920, 3), np.uint8), tmp_path, "ROW", when=when)
    assert p1.name == "ROW_20261114_023005_123.jpg" and p2.name == "ROW_20261114_023005_123_2.jpg"
    assert photo_path(tmp_path, "ROW", when).name == "ROW_20261114_023005_123_3.jpg"
    import cv2
    assert cv2.imread(str(p1)).shape == (1080, 1920, 3)                         # full size, no resizing


def test_save_into_folder_with_any_characters(tmp_path):
    d = tmp_path / "Calibración ÄÖ"
    p = save_jpeg(np.zeros((100, 200, 3), np.uint8), d, "ROW")
    assert p.exists() and p.stat().st_size > 0


def test_capture_log(tmp_path):
    log = CaptureLog(tmp_path, "ARAN99", "ROW", "database", PORTS[0], "0103043", (1920, 1080), (1920, 1080), True)
    log2 = CaptureLog(tmp_path, "ARAN99", "ROW", "database", PORTS[0], "0103043", (1920, 1080), (1920, 1080), True)
    assert log.path != log2.path                                                # never overwritten
    log.add(tmp_path / "ROW_1.jpg", 1920, 1080)
    log.add(tmp_path / "ROW_2.jpg", 1920, 1080, countdown=True)
    d = json.loads(log.path.read_text(encoding="utf-8"))
    assert d["serial"] == "0103043" and d["camera_source"] == "database" and d["van_database_used"] is True
    assert [p["file"] for p in d["photos"]] == ["ROW_1.jpg", "ROW_2.jpg"] and d["photos"][1]["countdown"]
    assert d["expected_size"] == "1920x1080" and d["app_version"] and d["computer"]
    assert not list(tmp_path.glob("*.tmp"))


def test_error_log_rotates_and_hides_passwords(tmp_path, monkeypatch):
    from src.capture import errors
    p = tmp_path / "capture_errors.log"
    monkeypatch.setattr(errors, "MAX_BYTES", 100)
    log_error("opened DRIVER=x;PWD=secret;", path=p)
    assert "secret" not in p.read_text(encoding="utf-8")
    log_error("x" * 200, path=p); log_error("after rotate", path=p)
    assert p.with_suffix(".log.1").exists() and "after rotate" in p.read_text(encoding="utf-8")


def test_session_folder_name_and_never_reused(tmp_path):
    from datetime import datetime
    from src.capture.saver import session_folder
    when = datetime(2026, 11, 14, 6, 36, 5)
    a = session_folder(tmp_path, "Right", "000312", when)
    b = session_folder(tmp_path, "Right", "000312", when)
    assert a.name == "Right_000312_20261114_063605" and b.name == "Right_000312_20261114_063605_2"
    assert session_folder(tmp_path, "ROW", "", when).name == "ROW_noserial_20261114_063605"
    assert a.is_dir() and b.is_dir()
