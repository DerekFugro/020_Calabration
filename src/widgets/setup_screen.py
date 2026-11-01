"""setup_screen.py — Screen 1: folder, camera role + serial, board parameters.

Emits run_requested(folder, serial, BoardConfig) when the user clicks Run.
The BoardConfig is None when the Board list is on "Auto-detect"; the
candidates to choose from are then read via the `board_candidates` property.
Boards come from the Cal_board/<board>/board.yaml library (src/boards.py).
The camera role is read separately via the `camera_role` property (same
pattern as `min_blur_score`).

Settings are persisted via QSettings across sessions.  The role dropdown
remembers every role ever used AND the serial last used with each role, so the
operator only retypes a serial when the camera actually changes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.board import (
    BoardConfig,
    DEFAULT_CELL_HEIGHT_MM,
    DEFAULT_CELL_WIDTH_MM,
    DEFAULT_SQUARES_X,
    DEFAULT_SQUARES_Y,
)
from src.styles import BUTTON_H, INPUT_H, MARGIN, SPACING

# ── QSettings keys ───────────────────────────────────────────────────────────
_ORG = "SidewalkProfiler"
_APP = "Calibration"

_KEY_FOLDER       = "setup/folder"
_KEY_SERIAL       = "setup/serial"
_KEY_ROLE         = "setup/role"           # last role used
_KEY_ROLE_LIST    = "setup/role_list"      # JSON list of known roles
_KEY_ROLE_SERIALS = "setup/role_serials"   # JSON {role: serial}
_KEY_SQUARES_X    = "board/squares_x"
_KEY_SQUARES_Y    = "board/squares_y"
_KEY_CELL_W       = "board/cell_width_mm"
_KEY_CELL_H       = "board/cell_height_mm"
_KEY_MIN_BLUR     = "filter/min_blur_score"
_KEY_BOARD        = "board/selected"        # board name or AUTO_DETECT

AUTO_DETECT = "Auto-detect"

_DEFAULT_MIN_BLUR = 20.0

# Seed roles.  These are the two field cameras on the rig; the list grows as
# soon as anyone types a new role.  The actual serial for each is NOT seeded —
# hard-coding rig facts into the app is what the master doc forbids; the app
# learns the pairing the first time the operator enters it.
_SEED_ROLES = ["FORWARDLEFT", "FORWARDRIGHT", "ROW", "REARLEFT", "REARRIGHT", "PAVE", "BENCH"]


# ── QSettings JSON helpers ───────────────────────────────────────────────────

def _load_json_map(raw) -> dict[str, str]:
    """Parse a {role: serial} map from QSettings; {} if absent or corrupt."""
    import json
    try:
        data = json.loads(raw) if raw else {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (ValueError, TypeError, AttributeError):
        return {}


def _load_json_list(raw) -> list[str]:
    """Parse a role list from QSettings; [] if absent or corrupt."""
    import json
    try:
        data = json.loads(raw) if raw else []
        return [str(v) for v in data] if isinstance(data, list) else []
    except (ValueError, TypeError, AttributeError):
        return []


class SetupScreen(QWidget):
    """Screen 1 — folder + serial + board params + Run button."""

    run_requested = Signal(str, str, object)   # folder, serial, BoardConfig

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._create_widgets()
        self._create_layouts()
        self._connect_signals()
        self._apply_styles()
        self._load_initial_state()

    # ── Widget Construction ───────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        # Folder group
        self.folder_group   = QGroupBox("Image Folder")
        self.folder_input   = QLineEdit()
        self.folder_input.setPlaceholderText("Path to folder containing calibration images…")
        self.browse_button  = QPushButton("Browse…")
        self.browse_button.setFixedHeight(BUTTON_H)

        # Camera group
        self.camera_group   = QGroupBox("Camera")
        self.role_label     = QLabel("Role:")
        self.role_combo     = QComboBox()
        self.role_combo.setEditable(True)          # a new role can be typed once
        self.role_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.role_combo.setFixedHeight(INPUT_H)
        self.role_combo.lineEdit().setPlaceholderText("PAVE / ROW / BENCH…")
        self.role_hint      = QLabel(
            "Role + serial name the file in the calibration store. "
            "Picking a role fills in the serial you used last time."
        )
        self.serial_label   = QLabel("Serial Number:")
        self.serial_input   = QLineEdit()
        self.serial_input.setPlaceholderText("Required — e.g. SN001")
        self.serial_input.setFixedHeight(INPUT_H)

        # Board parameters group
        self.board_group        = QGroupBox("Board Parameters")
        self.board_label        = QLabel("Board:")
        self.board_combo        = QComboBox()
        self.board_combo.setFixedHeight(INPUT_H)
        self.board_hint         = QLabel("")
        self.squares_x_label    = QLabel("Squares X:")
        self.squares_x_spin     = QSpinBox()
        self.squares_y_label    = QLabel("Squares Y:")
        self.squares_y_spin     = QSpinBox()
        self.cell_width_label   = QLabel("Cell Width (mm):")
        self.cell_width_spin    = QDoubleSpinBox()
        self.cell_height_label  = QLabel("Cell Height (mm):")
        self.cell_height_spin   = QDoubleSpinBox()
        # No Marker Size input: detection is plain chessboard, so marker size
        # changes nothing.  Asking for it invited an unmeasured number into the
        # outputs (removed 2026-08-15).  BoardConfig keeps its default for the
        # board-printing helper.

        # Filter parameters group
        self.filter_group       = QGroupBox("Advanced: chessboard blur filter (dot boards skip it)")
        self.min_blur_label     = QLabel("Min Blur Score:")
        self.min_blur_spin      = QDoubleSpinBox()
        self.min_blur_hint      = QLabel("(lower = accept blurrier images; 0 = no blur check)")
        self.min_blur_spin.setRange(0.0, 5000.0)
        self.min_blur_spin.setDecimals(1)
        self.min_blur_spin.setSingleStep(5.0)
        self.min_blur_spin.setFixedHeight(INPUT_H)

        # SpinBox configuration (ranges only; values set in _load_initial_state)
        self.squares_x_spin.setRange(2, 50)
        self.squares_y_spin.setRange(2, 50)
        for spin in (self.cell_width_spin, self.cell_height_spin):
            spin.setRange(1.0, 500.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.1)
            spin.setFixedHeight(INPUT_H)

        # Run button
        self.run_button = QPushButton("Run Calibration")
        self.run_button.setObjectName("primary_button")
        self.run_button.setFixedHeight(BUTTON_H)
        self.run_button.setEnabled(False)

        # Status label
        self.status_label = QLabel("Select a folder and enter the camera serial number.")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    # ── Layout ────────────────────────────────────────────────────────────────
    def _create_layouts(self) -> None:
        # Folder group layout
        self.folder_layout = QHBoxLayout()
        self.folder_layout.setSpacing(SPACING)
        self.folder_layout.addWidget(self.folder_input)
        self.folder_layout.addWidget(self.browse_button)
        self.folder_group.setLayout(self.folder_layout)

        # Camera group layout
        self.camera_layout = QFormLayout()
        self.camera_layout.setSpacing(SPACING)
        self.camera_layout.addRow(self.role_label, self.role_combo)
        self.camera_layout.addRow(self.serial_label, self.serial_input)
        self.camera_layout.addRow(self.role_hint)
        self.camera_group.setLayout(self.camera_layout)

        # Board params layout
        self.board_layout = QGridLayout()
        self.board_layout.setSpacing(SPACING)
        self.board_layout.addWidget(self.board_label,       0, 0)
        self.board_layout.addWidget(self.board_combo,       0, 1, 1, 3)
        self.board_layout.addWidget(self.board_hint,        1, 0, 1, 5)
        self.board_layout.addWidget(self.squares_x_label,   2, 0)
        self.board_layout.addWidget(self.squares_x_spin,    2, 1)
        self.board_layout.addWidget(self.squares_y_label,   2, 2)
        self.board_layout.addWidget(self.squares_y_spin,    2, 3)
        self.board_layout.addWidget(self.cell_width_label,  3, 0)
        self.board_layout.addWidget(self.cell_width_spin,   3, 1)
        self.board_layout.addWidget(self.cell_height_label, 3, 2)
        self.board_layout.addWidget(self.cell_height_spin,  3, 3)
        self.board_layout.setColumnStretch(4, 1)   # absorb remaining space
        self.board_group.setLayout(self.board_layout)

        # Filter params layout
        self.filter_layout = QFormLayout()
        self.filter_layout.setSpacing(SPACING)
        self.filter_layout.addRow(self.min_blur_label, self.min_blur_spin)
        self.filter_layout.addRow(self.min_blur_hint)
        self.filter_group.setLayout(self.filter_layout)

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.main_layout.setSpacing(SPACING)
        self.main_layout.addWidget(self.folder_group)
        self.main_layout.addWidget(self.camera_group)
        self.main_layout.addWidget(self.board_group)
        self.main_layout.addWidget(self.filter_group)
        self.main_layout.addStretch()
        self.main_layout.addWidget(self.run_button)
        self.main_layout.addWidget(self.status_label)

    # ── Signals & Slots ───────────────────────────────────────────────────────
    def _connect_signals(self) -> None:
        self.browse_button.clicked.connect(self._on_browse_button_clicked)
        self.folder_input.textChanged.connect(self._on_inputs_changed)
        self.serial_input.textChanged.connect(self._on_inputs_changed)
        self.role_combo.currentTextChanged.connect(self._on_role_changed)
        self.board_combo.currentIndexChanged.connect(self._on_board_changed)
        self.run_button.clicked.connect(self._on_run_button_clicked)

    # ── Styling ───────────────────────────────────────────────────────────────
    def _apply_styles(self) -> None:
        self.status_label.setStyleSheet("color: rgb(140,140,140); font-size: 9pt;")
        self.role_hint.setStyleSheet("color: rgb(140,140,140); font-size: 8pt;")
        self.role_hint.setWordWrap(True)
        self.board_hint.setStyleSheet("color: rgb(140,140,140); font-size: 8pt;")
        self.board_hint.setWordWrap(True)

    # ── Initial State ─────────────────────────────────────────────────────────
    def _load_initial_state(self) -> None:
        from PySide6.QtCore import QSettings
        s = QSettings(_ORG, _APP)

        # Role memory: known roles, and the serial last used with each.
        self._role_serials = _load_json_map(s.value(_KEY_ROLE_SERIALS, ""))
        roles = _load_json_list(s.value(_KEY_ROLE_LIST, ""))
        for seed in _SEED_ROLES:
            if seed not in roles:
                roles.append(seed)
        self._loading = True                       # suppress role auto-fill
        self.role_combo.addItems(roles)
        last_role = str(s.value(_KEY_ROLE, "") or "")
        if last_role:
            idx = self.role_combo.findText(last_role)
            if idx >= 0:
                self.role_combo.setCurrentIndex(idx)
            else:
                self.role_combo.setCurrentText(last_role)
        self._loading = False

        self.folder_input.setText(s.value(_KEY_FOLDER, ""))
        self.serial_input.setText(s.value(_KEY_SERIAL, ""))
        self.squares_x_spin.setValue(int(s.value(_KEY_SQUARES_X, DEFAULT_SQUARES_X)))
        self.squares_y_spin.setValue(int(s.value(_KEY_SQUARES_Y, DEFAULT_SQUARES_Y)))
        self.cell_width_spin.setValue(float(s.value(_KEY_CELL_W, DEFAULT_CELL_WIDTH_MM)))
        self.cell_height_spin.setValue(float(s.value(_KEY_CELL_H, DEFAULT_CELL_HEIGHT_MM)))
        self.min_blur_spin.setValue(float(s.value(_KEY_MIN_BLUR, _DEFAULT_MIN_BLUR)))
        self._load_boards(str(s.value(_KEY_BOARD, AUTO_DETECT) or AUTO_DETECT))
        self._update_run_button()

    def _load_boards(self, selected: str = AUTO_DETECT) -> None:
        """Fill the Board list from the Cal_board library."""
        from src.boards import CAL_BOARD_DIR, list_boards
        errors: list[str] = []
        self._boards = list_boards(errors=errors)
        self.board_combo.blockSignals(True)
        self.board_combo.clear()
        self.board_combo.addItem(AUTO_DETECT)
        for b in self._boards:
            kind = "dots" if b.is_dots else "chessboard"
            self.board_combo.addItem(f"{b.name}  ({kind}, {b.num_corners} points)", b.name)
        idx = self.board_combo.findData(selected)
        self.board_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.board_combo.blockSignals(False)
        self._board_errors = errors
        self._library_dir = CAL_BOARD_DIR
        self._on_board_changed()

    def _selected_board(self):
        """The chosen library board, or None for Auto-detect."""
        name = self.board_combo.currentData()
        if not name:
            return None
        return next((b for b in self._boards if b.name == name), None)

    def _on_board_changed(self, *_args) -> None:
        b = self._selected_board()
        chess = b is None or not b.is_dots
        for w in (self.squares_x_spin, self.squares_y_spin,
                  self.cell_width_spin, self.cell_height_spin):
            w.setEnabled(chess)
        if b is None:
            text = ("The board is picked from sample images.  The squares and "
                    "cell size below are used if it is the chessboard.")
        elif b.is_dots:
            text = f"Dot layout: {b.layout_csv}"
        else:
            text = "Chessboard: set the squares and cell size below."
        text += f"  Library: {self._library_dir}"
        if self._board_errors:
            text += "  Skipped: " + "; ".join(self._board_errors)
        self.board_hint.setText(text)

    # ── Business Logic ────────────────────────────────────────────────────────
    def _on_browse_button_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Calibration Image Folder",
            self.folder_input.text() or "",
        )
        if folder:
            self.folder_input.setText(folder)

    def _on_role_changed(self, text: str) -> None:
        """Fill in the serial remembered for this role (blank if new)."""
        if getattr(self, "_loading", False):
            return
        from src.calibration_store import normalise_role
        role = normalise_role(text)
        remembered = self._role_serials.get(role, "")
        if remembered and remembered != self.serial_input.text().strip():
            self.serial_input.setText(remembered)
        self._update_run_button()

    def _on_inputs_changed(self) -> None:
        self._update_run_button()

    def _update_run_button(self) -> None:
        folder_ok = bool(self.folder_input.text().strip())
        serial_ok = bool(self.serial_input.text().strip())
        role_ok   = bool(self.camera_role)
        self.run_button.setEnabled(folder_ok and serial_ok and role_ok)
        if not role_ok:
            self.status_label.setText("Pick the camera role to enable Run.")
        elif not serial_ok:
            self.status_label.setText("Enter the camera serial number to enable Run.")
        elif not folder_ok:
            self.status_label.setText("Select an image folder to enable Run.")
        else:
            self.status_label.setText("Ready.  Click Run Calibration to begin.")

    def _on_run_button_clicked(self) -> None:
        folder = self.folder_input.text().strip()
        serial = self.serial_input.text().strip()
        board  = self._chessboard_from_spins()
        self._save_settings(folder, serial, board, self.camera_role)
        chosen = self._selected_board()
        if chosen is not None and not chosen.is_dots:
            chosen = self._chessboard_from_spins(chosen.name, chosen.folder)
        self.run_requested.emit(folder, serial, chosen)   # None = Auto-detect

    def _chessboard_from_spins(self, name: str = "", folder: str = "") -> BoardConfig:
        """The chessboard as set in the spin boxes."""
        b = BoardConfig(
            squares_x       = self.squares_x_spin.value(),
            squares_y       = self.squares_y_spin.value(),
            cell_width_mm   = self.cell_width_spin.value(),
            cell_height_mm  = self.cell_height_spin.value(),
        )
        if name:
            b.name = name
        b.folder = folder
        return b

    @property
    def board_candidates(self) -> list[BoardConfig]:
        """Boards Auto-detect chooses from (chessboards use the spin boxes)."""
        return [b if b.is_dots else self._chessboard_from_spins(b.name, b.folder)
                for b in self._boards]

    def _save_settings(
        self,
        folder: str,
        serial: str,
        board: BoardConfig,
        role: str = "",
    ) -> None:
        import json
        from PySide6.QtCore import QSettings
        s = QSettings(_ORG, _APP)

        if role:
            # Remember the role, and the serial that goes with it.
            self._role_serials[role] = serial
            roles = [self.role_combo.itemText(i)
                     for i in range(self.role_combo.count())]
            if role not in roles:
                roles.append(role)
                self.role_combo.addItem(role)
            s.setValue(_KEY_ROLE,         role)
            s.setValue(_KEY_ROLE_LIST,    json.dumps(roles))
            s.setValue(_KEY_ROLE_SERIALS, json.dumps(self._role_serials))

        s.setValue(_KEY_FOLDER,    folder)
        s.setValue(_KEY_SERIAL,    serial)
        s.setValue(_KEY_SQUARES_X, board.squares_x)
        s.setValue(_KEY_SQUARES_Y, board.squares_y)
        s.setValue(_KEY_CELL_W,    board.cell_width_mm)
        s.setValue(_KEY_CELL_H,    board.cell_height_mm)
        s.setValue(_KEY_MIN_BLUR,  self.min_blur_spin.value())
        s.setValue(_KEY_BOARD,     self.board_combo.currentData() or AUTO_DETECT)

    @property
    def camera_role(self) -> str:
        """Normalised camera role (e.g. 'PAVE'); '' if none chosen."""
        from src.calibration_store import normalise_role
        return normalise_role(self.role_combo.currentText())

    @property
    def min_blur_score(self) -> float:
        """Current blur threshold set by the user."""
        return self.min_blur_spin.value()

    def set_inputs(self, folder: str, role: str, serial: str) -> None:
        """Pre-fill from the van table (Load Intrinsic > Whole van)."""
        self.folder_input.setText(folder)
        if role:
            from src.calibration_store import normalise_role
            role = normalise_role(role)
            if self.role_combo.findText(role) < 0:
                self.role_combo.addItem(role)
            self.role_combo.setCurrentText(role)
        self.serial_input.setText(serial)
        self._update_run_button()

    def set_busy(self, busy: bool) -> None:
        """Called by MainWindow to lock/unlock the screen during a worker run."""
        self.run_button.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.folder_input.setReadOnly(busy)
        self.serial_input.setReadOnly(busy)
        self.role_combo.setEnabled(not busy)
        self.board_combo.setEnabled(not busy)
        self.min_blur_spin.setEnabled(not busy)
        if busy:
            self.status_label.setText("Detection in progress…")
