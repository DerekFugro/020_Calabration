"""app_window.py — the tabbed window: one tab per step of the procedure.

  Load Intrinsic     photos already collected -> grade -> export   (works)
                     · One camera (default): setup -> report
                     · Whole van: every camera in one table
  Capture Intrinsic  the app takes the photos itself                (planned)
  Load Extrinsic     Old School EOP/GCP -> camera angles + lever arms (next)
  Capture Extrinsic  the app runs the static setup itself           (planned)

The van bar on top is shared: the van picked there labels every output.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QTabWidget, QVBoxLayout, QWidget,
)

from src.styles import STYLESHEET_MAIN
from src.widgets.main_window import MainWindow
from src.widgets.van_intrinsic_screen import VanIntrinsicScreen


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

        # Van bar
        self.van_edit = QLineEdit(); self.van_edit.setPlaceholderText("ARAN65")
        self.van_edit.setMaximumWidth(140)
        self.van_status = QLabel("Intrinsic: not graded")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Van:")); bar.addWidget(self.van_edit)
        bar.addSpacing(20); bar.addWidget(self.van_status, 1)

        # Load Intrinsic = Whole van + One camera
        self.van_screen = VanIntrinsicScreen()
        self.single = MainWindow()
        self.single.setWindowFlags(Qt.WindowType.Widget)
        self.load_intrinsic = QTabWidget()
        self.load_intrinsic.addTab(self.single, "One camera")      # default
        self.load_intrinsic.addTab(self.van_screen, "Whole van")
        self.load_intrinsic.setCurrentWidget(self.single)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.load_intrinsic, "Load Intrinsic")
        self.tabs.addTab(_planned("Capture Intrinsic — planned", [
            "The app will drive the camera and take the board photos itself.",
            "Live 3x3 grid: each area turns green once it has enough points and tilt.",
            "Stops asking for photos when the grade passes.",
        ]), "Capture Intrinsic")
        from src.widgets.extrinsic_screen import ExtrinsicScreen
        self.extrinsic = ExtrinsicScreen(intrinsic_provider=self._intrinsic_for)
        self.extrinsic.status.connect(self.statusBar().showMessage)
        self.tabs.addTab(self.extrinsic, "Load Extrinsic")
        self.tabs.addTab(_planned("Capture Extrinsic — planned", [
            "The app runs the static setup: finds the targets in each photo "
            "itself instead of clicking.",
        ]), "Capture Extrinsic")

        from src.widgets.boards_tab import BoardsTab
        self.boards_tab = BoardsTab()
        self.tabs.addTab(self.boards_tab, "Boards")
        self.boards_tab.status.connect(self.statusBar().showMessage)
        self.boards_tab.boards_changed.connect(self.single.setup_screen.reload_boards)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(bar); lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready.")

        self.van_screen.van_changed.connect(self.van_edit.setText)
        self.van_screen.status.connect(self._status)
        self.van_screen.open_requested.connect(self._open_in_single)
        self.van_edit.textChanged.connect(lambda t: setattr(self.single, "van", t.strip()))

    def _intrinsic_for(self, camera: str):
        """A passed intrinsic for this camera from the Whole van table, or None."""
        from src.extrinsic.intrinsic_source import from_run
        vs = self.van_screen
        for r, run in vs._runs.items():
            if vs._cell(r, 0) == camera:
                got = from_run(run, vs._cell(r, 1))
                if got is not None:
                    return got
        return None

    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text)
        runs = self.van_screen._runs
        if runs:
            parts = []
            for r, run in sorted(runs.items()):
                cam = self.van_screen._cell(r, 0)
                g = run.grade
                parts.append(f"{cam} {'ERROR' if run.error else ('pass' if g.passed else 'not passed')}")
            self.van_status.setText("Intrinsic: " + ",  ".join(parts))

    def _open_in_single(self, run, role: str, serial: str) -> None:
        self.single.show_result(run.folder, role, serial, run.board, run.detections,
                                run.filter_results, run.cal, run.quality)
        self.load_intrinsic.setCurrentWidget(self.single)
