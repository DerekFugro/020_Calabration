"""autograb.py - Auto grab: Capture saves a photo by itself, for one person holding the board.

Derek, 2026-11-14: "I can not move the board and press grab by myself."  His choices:
  * smart: save only when the whole board is found, held still, and in a new spot;
  * screen only (big text on the picture, no sound);
  * stop by itself at a target count (default 40); the button stops it any time.

A look runs about twice a second on the latest full frame (never slows the preview);
the photo saved is the exact frame that was looked at.
Board finding uses the same settings as the calibration app's detector (src/detector.py:
findChessboardCornersSB, 60 px white border; dot boards: src/dot_detector), so a photo
auto grab keeps is one the calibration app can read.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

# A board pose, compared item by item, each on its own scale:
#   place  x, y      fraction of the picture width
#   size   log(board diagonal / picture width)   (0.1 = about 10 % bigger or smaller)
#   shape  board width / diagonal, height / diagonal  (tilt squashes one of them)
#   turn   angle of the board's long side, radians
NEW_SPOT = np.array([0.05, 0.05, 0.10, 0.04, 0.04, 0.17])     # any one this far = a new photo
STILL = np.array([0.004, 0.004, 0.01, 0.004, 0.004, 0.017])   # all within this = held still
STILL_LOOKS = 2        # still this many looks in a row before saving
TARGET = 40
LOOK_EVERY_S = 0.4

# what the crew reads on the picture
SAY = {"no board": "BOARD NOT FOUND", "moving": "HOLD STILL", "hold still": "HOLD STILL",
       "same spot": "MOVE TO A NEW SPOT", "save": "SAVING...", "done": "DONE"}


def signature(points, width: int) -> np.ndarray:
    """[x, y, size, width share, height share, turn] of the board in the picture (see NEW_SPOT)."""
    p = np.asarray(points, float).reshape(-1, 2)
    c = p.mean(0)
    span = p.max(0) - p.min(0)
    diag = max(float(np.hypot(*span)), 1e-6)
    vals, vecs = np.linalg.eigh(np.cov((p - c).T))
    ax = vecs[:, int(np.argmax(vals))]
    turn = float(np.arctan2(ax[1], ax[0]))
    turn = (turn + np.pi / 2) % np.pi - np.pi / 2              # the long side has no front or back
    return np.array([c[0] / width, c[1] / width, np.log(diag / width), span[0] / diag, span[1] / diag, turn])


def _apart(a: np.ndarray, b: np.ndarray, scale: np.ndarray) -> float:
    """How far apart two poses are, in units of `scale` (>= 1 = past the threshold)."""
    d = np.abs(a - b)
    d[5] = min(d[5], np.pi - d[5])                              # turn wraps around
    return float(np.max(d / scale))


class AutoGrabLogic:
    """Decides, look by look, whether to save.  No camera, no Qt: easy to test."""

    def __init__(self, target: int = TARGET, still_looks: int = STILL_LOOKS) -> None:
        self.target, self.still_looks = target, still_looks
        self.saved: list[np.ndarray] = []
        self._prev = None
        self._still = 0

    @property
    def count(self) -> int:
        return len(self.saved)

    def look(self, points, width: int) -> tuple[str, np.ndarray | None]:
        """('no board' | 'moving' | 'hold still' | 'same spot' | 'save' | 'done', signature)"""
        if self.count >= self.target:
            return "done", None
        if points is None or len(np.asarray(points).reshape(-1, 2)) < 4:
            self._prev, self._still = None, 0
            return "no board", None
        sig = signature(points, width)
        if self._prev is None or _apart(sig, self._prev, STILL) > 1.0:
            self._prev, self._still = sig, 0
            return "moving", sig
        self._prev = sig
        self._still += 1
        if self._still < self.still_looks:
            return "hold still", sig
        if any(_apart(sig, s, NEW_SPOT) < 1.0 for s in self.saved):
            return "same spot", sig
        return "save", sig

    def saved_one(self, sig: np.ndarray) -> None:
        self.saved.append(sig)
        self._still = 0


def find_board(gray: np.ndarray, board):
    """Board points in this picture (N x 2), or None.  Same finders as the calibration app."""
    h, w = gray.shape[:2]
    if getattr(board, "is_dots", False):
        from src.dot_detector import detect_blobs, match_dots
        m = match_dots(detect_blobs(gray), board.dot_xy_mm, image_size=(w, h))
        return None if m is None else np.asarray(m.image_points, float).reshape(-1, 2)
    from src.detector import _CB_FLAGS_SB
    pad = 60
    padded = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    found, corners = cv2.findChessboardCornersSB(padded, (board.squares_x - 1, board.squares_y - 1), _CB_FLAGS_SB)
    return corners.reshape(-1, 2) - pad if found else None


def pick_board(gray: np.ndarray, boards):
    """The first library board found in this picture: (board, points) or (None, None)."""
    for b in boards:
        try:
            pts = find_board(gray, b)
        except Exception:  # noqa: BLE001 - a broken board file must not stop the others
            pts = None
        if pts is not None:
            return b, pts
    return None, None


def library_boards():
    from src.boards import list_boards
    return list_boards()


class AutoGrabThread(QThread):
    """Looks at the GrabWorker's latest frame; asks the window to save; waits for the answer."""
    state = Signal(str, int, int)              # what to say, photos saved, target
    want_save = Signal(object, object)         # frame, signature
    board_found = Signal(str)                  # board name

    def __init__(self, worker, target: int = TARGET, boards=None, parent=None) -> None:
        super().__init__(parent)
        self.worker, self.logic = worker, AutoGrabLogic(target)
        self._boards, self.board = boards, None
        self._stop = False
        self._answer = threading.Event()
        self._answer_ok, self._answer_sig = False, None

    def stop(self) -> None:
        self._stop = True
        self._answer.set()
        self.wait(5000)

    def answer(self, ok: bool) -> None:
        """The window saved (True) or could not save (False) the frame asked for."""
        self._answer_ok = ok
        self._answer.set()

    def run(self) -> None:
        if self._boards is None:
            self._boards = library_boards()
        while not self._stop:
            t0 = time.monotonic()
            frame = self.worker.latest() if self.worker is not None else None
            if frame is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
                if self.board is None:
                    self.board, pts = pick_board(gray, self._boards)
                    if self.board is not None:
                        self.board_found.emit(self.board.name)
                else:
                    pts = find_board(gray, self.board)
                what, sig = self.logic.look(pts, gray.shape[1])
                self.state.emit(what, self.logic.count, self.logic.target)
                if what == "done":
                    return
                if what == "save":
                    self._answer.clear()
                    self.want_save.emit(frame, sig)
                    self._answer.wait(15)
                    if self._stop:
                        return
                    if self._answer_ok:
                        self.logic.saved_one(sig)
                        self.state.emit("done" if self.logic.count >= self.logic.target else "saved",
                                        self.logic.count, self.logic.target)
                        if self.logic.count >= self.logic.target:
                            return
            time.sleep(max(0.0, LOOK_EVERY_S - (time.monotonic() - t0)))
