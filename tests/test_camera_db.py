"""Van database lookup (src/camera_db.py)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from src import camera_db


def test_candidates():
    assert camera_db.candidates("ARAN28", {}) == [("ARAN28-SERVER", "ARAN28"), ("localhost", "ARAN28")]
    assert camera_db.candidates("ARAN28", {"server": "X", "database": "Y"}) == [("X", "Y")]


def test_prefers_this_vans_enabled_rows(monkeypatch):
    rows = [SimpleNamespace(Name="ARANSW1", VideoModuleName="ARAN01-Server", CaptureView="ROW", CameraSerialNumber="111",
                            CCDWidth=2880, CCDHeight=1860, Enabled=1),
            SimpleNamespace(Name="ARANSW1", VideoModuleName="AranSW1-Server", CaptureView="ROW", CameraSerialNumber="222",
                            CCDWidth=2880, CCDHeight=1860, Enabled=1),
            SimpleNamespace(Name="ARANSW1", VideoModuleName="AranSW1-Server", CaptureView="Rear", CameraSerialNumber="333",
                            CCDWidth=2880, CCDHeight=1860, Enabled=0)]
    con = SimpleNamespace(cursor=lambda: SimpleNamespace(execute=lambda q: SimpleNamespace(fetchall=lambda: rows)),
                          close=lambda: None)
    monkeypatch.setattr(camera_db, "_connect", lambda *a: con)
    monkeypatch.setattr(camera_db, "_resolves", lambda h, wait_s=1.5: True)
    res = camera_db.lookup("ARANSW1", {"server": "s", "database": "d"})
    assert res.find("row").serial == "222" and res.where == "database d on s"
    assert res.find("Rear") is None                      # disabled cameras are left out
    assert res.find("ForwardLeft") is None and res.names() == ["ROW"]


def test_unreachable_says_so_in_plain_words(monkeypatch):
    def boom(*a):
        raise RuntimeError("('28000', '[28000] Login failed for user (18456)')")
    monkeypatch.setattr(camera_db, "_connect", boom)
    monkeypatch.setattr(camera_db, "_resolves", lambda h, wait_s=1.5: h == "localhost")
    res = camera_db.lookup("ARAN28", {})
    assert not res.cameras and "ARAN28-SERVER: not found on the network" in res.error
    assert "this Windows user is not allowed into ARAN28" in res.error and "Type the serial" in res.error


def test_windows_sign_in_only(monkeypatch):
    """Always Trusted_Connection; never a SQL user or password, even from old settings."""
    seen = {}
    fake = SimpleNamespace(drivers=lambda: ["ODBC Driver 18 for SQL Server"],
                           connect=lambda cs, **kw: seen.setdefault("cs", cs))
    monkeypatch.setitem(sys.modules, "pyodbc", fake)
    camera_db._connect("ARAN28-SERVER", "ARAN28", {"auth": "sql", "user": "sa"})
    assert "Trusted_Connection=yes" in seen["cs"]
    assert "UID=" not in seen["cs"] and "PWD=" not in seen["cs"]


def test_settings_keep_only_server_and_database(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_db, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(camera_db, "SETTINGS", tmp_path / "camera_db.json")
    camera_db.save_settings({"server": "S", "database": "D", "auth": "sql", "user": "sa"})
    assert camera_db.load_settings() == {"server": "S", "database": "D"}


def test_local_aran69_copy_if_present():
    """Dev PC only: the real ARAN69 copy on this PC."""
    res = camera_db.lookup("ARAN69", {"server": "localhost"})
    if res.error:
        pytest.skip("no local ARAN69 database")
    assert res.find("ROW") is not None and res.find("ROW").width > 0
