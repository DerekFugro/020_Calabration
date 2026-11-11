"""app_window.py — the main window: one tab per step of the procedure.

  Load Intrinsic     one camera's lens photos -> grade -> save / export
  Capture Intrinsic  the app takes the photos itself                (planned)
  Load Extrinsic     one camera's Old School photos -> camera angles + lever arms
  Capture Extrinsic  the app runs the static setup itself           (planned)
  Boards             add, measure and print calibration boards

One camera at a time (Derek, 2026-11-03): the Whole van table was removed.
The bar on top is shared (src/widgets/camera_bar.py): van, camera and serial label every
output, and the lens made on Load Intrinsic is used by Load Extrinsic for the same camera
without loading it again.  Changing the camera clears both tabs (Derek, 2026-11-10).
All screens report through the one status bar at the bottom.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QLabel, QMainWindow, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
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
        self.setWindowTitle("SurveyorCalibration")
        # Never open bigger than the screen; a tab that needs more room scrolls instead.
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        a = scr.availableGeometry() if scr is not None else None
        self.resize(min(1250, a.width() - 40) if a else 1250, min(850, a.height() - 60) if a else 850)
        self.setStyleSheet(STYLESHEET_MAIN)
        say = self.statusBar().showMessage

        # Bar on top: van, camera, serial
        from src.widgets.camera_bar import CameraBar
        self.bar = CameraBar()
        self.van_edit = self.bar.van_edit

        self.single = OneCameraScreen(self.bar)

        from src.widgets.boards_tab import BoardsTab
        from src.widgets.extrinsic_screen import ExtrinsicScreen
        self.extrinsic = ExtrinsicScreen(self.bar, intrinsic_provider=self._intrinsic_for)
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
        boards_scroll = QScrollArea(); boards_scroll.setWidgetResizable(True)
        boards_scroll.setFrameShape(QFrame.Shape.NoFrame); boards_scroll.setWidget(self.boards_tab)
        self.tabs.addTab(boards_scroll, "Boards")

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addWidget(self.bar); lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        say("Ready.")

        for screen in (self.single, self.extrinsic, self.boards_tab):
            screen.status.connect(say)
        self.boards_tab.boards_changed.connect(self.single.setup_screen.reload_boards)
        self.bar.camera_changed.connect(lambda _c: self.single.new_camera())
        self.bar.camera_changed.connect(lambda _c: self.extrinsic.new_camera())
        self.tabs.currentChanged.connect(lambda _i: self.extrinsic.refresh_lens())
        # Load Extrinsic's buttons sit in the top bar row, shown only on that tab (2026-11-11).
        self.bar.set_actions([self.extrinsic.actions])
        self.tabs.currentChanged.connect(self._tab_shown)
        self._tab_shown(self.tabs.currentIndex())
        # On the van, the PC name says which van it is (ARAN69-SERVER, ARAN69-ROW); shown so
        # it can be corrected.
        from src.van_scan import van_from_computer
        self.van_edit.setText(van_from_computer())

    def _tab_shown(self, _i):
        self.extrinsic.actions.setVisible(self.tabs.currentWidget() is self.extrinsic)

    def _intrinsic_for(self):
        """This session's Load Intrinsic lens for the camera in the top bar, or None.
        (Changing the camera clears Load Intrinsic, so a lens here is always this camera's.)"""
        from src.extrinsic.intrinsic_source import from_run
        from src.van_scan import camera_from_name
        run = self.single.last_run
        lens_cam = camera_from_name(self.single.last_role) or self.single.last_role
        if run is None or lens_cam != self.bar.camera:
            return None
        return from_run(run, self.single.last_serial, lens_cam)
