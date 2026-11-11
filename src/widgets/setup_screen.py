"""setup_screen.py — One camera, step 1: photo folder, Run.

Emits run_requested(folder, serial, board) — board is None for Auto-detect.
The camera and serial are picked in the bar on top (src/widgets/camera_bar.py, shared
with Load Extrinsic; Derek, 2026-11-10).  Unusable photos always go to NotUsed
(src/not_used.py).  The board list sits under Advanced: leave it on Auto-detect; boards
are added in the Boards tab.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from src.styles import BUTTON_H, INPUT_H, MARGIN, SPACING

_ORG, _APP = "SidewalkProfiler", "Calibration"
_KEY_FOLDER = "setup/folder"
_KEY_BOARD = "board/selected"          # board name or AUTO_DETECT

AUTO_DETECT = "Auto-detect"
class SetupScreen(QWidget):
    run_requested = Signal(str, str, object)   # folder, serial, BoardConfig | None

    def __init__(self, bar, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bar = bar                  # van, camera, serial (shared bar on top)
        self._boards, self._board_errors = [], []
        self._build()
        self._load_settings()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        dim = "color: rgb(140,140,140); font-size: 8pt;"

        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Folder with the board photos…")
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setFixedHeight(BUTTON_H)
        folder_group = QGroupBox("Photos")
        fl = QHBoxLayout(folder_group)
        fl.setSpacing(SPACING)
        fl.addWidget(self.folder_input); fl.addWidget(self.browse_button)

        self.board_combo = QComboBox()
        self.board_combo.setFixedHeight(INPUT_H)
        self.board_hint = QLabel("")
        self.board_hint.setStyleSheet(dim); self.board_hint.setWordWrap(True)
        notused = QLabel("Unusable photos (unreadable, no board, wrong size) are always moved to a "
                         "NotUsed folder; NotUsed\\why.txt lists each one.")
        notused.setStyleSheet(dim); notused.setWordWrap(True)
        adv = QGroupBox("Advanced (leave the board on Auto-detect; boards are added in the Boards tab)")
        al = QGridLayout(adv)
        al.setSpacing(SPACING)
        al.addWidget(QLabel("Board:"), 0, 0)
        al.addWidget(self.board_combo, 0, 1)
        al.addWidget(self.board_hint, 1, 0, 1, 2)
        al.addWidget(notused, 2, 0, 1, 2)
        al.setColumnStretch(1, 1)

        self.run_button = QPushButton("Run Calibration")
        self.run_button.setObjectName("primary_button")
        self.run_button.setFixedHeight(BUTTON_H)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: rgb(140,140,140); font-size: 9pt;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        lay.setSpacing(SPACING)
        hint = QLabel("Camera and serial: pick them in the bar at the top.  They name the result files.")
        hint.setStyleSheet(dim); hint.setWordWrap(True)
        lay.addWidget(folder_group); lay.addWidget(hint); lay.addWidget(adv)
        lay.addStretch()
        lay.addWidget(self.status_label)          # Run Calibration sits in the top bar row (2026-11-11)

        self.browse_button.clicked.connect(self._browse)
        self.folder_input.textChanged.connect(self._update_run_button)
        self.bar.changed.connect(self._update_run_button)
        self.board_combo.currentIndexChanged.connect(self._on_board_changed)
        self.run_button.clicked.connect(self._run)

    def _load_settings(self) -> None:
        s = QSettings(_ORG, _APP)
        self.folder_input.setText(str(s.value(_KEY_FOLDER, "") or ""))
        self._load_boards(str(s.value(_KEY_BOARD, AUTO_DETECT) or AUTO_DETECT))
        self._update_run_button()

    # ── Boards ────────────────────────────────────────────────────────────────
    def _load_boards(self, selected: str = AUTO_DETECT) -> None:
        from src.boards import CAL_BOARD_DIR, list_boards
        errors: list[str] = []
        self._boards = list_boards(errors=errors)
        self._board_errors = errors
        self._library_dir = CAL_BOARD_DIR
        self.board_combo.blockSignals(True)
        self.board_combo.clear()
        self.board_combo.addItem(AUTO_DETECT)
        for b in self._boards:
            kind = "dots" if b.is_dots else "chessboard"
            self.board_combo.addItem(f"{b.name}  ({kind}, {b.num_corners} points)", b.name)
        idx = self.board_combo.findData(selected)
        self.board_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.board_combo.blockSignals(False)
        self._on_board_changed()

    def reload_boards(self) -> None:
        """The Boards tab added or re-measured a board."""
        self._load_boards(self.board_combo.currentData() or AUTO_DETECT)

    def _selected_board(self):
        name = self.board_combo.currentData()
        return next((b for b in self._boards if b.name == name), None) if name else None

    def _on_board_changed(self, *_args) -> None:
        b = self._selected_board()
        if b is None:
            text = "Auto-detect picks the board from a few photos"
        elif b.is_dots:
            text = f"{b.num_corners} dots, layout {Path(b.layout_csv).name}"
        else:
            text = (f"Chessboard {b.squares_x}x{b.squares_y}, cell {b.cell_width_mm:.2f} x "
                    f"{b.cell_height_mm:.2f} mm")
        text += f".  Library: {self._library_dir}"
        if self._board_errors:
            text += "  Skipped: " + "; ".join(self._board_errors)
        self.board_hint.setText(text)

    # ── Run ───────────────────────────────────────────────────────────────────
    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder with the board photos",
                                                  self.folder_input.text() or "")
        if folder:
            self.folder_input.setText(folder)

    def _update_run_button(self, *_args) -> None:
        folder = self.folder_input.text().strip()
        missing = ("Pick the camera at the top" if not self.bar.camera_role else
                   "Type the camera serial at the top" if not self.bar.serial else
                   "Pick the photo folder" if not folder else "")
        self.run_button.setEnabled(not missing)
        if missing:
            self.status_label.setText(missing + " to enable Run.")
            return
        from src.previous_runs import find_previous
        prev = find_previous(folder)
        self.status_label.setText(
            f"Already calibrated: {prev[0].text()}.  Run lets you open it or process again."
            if prev else "Ready.  Click Run Calibration to begin.")

    def _run(self) -> None:
        folder = self.folder_input.text().strip()
        s = QSettings(_ORG, _APP)
        self.bar.remember_role()
        s.setValue(_KEY_FOLDER, folder)
        s.setValue(_KEY_BOARD, self.board_combo.currentData() or AUTO_DETECT)
        self.run_requested.emit(folder, self.bar.serial, self._selected_board())

    # ── Used by the One camera screen ─────────────────────────────────────────
    @property
    def serial_from(self) -> str:
        return self.bar.serial_from

    @property
    def camera_role(self) -> str:
        """Normalised camera role (e.g. 'ROW'); '' if none chosen (from the bar on top)."""
        return self.bar.camera_role

    def clear_folder(self) -> None:
        """New camera: no photo folder from the last one."""
        self.folder_input.clear()

    def set_busy(self, busy: bool) -> None:
        for w in (self.run_button, self.browse_button, self.board_combo):
            w.setEnabled(not busy)
        self.folder_input.setReadOnly(busy)
        self.bar.set_busy(busy)
        if busy:
            self.status_label.setText("Working…")
        else:
            self._update_run_button()
