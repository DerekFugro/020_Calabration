"""window.py - CaptureWindow: pick a camera, see it live, grab full-size board photos.

Layout (docs/capture/Capture_Instructions.md):
  top     Van, Use the van database, Camera list, where the list came from, Try again
          (Windows inputs only: which camera it is, its serial, its size)
  centre  live preview, never stretched; camera, port, serial, expected / delivered size, fps
  bottom  folder, photo count, Grab, Countdown, last photos, Open in calibration app, Advanced...
  status  plain words
Read only towards ARAN: opens, reads and closes one input; changes no settings.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QKeySequenceEdit, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from src.capture import cameras as cam_list
from src.capture import sizes
from src.capture.capture_log import CaptureLog
from src.styles import BUTTON_H, INPUT_H, MARGIN, SPACING, STYLESHEET_MAIN

ORG, APP = "SidewalkProfiler", "SurveyorCapture"
CAMERA_NAMES = ["ROW", "ForwardLeft", "ForwardRight", "Left", "Right", "RearLeft", "RearRight", "PAVE"]
SIZES = ["3840 x 2160", "1920 x 1080", "2880 x 1860", "2448 x 2048"]
DIM = "color: rgb(150,150,150);"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


class _ListWorker(QThread):
    """The camera list from the van database, without freezing the window."""
    done = Signal(object, str)

    def __init__(self, van: str, names, parent=None) -> None:
        super().__init__(parent)
        self.van, self.names = van, names

    def run(self) -> None:
        try:
            cams, msg = cam_list.from_database(self.van, self.names)
        except Exception as exc:  # noqa: BLE001
            cams, msg = [], f"Could not read the van database: {exc}"
        self.done.emit(cams, msg)


class AdvancedDialog(QDialog):
    def __init__(self, quality: int, countdown_s: int, grab_key: str, parent=None) -> None:
        super().__init__(parent)
        self._values = (quality, countdown_s, grab_key)
        self._create_widgets()
        self._create_layouts()
        self._connect_signals()
        self._apply_styles()
        self._load_initial_state()

    def _create_widgets(self) -> None:
        self.setWindowTitle("Advanced")
        self.quality = QSpinBox(); self.quality.setRange(80, 100)
        self.countdown = QSpinBox(); self.countdown.setRange(1, 10); self.countdown.setSuffix(" s")
        self.key = QKeySequenceEdit()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)

    def _create_layouts(self) -> None:
        f = QFormLayout(self)
        f.addRow("JPEG quality:", self.quality)
        f.addRow("Countdown:", self.countdown)
        f.addRow("Grab key:", self.key)
        f.addRow(self.buttons)

    def _connect_signals(self) -> None:
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def _apply_styles(self) -> None:
        self.setStyleSheet(STYLESHEET_MAIN)

    def _load_initial_state(self) -> None:
        q, c, k = self._values
        self.quality.setValue(q); self.countdown.setValue(c); self.key.setKeySequence(QKeySequence(k))

    def values(self) -> tuple[int, int, str]:
        return self.quality.value(), self.countdown.value(), self.key.keySequence().toString() or "Space"


class CaptureWindow(QMainWindow):
    """source_factory(camera, index) -> FrameSource and names (the Windows inputs) can be given
    for tests and PCs without a card; otherwise the real DirectShow inputs are used."""

    def __init__(self, van: str = "", camera: str = "", folder: str = "", use_db: bool = True,
                 source_factory=None, names: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._args = (van, camera, folder, use_db)
        self._factory, self._names = source_factory, names
        self._cams: list = []
        self._cam = None
        self._worker = None
        self._list_worker = None
        self._log = None
        self._delivered = None
        self._count = 0
        self._countdown_left = 0
        self._busy_saving = False
        self._closing = False          # a closing window never (re)opens a camera
        self._listed_for = None        # (van, database on) the camera list was made for
        self._create_widgets()
        self._create_layouts()
        self._connect_signals()
        self._apply_styles()
        self._load_initial_state()

    # ── widgets ──────────────────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        from src.version import app_version
        self.setWindowTitle(f"SurveyorCapture   {app_version()}")
        self.van_edit = QLineEdit(); self.van_edit.setFixedWidth(110); self.van_edit.setPlaceholderText("e.g. ARAN69")
        self.use_db = QCheckBox("Use the van database")
        self.camera_combo = QComboBox(); self.camera_combo.setMinimumWidth(380)
        self.list_label = QLabel("")
        self.list_label.setWordWrap(True)          # a long "could not read the database" must not widen the window
        self.try_btn = QPushButton("Try again")
        # Windows inputs only: the crew says which camera, its serial and size
        self.name_combo = QComboBox(); self.name_combo.setEditable(True); self.name_combo.addItems(CAMERA_NAMES)
        self.name_combo.setCurrentIndex(-1); self.name_combo.setPlaceholderText("Which camera?")
        self.serial_edit = QLineEdit(); self.serial_edit.setPlaceholderText("Serial (camera label)"); self.serial_edit.setFixedWidth(160)
        self.size_combo = QComboBox(); self.size_combo.addItems(SIZES); self.size_combo.setCurrentIndex(-1)
        self.size_combo.setPlaceholderText("Camera size?")
        self.user_row = QWidget()
        self.preview = QLabel("No camera yet"); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(QSize(480, 270))
        self.overlay = QLabel("", self.preview); self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter); self.overlay.hide()
        self.info = QLabel("")
        self.folder_edit = QLineEdit(); self.folder_edit.setPlaceholderText("Folder for the photos")
        self.browse_btn = QPushButton("Browse...")
        self.count_label = QLabel("0 photos")
        self.grab_btn = QPushButton("Grab")
        self.countdown_btn = QPushButton("Countdown")
        self.thumbs = QWidget()
        self.thumbs_scroll = QScrollArea()
        self.open_cal_btn = QPushButton("Open in calibration app")
        self.advanced_btn = QPushButton("Advanced...")
        self.status = QLabel("")

    def _create_layouts(self) -> None:
        top = QHBoxLayout(); top.setSpacing(SPACING)
        top.addWidget(QLabel("Van:")); top.addWidget(self.van_edit); top.addWidget(self.use_db)
        top.addSpacing(SPACING); top.addWidget(QLabel("Camera:")); top.addWidget(self.camera_combo, 1)
        top.addWidget(self.try_btn)
        ur = QHBoxLayout(self.user_row); ur.setContentsMargins(0, 0, 0, 0); ur.setSpacing(SPACING)
        ur.addWidget(QLabel("This input is camera:")); ur.addWidget(self.name_combo)
        ur.addWidget(QLabel("Serial:")); ur.addWidget(self.serial_edit)
        ur.addWidget(QLabel("Size:")); ur.addWidget(self.size_combo); ur.addStretch(1)
        tl = QHBoxLayout(self.thumbs); tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(6); tl.addStretch(1)
        self._thumb_layout = tl
        self.thumbs_scroll.setWidget(self.thumbs); self.thumbs_scroll.setWidgetResizable(True)
        self.thumbs_scroll.setFixedHeight(112); self.thumbs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        fold = QHBoxLayout(); fold.setSpacing(SPACING)
        fold.addWidget(QLabel("Photos go to:")); fold.addWidget(self.folder_edit, 1); fold.addWidget(self.browse_btn)
        fold.addWidget(self.count_label)
        acts = QHBoxLayout(); acts.setSpacing(SPACING)
        acts.addWidget(self.grab_btn, 2); acts.addWidget(self.countdown_btn, 1)
        acts.addWidget(self.open_cal_btn); acts.addWidget(self.advanced_btn)
        central = QWidget()
        lay = QVBoxLayout(central); lay.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN); lay.setSpacing(SPACING)
        lay.addLayout(top); lay.addWidget(self.list_label); lay.addWidget(self.user_row)
        lay.addWidget(self.preview, 1); lay.addWidget(self.info)
        lay.addLayout(fold); lay.addLayout(acts); lay.addWidget(self.thumbs_scroll); lay.addWidget(self.status)
        self.setCentralWidget(central)

    def _connect_signals(self) -> None:
        self.van_edit.editingFinished.connect(self._refresh_cameras)
        self.use_db.toggled.connect(lambda _on: self._refresh_cameras())
        self.camera_combo.currentIndexChanged.connect(lambda _i: self._camera_chosen())
        self.try_btn.clicked.connect(self._start_camera)
        self.size_combo.currentIndexChanged.connect(lambda _i: self._start_camera())
        self.name_combo.currentTextChanged.connect(lambda _t: self._sync_buttons())
        self.serial_edit.textChanged.connect(lambda _t: self._sync_buttons())
        self.browse_btn.clicked.connect(self._browse)
        self.folder_edit.textChanged.connect(lambda _t: self._folder_changed())
        self.grab_btn.clicked.connect(lambda: self._grab(False))
        self.countdown_btn.clicked.connect(self._start_countdown)
        self.open_cal_btn.clicked.connect(self._open_calibration)
        self.advanced_btn.clicked.connect(self._advanced)
        self._tick = QTimer(self); self._tick.setInterval(1000); self._tick.timeout.connect(self._countdown_step)

    def _apply_styles(self) -> None:
        self.setStyleSheet(STYLESHEET_MAIN)
        for b in (self.try_btn, self.browse_btn, self.open_cal_btn, self.advanced_btn):
            b.setFixedHeight(BUTTON_H)
        for w in (self.van_edit, self.camera_combo, self.folder_edit, self.serial_edit, self.name_combo, self.size_combo):
            w.setFixedHeight(INPUT_H)
        self.grab_btn.setObjectName("primary_button"); self.grab_btn.setMinimumHeight(56)
        self.countdown_btn.setMinimumHeight(56)
        self.grab_btn.setStyleSheet("font-size: 16pt; font-weight: bold;")
        self.countdown_btn.setStyleSheet("font-size: 13pt;")
        self.preview.setStyleSheet("background: black; color: rgb(150,150,150); font-size: 14pt;")
        self.overlay.setStyleSheet("color: white; font-size: 120pt; font-weight: bold; background: rgba(0,0,0,90);")
        self.list_label.setStyleSheet(DIM); self.info.setStyleSheet(DIM)
        self.count_label.setStyleSheet("font-weight: bold;")
        self.resize(1280, 720)

    def _load_initial_state(self) -> None:
        van, camera, folder, use_db = self._args
        s = QSettings(ORG, APP)
        self._quality = int(s.value("jpeg_quality", 95))
        self._countdown_s = int(s.value("countdown_s", 3))
        self._grab_key = str(s.value("grab_key", "Space"))
        self._shortcut = QShortcut(QKeySequence(self._grab_key), self)
        self._shortcut.activated.connect(lambda: self._grab(False))
        if not van:
            from src.van_scan import van_from_computer
            van = van_from_computer() if use_db else ""
        self.van_edit.setText(van)
        self.folder_edit.setText(folder or str(s.value("folder", "") or ""))
        self._want_camera = camera
        self.use_db.blockSignals(True); self.use_db.setChecked(use_db); self.use_db.blockSignals(False)
        self.user_row.hide()
        self._sync_buttons()
        self._refresh_cameras()

    # ── the camera list ──────────────────────────────────────────────────────
    def _inputs(self) -> list[str]:
        if self._names is None:
            from src.capture.dshow_names import video_inputs
            self._names = video_inputs()
        return self._names

    def _refresh_cameras(self) -> None:
        van = self.van_edit.text().strip().upper()
        key = (van, self.use_db.isChecked())
        if self._closing or key == self._listed_for:
            return                     # e.g. focus leaving the van box on close: nothing changed
        self._listed_for = key
        self._stop_camera()
        names = self._inputs()
        if self.use_db.isChecked() and van:
            self.list_label.setText(f"Looking up {van}'s cameras in the van database...")
            self._list_worker = _ListWorker(van, names, self)
            self._list_worker.done.connect(self._db_list_done)
            self._list_worker.start()
        else:
            self._populate_camera_list(cam_list.from_ports(names), "Cameras: the inputs Windows reports. "
                                       "Say which camera each one is, and type its serial.")

    def _db_list_done(self, cams, msg) -> None:
        if self._closing:
            return
        if cams:
            self._populate_camera_list(cams, f"Cameras: from the van database ({self.van_edit.text().strip().upper()}).")
        else:
            self._populate_camera_list(cam_list.from_ports(self._inputs()),
                                       f"{msg}  Using the inputs Windows reports instead.")

    def _create_camera_item(self, cam) -> None:
        """One entry in the camera list (greyed out when Capture can't use it)."""
        text = cam.label if cam.supported else f"{cam.name}  -  {cam.why}"
        self.camera_combo.addItem(text)
        if not cam.supported:
            item = self.camera_combo.model().item(self.camera_combo.count() - 1)
            item.setEnabled(False)

    def _clear_camera_list(self) -> None:
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        self.camera_combo.blockSignals(False)

    def _populate_camera_list(self, cams, where: str) -> None:
        self._clear_camera_list()
        self._cams = list(cams)
        self.camera_combo.blockSignals(True)
        for c in self._cams:
            self._create_camera_item(c)
        self.camera_combo.setPlaceholderText("Pick the camera..." if self._cams else "No cameras found")
        pick = -1
        if self._want_camera:
            pick = next((i for i, c in enumerate(self._cams) if c.supported and
                         c.name.lower() == self._want_camera.lower()), -1)
        self.camera_combo.setCurrentIndex(pick)
        self.camera_combo.blockSignals(False)
        self.list_label.setText(where)
        self._camera_chosen()

    # ── one camera ───────────────────────────────────────────────────────────
    def _camera_chosen(self) -> None:
        self._stop_camera()
        i = self.camera_combo.currentIndex()
        self._cam = self._cams[i] if 0 <= i < len(self._cams) else None
        self._log, self._delivered = None, None
        self._clear_thumbnails(); self._count = 0; self.count_label.setText("0 photos")
        user = self._cam is not None and self._cam.source == "user"
        self.user_row.setVisible(user)
        if user:
            self.size_combo.blockSignals(True); self.size_combo.setCurrentIndex(-1); self.size_combo.blockSignals(False)
        self.preview.setPixmap(QPixmap()); self.preview.setText("No camera yet" if self._cam is None else "Opening...")
        self._start_camera()

    def _expected(self):
        if self._cam is None:
            return None
        e = sizes.expected_size(self._cam)
        if e is None and self.size_combo.currentIndex() >= 0:
            w, h = self.size_combo.currentText().split(" x ")
            e = (int(w), int(h))
        return e

    def camera_name(self) -> str:
        if self._cam is None:
            return ""
        return self._cam.name or self.name_combo.currentText().strip()

    def serial(self) -> str:
        if self._cam is None:
            return ""
        return self._cam.serial if self._cam.source == "database" else self.serial_edit.text().strip()

    def _start_camera(self) -> None:
        self._stop_camera()
        if self._closing:
            return
        cam = self._cam
        if cam is None:
            self._sync_buttons(); return
        if not cam.supported:
            self._say(cam.why, "amber"); self._sync_buttons(); return
        want = self._expected()
        if want is None:
            self.preview.setText("Pick the camera's size (top) to start the picture.")
            self._say("This input's size isn't known: pick the camera's size.", "amber"); self._sync_buttons(); return
        index = cam_list.resolve_index(cam.port, self._inputs())
        if index is None:
            self._say(f"{cam.name or cam.port}: its input ({cam.port}) is not on this PC.", "red"); self._sync_buttons(); return
        if self._factory is not None:
            src = self._factory(cam, index)
        else:
            from src.capture.source import DShowSource
            src = DShowSource(index, self.camera_name())
        from src.capture.grabber import GrabWorker
        self._no_signal, self._warning = False, ""
        self._worker = GrabWorker(src, want[0], want[1], self.camera_name(), self)
        self._worker.opened.connect(self._opened)
        self._worker.preview.connect(self._show_preview)
        self._worker.saved.connect(self._saved)
        self._worker.refused.connect(lambda m: self._grab_done(m, "red"))
        self._worker.stopped.connect(lambda m: (self._say(m, "red"), self._sync_buttons()))
        self._worker.start()
        self._say(f"Opening {self.camera_name() or cam.port}...", "")
        self._sync_buttons()

    def _stop_camera(self) -> None:
        if self._worker is not None:
            w, self._worker = self._worker, None
            w.stop()
        self._delivered = None
        self._sync_buttons()

    def _opened(self, r) -> None:
        if not r.ok:
            self.preview.setPixmap(QPixmap()); self.preview.setText("No picture")
            self._say(r.message, "red"); self._sync_buttons(); return
        self._delivered = (r.width, r.height)
        warn = [w for w in (sizes.size_warning(self._expected(), self._delivered, self.camera_name()),
                            cam_list.other_pc_warning(self._cam)) if w]
        self._warning = "  ".join(warn)            # stays up: a later "live" never hides it
        self._opened_again()
        self._update_info(0.0)
        self._sync_buttons()

    def _update_info(self, fps: float) -> None:
        c = self._cam
        if c is None:
            self.info.setText(""); return
        e = self._expected()
        self.info.setText(f"Camera {self.camera_name() or '?'}   ·   input {c.port}   ·   serial {self.serial() or '?'}   ·   "
                          f"expected {e[0]} x {e[1]}" + (f"   ·   delivered {self._delivered[0]} x {self._delivered[1]}"
                                                         if self._delivered else "") + (f"   ·   {fps:.0f} frames/s" if fps else ""))

    def _show_preview(self, img, no_signal: bool, fps: float) -> None:
        pm = QPixmap.fromImage(img).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)
        self._update_info(fps)
        if no_signal != getattr(self, "_no_signal", None):
            self._no_signal = no_signal
            if no_signal:
                self._say(f"{self.camera_name() or 'This input'}: no signal from the camera (the card shows its "
                          "colour bars). Check the cable and that the camera is on.", "red")
            elif self._delivered:
                self._opened_again()
            self._sync_buttons()

    def _opened_again(self) -> None:
        if getattr(self, "_warning", ""):
            self._say(self._warning, "amber")
        else:
            self._say(f"{self.camera_name() or 'The camera'} is live.", "green")

    # ── grab ─────────────────────────────────────────────────────────────────
    def _ready_to_grab(self) -> bool:
        return (self._worker is not None and self._delivered is not None and not getattr(self, "_no_signal", False)
                and not self._busy_saving and bool(self.camera_name()))

    def _grab(self, countdown: bool) -> None:
        if not self._ready_to_grab():
            if self._cam is not None and self._cam.source == "user" and not self.camera_name():
                self._say("Say which camera this input is (top) before grabbing.", "amber")
            return
        folder = self.folder_edit.text().strip()
        if not folder:
            self._browse()
            folder = self.folder_edit.text().strip()
            if not folder:
                return
        if self._log is None:
            self._log = CaptureLog(folder, self.van_edit.text().strip().upper(), self.camera_name(), self._cam.source,
                                   self._cam.port, self.serial(), self._expected(), self._delivered, self.use_db.isChecked())
        self._busy_saving = True
        self._sync_buttons()
        self._pending_countdown = countdown
        self._worker.request_grab(folder, self._quality, countdown)

    def _saved(self, path: str, w: int, h: int, countdown: bool, thumb) -> None:
        if self._log is not None:
            self._log.add(Path(path), w, h, countdown)
        self._count += 1
        self.count_label.setText(f"{self._count} photo{'s' if self._count != 1 else ''}")
        self._create_thumbnail_widget(thumb, Path(path).name)
        self._grab_done(f"Saved {Path(path).name} ({w} x {h}).", "green")

    def _grab_done(self, msg: str, colour: str) -> None:
        self._busy_saving = False
        self._say(msg, colour)
        self._sync_buttons()

    def _start_countdown(self) -> None:
        if not self._ready_to_grab() or self._tick.isActive():
            return
        self._countdown_left = self._countdown_s
        self.overlay.setGeometry(self.preview.rect()); self.overlay.setText(str(self._countdown_left)); self.overlay.show()
        self._tick.start()

    def _countdown_step(self) -> None:
        self._countdown_left -= 1
        if self._countdown_left > 0:
            self.overlay.setText(str(self._countdown_left)); return
        self._tick.stop(); self.overlay.hide()
        self._grab(True)

    # ── last photos ──────────────────────────────────────────────────────────
    def _create_thumbnail_widget(self, img, name: str) -> None:
        lbl = QLabel(); lbl.setPixmap(QPixmap.fromImage(img)); lbl.setToolTip(name)
        self._thumb_layout.insertWidget(0, lbl)
        self.thumbs_scroll.show()
        while self._thumb_layout.count() > 13:                # keep the last 12 (+ the stretch)
            it = self._thumb_layout.takeAt(self._thumb_layout.count() - 2)
            if it.widget():
                it.widget().deleteLater()

    def _clear_thumbnails(self) -> None:
        self.thumbs_scroll.hide()                       # no empty strip: the preview gets the room
        while self._thumb_layout.count() > 1:
            it = self._thumb_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    # ── folder, calibration app, advanced ────────────────────────────────────
    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder for the photos", self.folder_edit.text())
        if d:
            self.folder_edit.setText(d)

    def _folder_changed(self) -> None:
        self._log = None                                       # a new folder gets its own log
        QSettings(ORG, APP).setValue("folder", self.folder_edit.text().strip())
        self._sync_buttons()

    def _open_calibration(self) -> None:
        folder = self.folder_edit.text().strip()
        if not folder:
            return
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable).with_name("SurveyorCalibration.exe")
            ok = QProcess.startDetached(str(exe), ["--folder", folder])
        else:
            root = _project_root()
            ok = QProcess.startDetached(sys.executable, [str(root / "main.py"), "--folder", folder], str(root))
        ok = ok[0] if isinstance(ok, tuple) else ok
        self._say("Opening the calibration app on this folder..." if ok else
                  "Could not start the calibration app.", "" if ok else "red")

    def _advanced(self) -> None:
        d = AdvancedDialog(self._quality, self._countdown_s, self._grab_key, self)
        if d.exec():
            self._quality, self._countdown_s, self._grab_key = d.values()
            s = QSettings(ORG, APP)
            s.setValue("jpeg_quality", self._quality); s.setValue("countdown_s", self._countdown_s)
            s.setValue("grab_key", self._grab_key)
            self._shortcut.setKey(QKeySequence(self._grab_key))

    # ── state ────────────────────────────────────────────────────────────────
    def _sync_buttons(self) -> None:
        ready = self._ready_to_grab()
        self.grab_btn.setEnabled(ready); self.countdown_btn.setEnabled(ready)
        self.try_btn.setEnabled(self._cam is not None and self._cam.supported)
        self.open_cal_btn.setEnabled(bool(self.folder_edit.text().strip()))

    def _say(self, text: str, colour: str = "") -> None:
        c = {"green": "rgb(60,200,60)", "amber": "rgb(230,180,40)", "red": "rgb(255,107,107)"}.get(colour, "rgb(200,200,200)")
        self.status.setStyleSheet(f"color: {c}; font-size: 11pt;")
        self.status.setText(text)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.overlay.isVisible():
            self.overlay.setGeometry(self.preview.rect())

    def closeEvent(self, e) -> None:
        self._closing = True
        self._tick.stop()
        self._stop_camera()
        if self._list_worker is not None:
            self._list_worker.wait(8000)
        super().closeEvent(e)
