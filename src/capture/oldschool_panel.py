"""oldschool_panel.py - Capture's Old School panel (Phase 8): the POS light, Save image, the
5-minute wait and each position's rating.  The window owns the camera and saves the photos.

One position (Derek, 2026-11-15):
  1. Save image (only when the camera is live and the POS light is green)
  2. make <site>\\<camera>\\Position<N>, ask the POS logger to log 5 minutes into it (mark)
  3. the window takes a few photos into the same folder (want_photos -> photos_done)
  4. "Keep the van parked" countdown until the POS logger says the mark is done
  5. the rating: PASS / NOT PASSED + why; NOT PASSED says "Redo this position"
The POS logger is started when the site folder is known and closed with the window.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.capture import oldschool as osc
from src.capture.pos_link import PosError, PosLink
from src.styles import SPACING

LIGHT = {"green": "rgb(40,170,60)", "orange": "rgb(220,140,20)", "red": "rgb(200,50,50)", "grey": "rgb(90,90,90)"}
FINISH_GRACE_S = 30.0          # mark_done should come at 300 s; after 330 s it never will
PHOTOS_WAIT_S = 30.0           # the photos should take ~5 s


class _Call(QThread):
    """Runs one POS link call off the screen's thread (start + wait_ready, mark)."""
    done = Signal(object, str)                  # result, error text

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(), "")
        except PosError as exc:
            self.done.emit(None, str(exc))
        except Exception as exc:  # noqa: BLE001 - a crew message, never a crash
            self.done.emit(None, f"POS logging problem: {exc}")


class OldSchoolPanel(QWidget):
    want_photos = Signal(object, int, float)     # position folder, photos, seconds apart
    busy_changed = Signal(bool)                  # a position is being collected (lock the camera)
    rated = Signal(object, dict)                 # position folder, what goes in its log

    def __init__(self, pos_factory=None, parent=None) -> None:
        super().__init__(parent)
        self._pos_factory = pos_factory or (lambda: PosLink())
        self.pos: PosLink | None = None
        self.site: Path | None = None
        self._camera, self._serial, self._camera_ok = "", "", False
        self._ready = False             # POS recording (wait_ready passed)
        self._problem = ""              # POS start problem (crew words)
        self._job = None                # running _Call
        self._pos_n, self._pos_folder = 0, None
        self._pos_cam, self._pos_serial = "", ""
        self._mark = 0                  # POS mark number of the position being collected
        self._mark_t0 = 0.0
        self._mark_secs = osc.MARK_SECONDS
        self._photos: list = []
        self._photos_done = False
        self._photos_t0 = 0.0
        self._passed: dict[str, int] = {}
        self._after: dict[str, bool] = {}      # camera -> did its last position pass
        self._create_widgets()
        self._create_layouts()
        self._connect_signals()
        self._apply_styles()
        self._load_initial_state()

    # ── widgets ──────────────────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        self.light = QLabel("POS")
        self.light_text = QLabel("Starting the POS logging...")
        self.light_text.setWordWrap(True)
        self.where = QLabel("")
        self.big = QLabel("")
        self.big.setWordWrap(True)
        self.save_btn = QPushButton("Save image")
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.tally = QLabel("")
        self._poll = QTimer(self)
        self._poll.setInterval(250)

    def _create_layouts(self) -> None:
        lt = QVBoxLayout(); lt.setSpacing(4)
        lt.addWidget(self.light); lt.addWidget(self.light_text)
        mid = QVBoxLayout(); mid.setSpacing(4)
        mid.addWidget(self.where); mid.addWidget(self.big); mid.addWidget(self.result); mid.addWidget(self.tally)
        row = QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(SPACING * 2)
        row.addLayout(lt, 2); row.addLayout(mid, 5); row.addWidget(self.save_btn, 2)

    def _connect_signals(self) -> None:
        self.save_btn.clicked.connect(self.save_image)
        self._poll.timeout.connect(self._tick)

    def _apply_styles(self) -> None:
        self.light.setFixedHeight(64)
        self.light_text.setStyleSheet("font-size: 11pt;")
        self.where.setStyleSheet("font-size: 12pt; color: rgb(170,170,170);")
        self.big.setStyleSheet("font-size: 20pt; font-weight: bold;")
        self.result.setStyleSheet("font-size: 13pt;")
        self.tally.setStyleSheet("font-size: 11pt; color: rgb(170,170,170);")
        self.save_btn.setObjectName("primary_button")
        self.save_btn.setMinimumHeight(72)
        self.save_btn.setStyleSheet("font-size: 18pt; font-weight: bold;")
        self._show_light("grey", "Looking for the POS...", "")

    def _load_initial_state(self) -> None:
        self.save_btn.setEnabled(False)
        self._say_big("Pick the folder for the Old School photos.")

    # ── POS logger ───────────────────────────────────────────────────────────
    def start(self, site: Path) -> None:
        """The site folder is made: start the POS logger recording into it."""
        self.site = Path(site)
        self.pos = self._pos_factory()
        self._ready, self._problem = False, ""
        self._show_light("grey", "Starting the POS logging...", "")
        self._say_big("Starting the POS logging...")

        def go():
            self.pos.start(str(self.site))
            return self.pos.wait_ready()
        self._run(go, self._started)
        self._poll.start()

    def _started(self, status, err: str) -> None:
        if err:
            self._problem = err
            self._show_light("red", "No POS logging", err)
            self._say_big("POS logging did not start.")
        else:
            self._ready = True
            self._show_status(status)
            self._say_ready()
        self._sync()

    def close_pos(self) -> None:
        """Window closing: stop the POS logger cleanly (quit, bye)."""
        self._poll.stop()
        if self._job is not None:
            self._job.wait(15000)
        if self.pos is not None:
            self.pos.close()

    # ── camera (from the window) ─────────────────────────────────────────────
    def set_camera(self, name: str, serial: str, ok: bool) -> None:
        self._camera, self._serial, self._camera_ok = name, serial, ok
        self._update_tally()
        if self._ready and not self.busy:
            self._say_ready()
        self._sync()

    # ── one position ─────────────────────────────────────────────────────────
    @property
    def busy(self) -> bool:
        return self._pos_folder is not None

    def can_save(self) -> bool:
        st = self.pos.status if self.pos is not None else None
        return (self._ready and not self.busy and self._job is None and self._camera_ok
                and bool(self._camera) and st is not None and st.ok_to_collect and not self.pos.lost)

    def save_image(self) -> None:
        if not self.can_save():
            return
        self._pos_cam, self._pos_serial = self._camera, self._serial      # fixed for this position
        try:
            n, folder = osc.make_position_folder(self.site, self._pos_cam)
        except OSError as exc:
            self._say_result(f"Could not make the position folder: {exc}", "red"); return
        self._pos_n, self._pos_folder = n, folder
        self._mark, self._photos, self._photos_done = 0, [], False
        self.busy_changed.emit(True)
        self.where.setText(f"{self._pos_cam}  ·  Position {n}")
        self._say_big("Starting...")
        self.result.setText("")
        label = f"{self._pos_cam}_Position{n}"
        self._run(lambda: self.pos.mark(label, str(folder), self._mark_secs), self._marked)
        self._sync()

    def _marked(self, reply, err: str) -> None:
        if err or not reply or not reply.get("ok"):
            why = err or (reply or {}).get("error") or "no answer"
            self._finish(None, [f"the POS logging did not start for this position ({why})"])
            return
        self._mark = int(reply.get("mark") or 0)
        self._mark_t0 = time.monotonic()
        self._mark_secs = float(reply.get("seconds") or self._mark_secs)
        self._photos_t0 = time.monotonic()
        self._say_big("Taking photos - keep the van parked.")
        self.want_photos.emit(self._pos_folder, osc.PHOTOS, osc.PHOTO_EVERY_S)

    def photos_done(self, paths: list) -> None:
        """The window saved these photos (maybe fewer than asked)."""
        if not self.busy or self._photos_done:
            return
        self._photos, self._photos_done = list(paths), True

    def _tick(self) -> None:
        if self.pos is None:
            return
        while not self.pos.messages.empty():
            m = self.pos.messages.get_nowait()
            if m.get("type") in ("logging", "heartbeat", "reply") and "light" in m and self._ready:
                self._show_status(self.pos.status)
        if self._ready and self.pos.lost:
            self._show_light("red", "POS logging stopped", "The POS logging app is not answering. Call for help.")
        if self.busy and self._mark:
            if not self._photos_done and time.monotonic() - self._photos_t0 > PHOTOS_WAIT_S:
                self._photos_done = True              # the window could not save them all
            res = self.pos.result(self._mark)
            left = self._mark_secs - (time.monotonic() - self._mark_t0)
            if res is not None and self._photos_done:
                self._finish(res, []); return
            if left < -FINISH_GRACE_S or (not self.pos.alive):
                self._finish(res, []); return
            if self._photos_done:
                mm, ss = divmod(max(0, int(left + 0.999)), 60)
                self._say_big(f"Keep the van parked  {mm}:{ss:02d}")
        self._sync()

    def _finish(self, res, extra: list) -> None:
        checks = osc.check_photos(self._photos)
        still = osc.van_still(res.file) if res is not None and res.file else {}
        rating = osc.rate_position(res, checks, still)
        rating.reasons = extra + rating.reasons
        rating.passed = rating.passed and not extra
        n, folder = self._pos_n, self._pos_folder
        cam = self._pos_cam
        log = {"position": n, "camera": cam, "serial": self._pos_serial,
               "pos_mark": None if res is None else dict(res.__dict__),
               "pos_session_folder": self.pos.status.session_folder if self.pos else "",
               "photos_checked": [c.__dict__ for c in checks], "rating": rating.as_dict()}
        if rating.passed:
            self._passed[cam] = self._passed.get(cam, 0) + 1
        self._after[cam] = rating.passed
        self._pos_folder, self._mark = None, 0
        self.rated.emit(folder, log)
        self.busy_changed.emit(False)
        self._say_result(rating.text(n), "green" if rating.passed else "red")
        self._update_tally()
        if self._ready:
            self._say_ready()
        self._sync()

    # ── words ────────────────────────────────────────────────────────────────
    def _say_ready(self) -> None:
        if self.busy:
            return
        after = self._after.get(self._camera)
        if not self._camera:
            self._say_big("Pick the camera.")
        elif after is False:
            self._say_big("Redo this position, then press Save image.")
        elif after is True:
            self._say_big("Move to the next position, then press Save image.")
        else:
            self._say_big("Park at the first position, then press Save image.")

    def _update_tally(self) -> None:
        if not self._camera:
            self.tally.setText(""); return
        n = self._passed.get(self._camera, 0)
        need = osc.MIN_POSITIONS
        self.tally.setText(f"{self._camera}: {n} position{'s' if n != 1 else ''} passed"
                           + (f" (at least {need} needed)" if n < need else " - enough for this camera"))

    def _show_status(self, st) -> None:
        self._show_light(st.light if st.logging else "red", st.message or "POS", st.detail)

    def _show_light(self, colour: str, title: str, detail: str) -> None:
        self.light.setText(title)
        self.light.setStyleSheet(f"background: {LIGHT.get(colour, LIGHT['grey'])}; color: white; "
                                 "font-size: 15pt; font-weight: bold; border-radius: 8px; padding: 4px;")
        self.light_text.setText(detail)
        self._light = colour

    def _say_big(self, text: str) -> None:
        self.big.setText(text)

    def _say_result(self, text: str, colour: str) -> None:
        c = {"green": "rgb(60,200,60)", "red": "rgb(255,107,107)"}.get(colour, "rgb(200,200,200)")
        self.result.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {c};")
        self.result.setText(text)

    def _sync(self) -> None:
        self.save_btn.setEnabled(self.can_save())

    def _run(self, fn, done) -> None:
        job = _Call(fn, self)
        self._job = job

        def finished(res, err):
            self._job = None
            done(res, err)
        job.done.connect(finished)
        job.start()
