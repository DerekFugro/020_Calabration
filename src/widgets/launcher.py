"""launcher.py - start screen -> main window -> Home -> start screen (Derek, 2026-11-13).

Home always gives a clean start: the main window is closed and a new one is made next
time (docs/capture: "If any state leaks ... Home closes and rebuilds the main window").
Home is refused while a calibration or solve runs, and asks before leaving a result
that is not saved.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

TABS = {"intrinsic", "extrinsic", "boards"}


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
        # "capture" / "capture_os": not built yet (greyed out on the start screen)

    def open_main(self, tab: str = "intrinsic", folder: str = "", use_db: bool | None = None):
        from src.widgets.app_window import AppWindow
        if use_db is None:
            use_db = self.start.database_on
        self.main = AppWindow(use_db=use_db, on_home=self.home)
        self.main.open_tab(tab, folder)
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
