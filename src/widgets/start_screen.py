"""start_screen.py - what the app opens on, every time (Derek, 2026-11-13; docs/capture, Phase 0).

  Van database status (this PC's van, looked up in the background) and a
  "Use the van database" tick box: ticked when found, never unticked by the app.
  Untick it to work on photos from another van (e.g. ARAN54 photos on the ARAN99 bench).

  Choices: Collect lens photos (SurveyorCapture, a separate program; greyed until it
  exists), Calibrate lens, Collect Old School photos (later), Camera position, Boards.
  No van, camera or serial here: those are set in the window that opens.
"""

from __future__ import annotations

import html as _h

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.styles import STYLESHEET_MAIN

CHOICES = [  # key, label, explanation, available now
    ("capture", "Collect lens photos", "Live picture from a van camera; grab the board photos.", False),
    ("intrinsic", "Calibrate lens", "Grade a camera's board photos and make its lens file.", True),
    ("capture_os", "Collect Old School photos", "Coming later.", False),
    ("extrinsic", "Camera position", "Old School photos -> the camera's angles, height and lever arms.", True),
]


class StartScreen(QWidget):
    chosen = Signal(str)            # "capture" / "intrinsic" / "extrinsic" / "boards"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.db_res = None
        self._db_worker = None
        self._init_state()
        self._build_ui()
        self._connect_signals()
        self._apply_styles()
        self._look_up()

    def _init_state(self) -> None:
        from src.van_scan import van_from_computer
        from src.version import app_version
        self.van = van_from_computer()
        self.version = app_version()
        self.buttons: dict[str, QPushButton] = {}

    def _build_ui(self) -> None:
        self.setWindowTitle(f"SurveyorCalibration   {self.version}")
        self.title = QLabel("SurveyorCalibration")
        self.db_label = QLabel(""); self.db_label.setWordWrap(True)
        self.db_label.setTextFormat(Qt.TextFormat.RichText)
        self.use_db = QCheckBox("Use the van database (camera list and serials)")
        self.use_db.hide()
        self.db_hint = QLabel("Untick it to work on photos from another van: cameras are then picked "
                              "from the usual list and serials are typed.")
        self.db_hint.setWordWrap(True); self.db_hint.hide()
        grid = QGridLayout()
        for i, (key, label, why, ready) in enumerate(CHOICES):
            b = QPushButton(label); b.setMinimumHeight(70); b.setEnabled(ready)
            b.setToolTip(why if ready else f"{why}  (Not available yet.)")
            note = QLabel(why if ready else f"{why}  Not available yet."); note.setWordWrap(True)
            note.setObjectName("note")
            self.buttons[key] = b
            grid.addWidget(b, (i // 2) * 2, i % 2); grid.addWidget(note, (i // 2) * 2 + 1, i % 2)
        self.boards_btn = QPushButton("Boards...")
        self.boards_btn.setToolTip("Add, measure and print calibration boards")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(10)
        lay.addWidget(self.title); lay.addWidget(self.db_label); lay.addWidget(self.use_db); lay.addWidget(self.db_hint)
        lay.addSpacing(8); lay.addLayout(grid); lay.addStretch(1)
        lay.addWidget(self.boards_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.resize(720, 460)

    def _connect_signals(self) -> None:
        for key, b in self.buttons.items():
            b.clicked.connect(lambda _c=False, k=key: self.chosen.emit(k))
        self.boards_btn.clicked.connect(lambda: self.chosen.emit("boards"))

    def _apply_styles(self) -> None:
        self.setStyleSheet(STYLESHEET_MAIN + " QLabel#note { color: rgb(150,150,150); font-size: 8pt; }")
        self.title.setStyleSheet("font-size: 18pt; font-weight: bold;")
        self.db_hint.setStyleSheet("color: rgb(150,150,150); font-size: 8pt;")

    # ── the van database ─────────────────────────────────────────────────────
    def _look_up(self) -> None:
        if not self.van:
            self.set_db(None); return
        self.db_label.setText(f"Looking for the {_h.escape(self.van)} van database...")
        from src.widgets.db_worker import DbWorker
        self._db_worker = DbWorker(self.van, self)
        self._db_worker.done.connect(lambda _van, res: self.set_db(res))
        self._db_worker.start()

    def set_db(self, res) -> None:
        """Show what was found.  Found -> tick box, ticked.  Not found -> no box."""
        self.db_res = res
        found = res is not None and not res.error and bool(res.cameras)
        if found:
            self.db_label.setText(f"&#10003; Van database: {_h.escape(res.database)} on {_h.escape(res.server)}, "
                                  f"{len(res.cameras)} camera{'s' if len(res.cameras) != 1 else ''} "
                                  f"({_h.escape(', '.join(res.names()))})")
            self.db_label.setStyleSheet("color: rgb(60,200,60);")
            self.use_db.setChecked(True)
        else:
            self.db_label.setText("No van database on this PC: cameras and serials are typed.")
            self.db_label.setStyleSheet("color: rgb(150,150,150);")
            self.use_db.setChecked(False)
        self.use_db.setVisible(found); self.db_hint.setVisible(found)

    @property
    def database_on(self) -> bool:
        """Use the van database in the window that opens: found and ticked."""
        return not self.use_db.isHidden() and self.use_db.isChecked()
