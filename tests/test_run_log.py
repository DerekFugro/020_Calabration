"""Run log (src/run_log.py) and app version (src/version.py)."""

from __future__ import annotations

import json
from datetime import datetime

from src.run_log import new_run_id, record_save


def test_run_id_never_reuses_a_name(tmp_path):
    when = datetime(2026, 11, 5, 14, 27, 34)
    a = new_run_id(str(tmp_path), when)
    assert a == "RUN_20261105_142734"
    (tmp_path / f"{a}.json").write_text("{}")
    b = new_run_id(str(tmp_path), when)
    assert b == "RUN_20261105_142734_2"


def test_record_save_adds_and_keeps_earlier_saves(tmp_path):
    p = tmp_path / "RUN_x.json"
    p.write_text(json.dumps({"run_id": "RUN_x", "saved": None}))
    record_save(p, cal_yaml="CAL_1.yaml", serial="2001964")
    d = json.loads(p.read_text())
    assert d["saved"]["cal_yaml"] == "CAL_1.yaml" and d["saved"]["serial"] == "2001964" and d["saved"]["at"]
    record_save(p, cal_yaml="CAL_2.yaml")
    d = json.loads(p.read_text())
    assert [s["cal_yaml"] for s in d["saved"]] == ["CAL_1.yaml", "CAL_2.yaml"]


def test_read_only_run_writes_nothing(tmp_path):
    from src.pipeline import run_folder
    (tmp_path / "a.jpg").write_bytes(b"not a photo")
    r = run_folder(str(tmp_path), change_folder=False)
    assert not list(tmp_path.glob("RUN_*.json")) and not list(tmp_path.glob("*.dots.json"))
    assert r.run_log == ""


def test_failed_run_still_logged(tmp_path):
    from src.pipeline import run_folder
    from src.boards import list_boards
    (tmp_path / "a.jpg").write_bytes(b"not a photo")
    r = run_folder(str(tmp_path), board=list_boards()[0], inputs={"van": "ARAN69", "van_from": "computer name"})
    logs = list(tmp_path.glob("RUN_*.json"))
    assert len(logs) == 1 and r.run_log
    d = json.loads(logs[0].read_text())
    assert d["inputs"]["van"] == "ARAN69" and d["app_version"] and d["error"]


def test_app_version_known():
    from src.version import app_version
    assert app_version() and app_version() != ""
