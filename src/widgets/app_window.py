"""app_window.py — the main window: one tab per step of the procedure.

  Load Intrinsic     one camera's lens photos -> grade -> save / export
  Capture Intrinsic  the app takes the photos itself                (planned)
  Load Extrinsic     one camera's Old School photos -> camera angles + lever arms
  Capture Extrinsic  the app runs the static setup itself           (planned)
  Boards             add, measure and print calibration boards

One camera at a time (Derek, 2026-11-03): the Whole van table was removed.
The van bar on top is shared: the van typed there labels every output.
All screens report through the one status bar at the bottom.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QTabWidget, QVBoxLayout, QWidget,
)

from src.styles import STYLESHEET_MAIN
from src.widgets.one_camera_screen import OneCameraScreen


def _planned(title: str, lines: list[str]) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    head = QLabel(title); head.setStyleSheet("font-size: 14pt; font-weight: bold;")
    body = QLabel("\n".join(lines)); body.setWordWrap(True)
    body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    lay.addWidget(head); lay.addWidget(body, 1)
    return w


class AppWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calibration")
        self.resize(1250, 850)
        self.setStyleSheet(STYLESHEET_MAIN)
        say = self.statusBar().showMessage

        # Van bar
        self.van_edit = QLineEdit(); self.van_edit.setPlaceholderText("ARAN65")
        self.van_edit.setMaximumWidth(140)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Van:")); bar.addWidget(self.van_edit); bar.addStretch(1)

        self.single = OneCameraScreen()

        from src.widgets.boards_tab import BoardsTab
        from src.widgets.extrinsic_screen import ExtrinsicScreen
        self.extrinsic = ExtrinsicScreen(intrinsic_provider=self._intrinsic_for)
        self.boards_tab = BoardsTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.single, "Load Intrinsic")
        self.tabs.addTab(_planned("Capture Intrinsic — planned", [
            "The app will drive the camera and take the board photos itself.",
            "Live 3x3 grid: each area turns green once it has enough points and tilt.",
            "Stops asking for photos when the grade passes.",
        ]), "Capture Intrinsic")
        self.tabs.addTab(self.extrinsic, "Load Extrinsic")
        self.tabs.addTab(_planned("Capture Extrinsic — planned", [
            "The app runs the static setup: finds the targets in each photo "
            "itself instead of clicking.",
        ]), "Capture Extrinsic")
        self.tabs.addTab(self.boards_tab, "Boards")

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(bar); lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        say("Ready.")

        for screen in (self.single, self.extrinsic, self.boards_tab):
            screen.status.connect(say)
        self.boards_tab.boards_changed.connect(self.single.setup_screen.reload_boards)
        self.van_edit.textChanged.connect(lambda t: setattr(self.single, "van", t.strip()))

    def _intrinsic_for(self, camera: str):
        """This session's passed Load Intrinsic result for this camera, or None."""
        from src.extrinsic.intrinsic_source import from_run
        from src.van_scan import camera_from_name
        run = self.single.last_run
        if run is None or camera_from_name(self.single.last_role) != camera:
            return None
        return from_run(run, self.single.last_serial)
