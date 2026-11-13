"""app_window.py — the main window: one tab per step of the procedure.

  Load Intrinsic     one camera's lens photos -> grade -> save / export
  Load Extrinsic     one camera's Old School photos -> camera angles + lever arms
  Boards             add, measure and print calibration boards

Opened from the start screen (src/widgets/start_screen.py, Derek 2026-11-13), on the tab
that was chosen, with the van database on or off as chosen there.  Home goes back to the
start screen; the launcher then throws this window away, so nothing carries over.
Photo capture is a separate program (docs/capture), not a tab.

One camera at a time (Derek, 2026-11-03): the Whole van table was removed.
The bar on top is shared (src/widgets/camera_bar.py): van, camera and serial label every
output, and the lens made on Load Intrinsic is used by Load Extrinsic for the same camera
without loading it again.  Changing the camera clears both tabs (Derek, 2026-11-10).
All screens report through the one status bar at the bottom.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame, QMainWindow, QMessageBox, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from src.styles import STYLESHEET_MAIN
from src.widgets.one_camera_screen import OneCameraScreen


class AppWindow(QMainWindow):
    def __init__(self, parent=None, use_db: bool = True, on_home=None) -> None:
        super().__init__(parent)
        self.on_home = on_home          # launcher: back to the start screen (None = no Home button)
        # Version in the title (2026-11-11): installed copy -> its VERSION file, git checkout -> the commit
        from src.version import app_version
        self.setWindowTitle(f"SurveyorCalibration   {app_version()}")
        # Never open bigger than the screen; a tab that needs more room scrolls instead.
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        a = scr.availableGeometry() if scr is not None else None
        self.resize(min(1250, a.width() - 40) if a else 1250, min(850, a.height() - 60) if a else 850)
        self.setStyleSheet(STYLESHEET_MAIN)
        say = self.statusBar().showMessage

        # Bar on top: van, camera, serial
        from src.widgets.camera_bar import CameraBar
        self.bar = CameraBar(use_db=use_db)
        self.van_edit = self.bar.van_edit

        self.single = OneCameraScreen(self.bar)

        from src.widgets.boards_tab import BoardsTab
        from src.widgets.extrinsic_screen import ExtrinsicScreen
        self.extrinsic = ExtrinsicScreen(self.bar, intrinsic_provider=self._intrinsic_for)
        self.boards_tab = BoardsTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.single, "Load Intrinsic")
        self.tabs.addTab(self.extrinsic, "Load Extrinsic")
        boards_scroll = QScrollArea(); boards_scroll.setWidgetResizable(True)
        boards_scroll.setFrameShape(QFrame.Shape.NoFrame); boards_scroll.setWidget(self.boards_tab)
        self.tabs.addTab(boards_scroll, "Boards")
        self._boards_page = boards_scroll

        # Home: back to the start screen (2026-11-13)
        self.home_btn = QPushButton("Home")
        self.home_btn.setToolTip("Back to the start screen.  Everything here is cleared.")
        self.home_btn.clicked.connect(self._home)
        self.home_btn.setVisible(on_home is not None)
        self.bar._row.insertWidget(0, self.home_btn)
        from PySide6.QtCore import QTimer
        self._busy_timer = QTimer(self); self._busy_timer.timeout.connect(self._sync_home); self._busy_timer.start(400)

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
        self.bar.set_actions([self.single.actions, self.extrinsic.actions])
        self.tabs.currentChanged.connect(self._tab_shown)
        self._tab_shown(self.tabs.currentIndex())
        # On the van, the PC name says which van it is (ARAN69-SERVER, ARAN69-ROW); shown so
        # it can be corrected.  Database off (another van's photos, 2026-11-13): left blank, so the
        # van comes from the photo folder (…\ARAN54_2025-06-19\…) and files aren't named after this PC.
        from src.van_scan import van_from_computer
        if use_db:
            self.van_edit.setText(van_from_computer())
        else:
            self.van_edit.setPlaceholderText("from the photo folder")
            self.bar._van_typed("")

    # ── start screen / Home ─────────────────────────────────────────────────
    def open_tab(self, tab: str, folder: str = "") -> None:
        """Show the tab chosen on the start screen; a photo folder goes to Load Intrinsic."""
        page = {"intrinsic": self.single, "extrinsic": self.extrinsic, "boards": self._boards_page}.get(tab, self.single)
        self.tabs.setCurrentWidget(page)
        if folder:
            self.tabs.setCurrentWidget(self.single)
            self.single.setup_screen.folder_input.setText(folder)

    def busy(self) -> bool:
        """A calibration, check or solve is running."""
        ws = [getattr(self.single, "_worker", None), getattr(self.single, "_check_worker", None),
              getattr(self.extrinsic, "_worker", None)]
        return any(w is not None and w.isRunning() for w in ws)

    def unsaved(self) -> str:
        """'' or what would be lost by leaving, in plain words."""
        out = [x for x in (self.single.unsaved(), self.extrinsic.unsaved()) if x]
        return "  ".join(out)

    def _sync_home(self) -> None:
        self.home_btn.setEnabled(not self.busy())

    def _home(self) -> None:
        if self.on_home is not None:
            self.on_home()

    def _tab_shown(self, _i):
        self.single.actions.setVisible(self.tabs.currentWidget() is self.single)
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
