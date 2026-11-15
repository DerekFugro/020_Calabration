"""Capture's link to the POS logger (Phase 8): start, wait for green, mark a position into
its folder, get the mark summary, close cleanly.  Uses tests/fake_pos_logger.py (no POS)."""
import json
import sys
from pathlib import Path

import pytest

from src.capture import pos_link
from src.capture.pos_link import MarkResult, PosError, PosLink

FAKE = str(Path(__file__).with_name("fake_pos_logger.py"))


def link(tmp_path, *args):
    return PosLink(argv=[sys.executable, FAKE, "--surveyor", "--out", str(tmp_path), *args],
                   cwd=str(tmp_path))


def test_lines_and_the_real_app_command():
    assert json.loads(pos_link.command_line("mark", id=3, label="Position1", folder="F:\\x", seconds=None)) \
        == {"cmd": "mark", "label": "Position1", "folder": "F:\\x", "id": 3}
    assert pos_link.parse_line('{"type":"bye"}\n') == {"type": "bye"}
    assert pos_link.parse_line("garbage") is None and pos_link.parse_line("[1]") is None
    argv = pos_link.app_argv(r"E:\DP\POSProcessor", "F:\\")
    assert argv[0].endswith(r".venv\Scripts\pythonw.exe") and argv[1:] == ["app.py", "--surveyor", "--out", "F:\\"]
    assert pos_link.MARK_SECONDS == 300 and pos_link.NEED_PROTOCOL == 2


def test_a_position_marked_into_its_folder(tmp_path):
    pos = link(tmp_path)
    pos.start(str(tmp_path))
    try:
        st = pos.wait_ready(10)
        assert st.ok_to_collect and st.light == "green" and st.session_folder.endswith("SurveyorPOS_20261115_120000")
        assert pos.refresh().ok_to_collect
        folder = tmp_path / "ROW" / "Position1"; folder.mkdir(parents=True)
        rep = pos.mark("Position1", str(folder), seconds=50)          # 0.5 s with the fake's time scale
        assert rep["ok"] and rep["mark"] == 1 and Path(rep["file"]).parent == folder
        assert pos.result(1) is None                                  # still recording
        for _ in range(100):
            if pos.result(1):
                break
            pos.messages.get(timeout=5)
        r = pos.result(1)
        assert isinstance(r, MarkResult) and r.complete and r.green_whole_time and r.rows == 15000
        assert r.max_rms_m == (0.35, 0.35, 0.44) and r.spread_deg[2] == 0.016 and r.time_type == "UTC"
        assert (folder / "01_Position1.csv").exists()
    finally:
        assert pos.close() == []
    assert pos.bye and not pos.killed and pos.proc.returncode == 0


def test_missing_folder_is_refused_not_fatal(tmp_path):
    pos = link(tmp_path); pos.start(str(tmp_path))
    try:
        pos.wait_ready(10)
        rep = pos.mark("Position9", str(tmp_path / "missing"))
        assert rep["ok"] is False and "Folder does not exist" in rep["error"]
        with pytest.raises(ValueError):
            pos.mark("Position9", "relative\\path")
    finally:
        pos.close()


def test_closing_mid_mark_gives_the_cut_short_mark(tmp_path):
    pos = link(tmp_path); pos.start(str(tmp_path))
    pos.wait_ready(10)
    (tmp_path / "P1").mkdir()
    pos.mark("Position1", str(tmp_path / "P1"))                       # 3 s with the fake: still running
    cut = pos.close()
    assert len(cut) == 1 and cut[0].label == "Position1" and not cut[0].complete
    assert pos.bye and not pos.killed


def test_old_pos_app_is_refused(tmp_path):
    pos = link(tmp_path, "--protocol", "1"); pos.start(str(tmp_path))
    try:
        with pytest.raises(PosError, match="too old"):
            pos.wait_ready(10)
    finally:
        pos.close()


def test_no_recording_in_time(tmp_path):
    pos = link(tmp_path, "--no-logging"); pos.start(str(tmp_path))
    try:
        with pytest.raises(PosError, match="did not start recording in 1 s"):
            pos.wait_ready(1)
    finally:
        pos.close()


def test_start_error_is_shown(tmp_path):
    pos = link(tmp_path, "--start-error", "Drive F: not found"); pos.start(str(tmp_path))
    try:
        with pytest.raises(PosError, match="Drive F: not found"):
            pos.wait_ready(10)
    finally:
        pos.close()


def test_orange_light_is_not_ok_to_collect(tmp_path):
    pos = link(tmp_path, "--light", "orange"); pos.start(str(tmp_path))
    try:
        st = pos.wait_ready(10)
        assert st.logging and not st.ok_to_collect and st.message == "Few satellites"
    finally:
        pos.close()


def test_app_not_found(tmp_path):
    with pytest.raises(PosError, match="was not found"):
        PosLink(app_dir=str(tmp_path / "nothing")).start(str(tmp_path))


def test_killed_only_as_a_last_resort(tmp_path):
    pos = link(tmp_path, "--ignore-quit"); pos.start(str(tmp_path))
    pos.wait_ready(10)
    pos.close(wait=1)
    assert pos.killed and not pos.alive
