"""Van database lookup (src/camera_db.py)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from src import camera_db


def test_candidates():
    assert camera_db.candidates("ARAN28") == [("ARAN28-SERVER", "ARAN28"), ("localhost", "ARAN28")]
    assert camera_db.candidates("") == []


def test_prefers_this_vans_enabled_rows(monkeypatch):
    from datetime import datetime
    rows = [SimpleNamespace(Name="ARANSW1", VideoModuleName="ARAN01-Server", CaptureView="ROW", CameraSerialNumber="111",
                            CCDWidth=2880, CCDHeight=1860, Enabled=1, IDVideoSystemConfiguration=5,
                            TimeChanged=datetime(2026, 1, 1), CaptureDeviceName="Video (00-0 x)"),
            SimpleNamespace(Name="ARANSW1", VideoModuleName="AranSW1-Server", CaptureView="ROW", CameraSerialNumber="222",
                            CCDWidth=2880, CCDHeight=1860, Enabled=1, IDVideoSystemConfiguration=6,
                            TimeChanged=datetime(2026, 2, 1), CaptureDeviceName="Video (01-1 x)"),
            SimpleNamespace(Name="ARANSW1", VideoModuleName="AranSW1-Server", CaptureView="Rear", CameraSerialNumber="333",
                            CCDWidth=2880, CCDHeight=1860, Enabled=0, IDVideoSystemConfiguration=6,
                            TimeChanged=datetime(2026, 2, 1), CaptureDeviceName="Video (01-0 x)")]
    con = SimpleNamespace(cursor=lambda: SimpleNamespace(execute=lambda q: SimpleNamespace(fetchall=lambda: rows)),
                          close=lambda: None)
    monkeypatch.setattr(camera_db, "_connect", lambda *a: con)
    monkeypatch.setattr(camera_db, "_resolves", lambda h, wait_s=1.5: True)
    res = camera_db.lookup("ARANSW1")
    assert res.find("row").serial == "222" and res.where == "database ARANSW1 on ARANSW1-SERVER"
    assert res.find("Rear") is None                      # disabled cameras are left out
    assert res.find("ForwardLeft") is None and res.names() == ["ROW"]
    assert res.find("row").port == "Video (01-1 x)" and res.find("row").pc == "AranSW1-Server"


def test_only_the_newest_configuration_counts(monkeypatch):
    """2026-11-14: ARAN writes a new configuration on every save; old ones stay enabled (ARAN99 had
    29).  The newest one is the van's current cameras, whatever order the rows come back in."""
    from datetime import datetime
    def row(cfg, when, view, serial, port):
        return SimpleNamespace(Name="ARAN99", VideoModuleName="Aran99-Server", CaptureView=view,
                               CameraSerialNumber=serial, CCDWidth=1920, CCDHeight=1080, Enabled=True,
                               IDVideoSystemConfiguration=cfg, TimeChanged=when, CaptureDeviceName=port)
    new = datetime(2026, 11, 14, 2, 16, 15)
    rows = [row(1068, new, "ROW", "88888888", "Video (00-1 HDMI)"), row(1068, new, "Right", "312", "0-GOX-16205C-CXP"),
            row(1069, new, "ROW", "88888888", "Video (00-1 HDMI)"), row(1069, new, "Right", "312", "0-GOX-16205C-CXP"),
            row(1050, datetime(2026, 6, 30), "ROW", "107334616420124", "GigE_107334616420124"),
            row(1041, datetime(2026, 6, 17), "ROW", "312", "0-GOX-16205C-CXP")]       # old rows LAST
    con = SimpleNamespace(cursor=lambda: SimpleNamespace(execute=lambda q: SimpleNamespace(fetchall=lambda: rows)),
                          close=lambda: None)
    monkeypatch.setattr(camera_db, "_connect", lambda *a: con)
    monkeypatch.setattr(camera_db, "_resolves", lambda h, wait_s=1.5: True)
    res = camera_db.lookup("ARAN99")
    assert res.find("ROW").serial == "88888888" and res.find("Right").serial == "312"
    assert res.names() == ["ROW", "Right"] and res.find("ROW").port == "Video (00-1 HDMI)"


def test_unreachable_says_so_in_plain_words(monkeypatch):
    def boom(*a):
        raise RuntimeError("('28000', '[28000] Login failed for user (18456)')")
    monkeypatch.setattr(camera_db, "_connect", boom)
    monkeypatch.setattr(camera_db, "_resolves", lambda h, wait_s=1.5: h == "localhost")
    res = camera_db.lookup("ARAN28")
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


def test_local_aran69_copy_if_present():
    """Dev PC only: the real ARAN69 copy on this PC."""
    res = camera_db.lookup("ARAN69")
    if res.error:
        pytest.skip("no local ARAN69 database")
    assert res.find("ROW") is not None and res.find("ROW").width > 0
