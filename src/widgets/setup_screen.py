"""setup_screen.py — One camera, step 1: photo folder, camera, serial, Run.

Emits run_requested(folder, serial, board) — board is None for Auto-detect.
The camera and serial start blank every time, so last session's camera can't
slip onto new photos (Derek, 2026-11-01).  Unusable photos always go to
NotUsed (src/not_used.py).  The board list sits under Advanced: leave it on
Auto-detect; boards are added in the Boards tab.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from src.styles import BUTTON_H, INPUT_H, MARGIN, SPACING

_ORG, _APP = "SidewalkProfiler", "Calibration"
_KEY_FOLDER = "setup/folder"
_KEY_ROLE_LIST = "setup/role_list"     # JSON list of roles ever typed
_KEY_BOARD = "board/selected"          # board name or AUTO_DETECT

AUTO_DETECT = "Auto-detect"
_SEED_ROLES = ["FORWARDLEFT", "FORWARDRIGHT", "ROW", "LEFT", "RIGHT", "REARLEFT", "REARRIGHT",
               "PAVE", "BENCH"]


def _load_json_list(raw) -> list[str]:
    try:
        data = json.loads(raw) if raw else []
        return [str(v) for v in data] if isinstance(data, list) else []
    except (ValueError, TypeError, AttributeError):
        return []


class SetupScreen(QWidget):
    run_requested = Signal(str, str, object)   # folder, serial, BoardConfig | None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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

        self.role_combo = QComboBox()
        self.role_combo.setEditable(True)
        self.role_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.role_combo.setFixedHeight(INPUT_H)
        self.serial_input = QLineEdit()
        self.serial_input.setPlaceholderText("Required — from the camera label")
        self.serial_input.setFixedHeight(INPUT_H)
        hint = QLabel("Fill in both every time.  Camera + serial name the result files.")
        hint.setStyleSheet(dim); hint.setWordWrap(True)
        camera_group = QGroupBox("Camera")
        cl = QFormLayout(camera_group)
        cl.setSpacing(SPACING)
        cl.addRow("Camera:", self.role_combo)
        cl.addRow("Serial number:", self.serial_input)
        cl.addRow(hint)

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
        lay.addWidget(folder_group); lay.addWidget(camera_group); lay.addWidget(adv)
        lay.addStretch()
        lay.addWidget(self.run_button); lay.addWidget(self.status_label)

        self.browse_button.clicked.connect(self._browse)
        self.folder_input.textChanged.connect(self._update_run_button)
        self.serial_input.textChanged.connect(self._update_run_button)
        self.role_combo.currentTextChanged.connect(self._update_run_button)
        self.board_combo.currentIndexChanged.connect(self._on_board_changed)
        self.run_button.clicked.connect(self._run)

    def _load_settings(self) -> None:
        s = QSettings(_ORG, _APP)
        roles = _load_json_list(s.value(_KEY_ROLE_LIST, ""))
        roles += [r for r in _SEED_ROLES if r not in roles]
        self.role_combo.addItems(roles)
        self.role_combo.setCurrentIndex(-1)            # blank: the user picks it
        self.role_combo.setEditText("")
        self.role_combo.lineEdit().setPlaceholderText("Pick the camera…")
        self.serial_input.clear()                     # blank: the user types it
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
        missing = ("Pick the camera" if not self.camera_role else
                   "Type the camera serial number" if not self.serial_input.text().strip() else
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
        role = self.camera_role
        s = QSettings(_ORG, _APP)
        roles = [self.role_combo.itemText(i) for i in range(self.role_combo.count())]
        if role not in roles:
            roles.append(role); self.role_combo.addItem(role)
        s.setValue(_KEY_ROLE_LIST, json.dumps(roles))
        s.setValue(_KEY_FOLDER, folder)
        s.setValue(_KEY_BOARD, self.board_combo.currentData() or AUTO_DETECT)
        self.run_requested.emit(folder, self.serial_input.text().strip(), self._selected_board())

    # ── Used by the One camera screen ─────────────────────────────────────────
    @property
    def camera_role(self) -> str:
        """Normalised camera role (e.g. 'ROW'); '' if none chosen."""
        import re
        cleaned = re.sub(r"[\s_]+", "-", self.role_combo.currentText().strip()).upper()
        return re.sub(r"-{2,}", "-", cleaned).strip("-")

    def set_busy(self, busy: bool) -> None:
        for w in (self.run_button, self.browse_button, self.role_combo, self.board_combo):
            w.setEnabled(not busy)
        self.folder_input.setReadOnly(busy)
        self.serial_input.setReadOnly(busy)
        if busy:
            self.status_label.setText("Working…")
        else:
            self._update_run_button()
