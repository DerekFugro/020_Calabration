"""Shared test setup.

Settings isolation (2026-11-14): the app's screens save to the Windows registry through
QSettings(org, app).  Tests must never write there, or the real app opens on a pytest temp
folder (seen in the Phase 4 check).  Every QSettings(org, app) in these modules is sent to an
.ini file in a temp folder for the whole test run.
"""
import importlib

import pytest
from PySide6.QtCore import QSettings

_MODULES = ("src.capture.window", "src.widgets.camera_bar", "src.widgets.setup_screen")


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path_factory, monkeypatch):
    folder = tmp_path_factory.getbasetemp() / "qsettings"
    folder.mkdir(exist_ok=True)

    def ini(org="test", app="test", *rest):
        return QSettings(str(folder / f"{org}_{app}.ini"), QSettings.Format.IniFormat)

    for name in _MODULES:
        monkeypatch.setattr(importlib.import_module(name), "QSettings", ini)
    yield

