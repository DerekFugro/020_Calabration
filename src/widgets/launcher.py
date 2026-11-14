"""launcher.py - start screen -> main window -> Home -> start screen (Derek, 2026-11-13).

Home always gives a clean start: the main window is closed and a new one is made next
time (docs/capture: "If any state leaks ... Home closes and rebuilds the main window").
Home is refused while a calibration or solve runs, and asks before leaving a result
that is not saved.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess
from PySide6.QtWidgets import QMessageBox

TABS = {"intrinsic", "extrinsic", "boards"}


def capture_present(prog: str, args: list[str], cwd: str) -> bool:
    """Is SurveyorCapture there to start?  (Installed exe, or src/capture in a source run.)"""
    if args[:2] == ["-m", "src.capture"]:
        return (Path(cwd) / "src" / "capture" / "__main__.py").exists()
    return Path(prog).exists()


def capture_command(van: str, use_db: bool) -> tuple[str, list[str], str]:
    """(program, arguments, working folder) that start SurveyorCapture as its own process.
    Installed: SurveyorCapture.exe beside this exe.  From source: python -m src.capture.
    Never imports src.capture (docs/capture: a capture-card hang must not freeze this app)."""
    args = (["--van", van] if van else []) + ([] if use_db else ["--no-db"])
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).with_name("SurveyorCapture.exe")
        return str(exe), args, str(exe.parent)
    root = Path(__file__).resolve().parent.parent.parent
    return sys.executable, ["-m", "src.capture"] + args, str(root)


class Launcher(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from src.widgets.start_screen import StartScreen
        self.start = StartScreen()
        self.main = None
        self.start.chosen.connect(self.choose)

    def show(self) -> None:
        self.start.show()

    def choose(self, key: str) -> None:
        if key in TABS:
            self.open_main(key)
        elif key == "capture":
            self.start_capture()
        # "capture_os": not built yet (greyed out on the start screen)

    def start_capture(self) -> bool:
        """SurveyorCapture in its own process; the start screen stays, for Calibrate lens after."""
        prog, args, cwd = capture_command(self.start.van if self.start.database_on else "", self.start.database_on)
        if not capture_present(prog, args, cwd):
            where = str(Path(cwd) / "src" / "capture") if args[:1] == ["-m"] else prog
            QMessageBox.warning(self.start, "Collect lens photos",
                                f"SurveyorCapture is not installed with this copy of the app.\nLooked for: {where}")
            return False
        res = QProcess.startDetached(prog, args, cwd)
        ok = res[0] if isinstance(res, tuple) else bool(res)
        if not ok:
            QMessageBox.warning(self.start, "Collect lens photos",
                                f"SurveyorCapture could not be started.\n{prog}")
        return ok

    def open_main(self, tab: str = "intrinsic", folder: str = "", use_db: bool | None = None, camera: str = ""):
        from src.widgets.app_window import AppWindow
        if use_db is None:
            use_db = self.start.database_on
        self.main = AppWindow(use_db=use_db, on_home=self.home)
        self.main.open_tab(tab, folder, camera)
        self.main.show()
        self.start.hide()
        return self.main

    def home(self) -> bool:
        """Back to the start screen with a clean slate.  False = stayed (busy, or the user said no)."""
        m = self.main
        if m is None:
            return True
        if m.busy():
            QMessageBox.information(m, "Home", "Wait for the calibration or solve to finish first.")
            return False
        unsaved = m.unsaved()
        if unsaved and QMessageBox.question(
                m, "Home", f"{unsaved}\n\nLeave anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        self.main = None
        m.on_home = None
        m.close()
        m.deleteLater()
        self.start.show()
        return True
