"""source.py - where frames come from: a DirectShow input (the Magewell card) or a fake one.

Read only: open, read frames, close.  Never changes camera or card settings, never retries
in a loop, never tries to take an input from another program (first connect wins).
Always ask for the expected size: with no size asked the card gives 640x480 (bench test).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from src.capture.nosignal import colour_bars


@dataclass
class OpenResult:
    ok: bool
    message: str = ""         # plain English, for the crew
    width: int = 0            # delivered size of the first frame
    height: int = 0


def busy_message(camera: str) -> str:
    return (f"{camera or 'The camera'} is busy or has no signal. Close ARAN collection or the other "
            "program using it, then press Try again.")


class FrameSource(Protocol):
    def open(self, width: int = 0, height: int = 0) -> OpenResult: ...
    def read(self) -> np.ndarray | None: ...
    def close(self) -> None: ...


class DShowSource:
    """One DirectShow input, by its cv2.CAP_DSHOW index (found from its name: cameras.resolve_index)."""

    def __init__(self, index: int, camera: str = "", first_frame_s: float = 3.0) -> None:
        self.index, self.camera, self.first_frame_s = index, camera, first_frame_s
        self._cap = None

    def open(self, width: int = 0, height: int = 0) -> OpenResult:
        import cv2
        self.close()
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            return OpenResult(False, busy_message(self.camera))
        if width and height:                      # before the first read (bench: else 640x480)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        t0, frame = time.monotonic(), None
        while time.monotonic() - t0 < self.first_frame_s:
            ok, f = cap.read()
            if ok and f is not None:
                frame = f; break
        if frame is None:
            cap.release()
            return OpenResult(False, busy_message(self.camera))
        self._cap = cap
        return OpenResult(True, "", frame.shape[1], frame.shape[0])

    def read(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ok, f = self._cap.read()
        return f if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class FakeSource:
    """Frames of any size for tests and PCs without a capture card.  Can act busy, show the
    card's no-signal bars, or deliver a different size than asked."""

    def __init__(self, width: int = 1920, height: int = 1080, busy: bool = False, no_signal: bool = False,
                 deliver: tuple[int, int] | None = None, camera: str = "") -> None:
        self.width, self.height, self.busy, self.no_signal = width, height, busy, no_signal
        self.deliver, self.camera, self._open, self._n = deliver, camera, False, 0

    def open(self, width: int = 0, height: int = 0) -> OpenResult:
        if self.busy:
            return OpenResult(False, busy_message(self.camera))
        if width and height:
            self.width, self.height = width, height
        if self.deliver:
            self.width, self.height = self.deliver
        self._open = True
        return OpenResult(True, "", self.width, self.height)

    def read(self) -> np.ndarray | None:
        if not self._open:
            return None
        if self.no_signal:
            return colour_bars(self.width, self.height)
        self._n += 1
        y = np.linspace(0, 255, self.height, dtype=np.uint8)[:, None]
        x = np.linspace(0, 255, self.width, dtype=np.uint8)[None, :]
        img = np.dstack([np.broadcast_to(x, (self.height, self.width)),
                         np.broadcast_to(y, (self.height, self.width)),
                         np.full((self.height, self.width), (self._n * 7) % 256, np.uint8)])
        return np.ascontiguousarray(img)

    def close(self) -> None:
        self._open = False
