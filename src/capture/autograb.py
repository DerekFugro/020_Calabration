"""autograb.py - Take photos: Capture saves a batch by itself, for one person holding the board.

Derek, 2026-11-14: "I can not move the board and press grab by myself."
Derek, 2026-11-14 (later): no board finding while collecting - it could be frustrating.  Take
a batch of 50 photos, one every 2 s, no matter what (only the card's "no signal" picture is
skipped), and let the calibration app sort them: photos it can't use go to NotUsed, and if
it needs more it asks for another 50 (its "Take 50 more" button opens Capture on the same
folder).  The old "Smart" mode (board found + still + new spot) is gone.

Only a NEW frame is saved: Magewell inputs are read once a second, and the same frame
must never be saved twice.  The photo saved is the exact frame that was taken.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal

BATCH = 50             # photos per batch (the calibration app asks for this many more)
EVERY_S = 2.0          # seconds between photos

# what the crew reads on the picture
SAY = {"no picture": "NO PICTURE", "saved": "SAVED", "done": "DONE"}


class AutoGrabThread(QThread):
    """Asks the window to save the GrabWorker's newest frame every every_s seconds; stops at target."""
    state = Signal(str, int, int)              # 'no picture' | 'saved' | 'done', photos saved, target
    want_save = Signal(object, object)         # frame, None

    def __init__(self, worker, target: int = BATCH, parent=None, every_s: float = EVERY_S) -> None:
        super().__init__(parent)
        self.worker, self.target, self.every_s = worker, target, every_s
        self._stop = False
        self._answer = threading.Event()
        self._answer_ok = False
        self._last = None                      # the last frame saved (never twice)

    def stop(self) -> None:
        self._stop = True
        self._answer.set()
        self.wait(5000)

    def answer(self, ok: bool) -> None:
        """The window saved (True) or could not save (False) the frame asked for."""
        self._answer_ok = ok
        self._answer.set()

    def _new_frame(self):
        """The worker's latest frame if it is one not seen yet, else None."""
        frame = self.worker.latest() if self.worker is not None else None
        if frame is None or frame is self._last:
            return None
        self._last = frame
        return frame

    def _ask_save(self, frame) -> bool:
        """Ask the window to save this frame; wait for its answer."""
        self._answer.clear()
        self.want_save.emit(frame, None)
        self._answer.wait(15)
        return not self._stop and self._answer_ok

    def run(self) -> None:
        from src.capture.nosignal import is_no_signal
        n, target = 0, self.target
        next_t = time.monotonic()
        while not self._stop and n < target:
            now = time.monotonic()
            if now < next_t:
                time.sleep(min(0.05, next_t - now)); continue
            latest = self.worker.latest() if self.worker is not None else None
            if latest is not None and latest is self._last:
                time.sleep(0.02); continue             # wait for a new frame (read once a second)
            next_t = now + self.every_s
            frame = self._new_frame()
            if frame is None or is_no_signal(frame):
                self.state.emit("no picture", n, target); continue
            if self._ask_save(frame):
                n += 1
                self.state.emit("done" if n >= target else "saved", n, target)
