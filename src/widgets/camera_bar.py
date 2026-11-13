"""camera_bar.py - the bar on top of every tab: van, camera, serial (Derek, 2026-11-10).

One camera at a time, end to end: the camera and serial picked here are used by Load
Intrinsic and Load Extrinsic, so the lens made on one tab is used by the other without
loading it twice.  Changing the camera clears both tabs (camera_changed).

Van: from the PC name (ARAN69-SERVER -> ARAN69), can be corrected.  The van's ARAN
database (src/camera_db.py, Windows sign-in, read only) is looked up in the background:
  * it answered -> the camera list is the van's enabled cameras only (pick, no typing),
    and picking one fills in its serial, locked; Edit unlocks it for a camera whose label
    disagrees (still flagged, and logged as typed);
  * no answer -> the usual camera list, and the serial is typed.
"""

from __future__ import annotations

import html as _h
import json
import re

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from src.styles import INPUT_H, SPACING

_ORG, _APP = "SidewalkProfiler", "Calibration"
_KEY_ROLE_LIST = "setup/role_list"     # JSON list of camera names ever typed
_SEED_ROLES = ["FORWARDLEFT", "FORWARDRIGHT", "ROW", "LEFT", "RIGHT", "REARLEFT", "REARRIGHT",
               "PAVE", "BENCH"]
_DIM = "color: rgb(150,150,150); font-size: 8pt;"


def _load_json_list(raw) -> list[str]:
    try:
        data = json.loads(raw) if raw else []
        return [str(v) for v in data] if isinstance(data, list) else []
    except (ValueError, TypeError, AttributeError):
        return []


class CameraBar(QWidget):
    camera_changed = Signal(str)       # the camera really changed: both tabs start over
    changed = Signal()                 # camera or serial text changed (Run / Solve buttons)
    van_changed = Signal(str)

    def __init__(self, parent=None, use_db: bool = True) -> None:
        super().__init__(parent)
        self.use_db = use_db            # start screen: "Use the van database" (2026-11-13)
        self.db_res = None              # camera_db.DbResult for the van, or None
        self._db_worker = None
        self._db_serial = ""            # serial the database gave for the chosen camera
        self._db_names: list[str] = []  # the van's enabled cameras, when the database answered
        self._unlocked = False          # Edit pressed for this camera
        self._last_cam = ""

        self.van_edit = QLineEdit(); self.van_edit.setPlaceholderText("e.g. ARAN69")
        self.van_edit.setFixedWidth(110); self.van_edit.setFixedHeight(INPUT_H)     # never squeezed by the buttons
        self.role_combo = QComboBox(); self.role_combo.setFixedHeight(INPUT_H); self.role_combo.setMinimumWidth(170)
        self.serial_input = QLineEdit(); self.serial_input.setFixedHeight(INPUT_H)
        self.serial_input.setPlaceholderText("From the camera label"); self.serial_input.setFixedWidth(150)
        self.serial_edit = QPushButton("Edit"); self.serial_edit.setFixedHeight(INPUT_H)
        self.serial_edit.setToolTip("The serial came from the van database.  Edit only if the camera label says otherwise.")
        self.serial_edit.hide()
        self.db_label = QLabel(""); self.db_label.setWordWrap(True); self.db_label.setStyleSheet(_DIM)
        self.db_label.setTextFormat(Qt.TextFormat.RichText)

        row = QHBoxLayout(); row.setSpacing(SPACING); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Van:")); row.addWidget(self.van_edit); row.addSpacing(SPACING)
        row.addWidget(QLabel("Camera:")); row.addWidget(self.role_combo); row.addSpacing(SPACING)
        row.addWidget(QLabel("Serial:")); row.addWidget(self.serial_input); row.addWidget(self.serial_edit)
        row.addStretch(1)
        self._row = row                 # set_actions(): the open tab's buttons go on the right
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(2)
        lay.addLayout(row); lay.addWidget(self.db_label)

        self._fill_usual()
        self.van_edit.textChanged.connect(self._van_typed)
        self.role_combo.currentTextChanged.connect(self._camera_picked)
        self.serial_input.textChanged.connect(lambda _t: self.changed.emit())
        self.serial_input.textEdited.connect(lambda _t: self._apply())
        self.serial_edit.clicked.connect(self._unlock_serial)

    # ── what the tabs read ───────────────────────────────────────────────────
    @property
    def van(self) -> str:
        return self.van_edit.text().strip()

    @property
    def camera_role(self) -> str:
        """Camera name for file names (e.g. 'ROW', 'FORWARDLEFT'); '' if none picked."""
        cleaned = re.sub(r"[\s_]+", "-", self.role_combo.currentText().strip()).upper()
        return re.sub(r"-{2,}", "-", cleaned).strip("-")

    @property
    def camera(self) -> str:
        """Camera in the app's own names (ROW, ForwardLeft, ...); '' if none picked."""
        from src.van_scan import camera_from_name
        return camera_from_name(self.camera_role) or self.camera_role

    @property
    def serial(self) -> str:
        return self.serial_input.text().strip()

    @property
    def serial_from(self) -> str:
        typed = self.serial
        if self._db_serial and typed == self._db_serial:
            return "van database"
        return "typed" + (f" (van database says {self._db_serial})" if self._db_serial else "")

    def remember_role(self) -> None:
        """A typed camera name joins the usual list (not the database's names)."""
        role = self.camera_role
        if self._db_names or not role:
            return
        roles = [self.role_combo.itemText(i) for i in range(self.role_combo.count())]
        if role not in roles:
            roles.append(role); self.role_combo.addItem(role)
        QSettings(_ORG, _APP).setValue(_KEY_ROLE_LIST, json.dumps(roles))

    def set_busy(self, busy: bool) -> None:
        """While a calibration runs, the camera can't change under it."""
        self.van_edit.setReadOnly(busy)
        self.role_combo.setEnabled(not busy)
        if busy:
            self.serial_input.setReadOnly(True); self.serial_edit.setEnabled(False)
        else:
            self._lock_serial(bool(self._db_serial) and not self._unlocked)

    def set_actions(self, widgets: list) -> None:
        """Buttons for the tab on show, on the right of the row (only that tab's are visible)."""
        for w in widgets:
            if w.parent() is not self:
                self._row.addWidget(w)

        # ── van and its database ────────────────────────────────────────────────
    def _van_typed(self, text: str) -> None:
        self.van_changed.emit(text.strip())
        self.db_res = None
        self.set_db_cameras(None)
        self.apply_db(None, "")
        van = text.strip()
        if not self.use_db:
            self.db_label.setStyleSheet(_DIM)
            self.db_label.setText("Van database: off (chosen on the start screen). Pick the camera; type the serial.")
            return
        if not van:
            return
        from src.widgets.db_worker import DbWorker
        self._db_worker = DbWorker(van, self)
        self._db_worker.done.connect(self._db_done)
        self._db_worker.start()
        self.db_label.setStyleSheet(_DIM)
        self.db_label.setText(f"Looking up {_h.escape(van)}'s cameras in the van database...")

    def _db_done(self, van, res) -> None:
        if van != self.van:
            return                       # the van changed while looking
        self.db_res = res
        self.set_db_cameras(res)
        self._apply()

    # ── camera ───────────────────────────────────────────────────────────────
    def _usual_roles(self) -> list[str]:
        roles = _load_json_list(QSettings(_ORG, _APP).value(_KEY_ROLE_LIST, ""))
        return roles + [r for r in _SEED_ROLES if r not in roles]

    def _fill_usual(self) -> None:
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        self.role_combo.setEditable(True)
        self.role_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.role_combo.addItems(self._usual_roles())
        self.role_combo.setCurrentIndex(-1)
        self.role_combo.setEditText("")
        self.role_combo.lineEdit().setPlaceholderText("Pick the camera...")
        self.role_combo.blockSignals(False)

    def set_db_cameras(self, res) -> None:
        """Camera list: the van's enabled cameras when the database answered, else the usual list."""
        names = res.names() if (res is not None and not res.error) else []
        if names == self._db_names:
            return
        current = self.role_combo.currentText()
        self._db_names = names
        if not names:
            self._fill_usual()
        else:
            self.role_combo.blockSignals(True)
            self.role_combo.clear()
            self.role_combo.setEditable(False)          # database list: pick only, no typing
            self.role_combo.addItems(names)
            self.role_combo.setPlaceholderText("Pick the camera...")
            self.role_combo.setCurrentIndex(-1)
            self.role_combo.blockSignals(False)
        i = self.role_combo.findText(current, Qt.MatchFlag.MatchFixedString) if current else -1
        if i >= 0:
            self.role_combo.setCurrentIndex(i)
        self._camera_picked(self.role_combo.currentText())

    def _camera_picked(self, _text: str) -> None:
        cam = self.camera
        if cam != self._last_cam:
            self._last_cam = cam
            self._unlocked = False
            self.camera_changed.emit(cam)
        self._apply()
        self.changed.emit()

    # ── serial ───────────────────────────────────────────────────────────────
    def _lock_serial(self, locked: bool) -> None:
        self.serial_input.setReadOnly(locked)
        self.serial_input.setStyleSheet("color: rgb(170,170,170);" if locked else "")
        self.serial_edit.setVisible(bool(self._db_serial))
        self.serial_edit.setEnabled(locked)

    def _unlock_serial(self) -> None:
        self._unlocked = True
        self._lock_serial(False)
        self.serial_input.setFocus(); self.serial_input.selectAll()

    def _apply(self) -> None:
        self.apply_db(self.db_res, self.camera)

    def apply_db(self, res, camera: str) -> None:
        """Fill the serial from the van database and lock it (Edit unlocks it), and say where
        it came from, or why it could not."""
        row = res.find(camera) if (res is not None and camera) else None
        typed = self.serial
        if res is None:
            self._db_serial = ""; self._lock_serial(False)
            if (self.db_label.text().startswith("Looking up") and self.van) or not self.use_db:
                return
            self.db_label.setText(""); return
        if row is None:
            if self._db_serial and typed == self._db_serial:
                self.serial_input.clear()             # the last camera's serial must not stay
            self._db_serial = ""
            self._lock_serial(False)
            self.db_label.setStyleSheet(_DIM)
            if res.error:
                self.db_label.setText(_h.escape(res.error))
            elif camera:
                self.db_label.setText(f"{_h.escape(camera)} is not in the van {_h.escape(res.where)} "
                                      f"(it lists {_h.escape(', '.join(res.names()))}). Type the serial.")
            else:
                self.db_label.setText(f"Van {_h.escape(res.where)}: pick the camera.")
            return
        if not self._unlocked or not typed or typed == self._db_serial:
            self.serial_input.setText(row.serial); typed = row.serial
        self._db_serial = row.serial
        self._lock_serial(not self._unlocked)
        size = f", photos {row.width} x {row.height}" if row.width else ""
        if typed == row.serial:
            self.db_label.setText(f"&#10003; Serial from the van {_h.escape(res.where)}{size}.")
            self.db_label.setStyleSheet("color: rgb(60,200,60); font-size: 8pt;")
        else:
            self.db_label.setText(f"&#9888; You typed {_h.escape(typed)}, but the van {_h.escape(res.where)} says "
                                  f"{_h.escape(row.serial)} for {_h.escape(row.camera)}{size}. Check the camera label.")
            self.db_label.setStyleSheet("color: rgb(230,180,40); font-size: 8pt;")
