"""grabber.py - runs one camera in its own thread so the window never freezes.

Opens the source at the expected size, sends small preview pictures (at most ~15 a second),
keeps the latest full frame, and saves it when asked.  A frame that is the card's "No Signal"
picture is never saved.  Closes the camera when stopped.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from src.capture.nosignal import is_no_signal
from src.capture.saver import save_jpeg

PREVIEW_FPS = 15
PREVIEW_MAX_W = 1280
THUMB_W = 160


def to_qimage(frame: np.ndarray, max_w: int) -> QImage:
    """BGR frame -> RGB QImage no wider than max_w (keeps the shape: never stretched)."""
    import cv2
    h, w = frame.shape[:2]
    if w > max_w:
        frame = cv2.resize(frame, (max_w, int(round(h * max_w / w))), interpolation=cv2.INTER_AREA)
    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    return QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()


class GrabWorker(QThread):
    opened = Signal(object)                    # source.OpenResult
    preview = Signal(QImage, bool, float)      # picture, no signal?, frames per second
    saved = Signal(str, int, int, bool, QImage)  # path, width, height, countdown, thumbnail
    refused = Signal(str)                      # plain words: why nothing was saved
    stopped = Signal(str)                      # plain words when the camera stops sending

    def __init__(self, source, width: int, height: int, camera: str = "", parent=None) -> None:
        super().__init__(parent)
        self.source, self.width, self.height, self.camera = source, width, height, camera
        self._stop = False
        self._lock = threading.Lock()
        self._pending = None

    def request_grab(self, folder: str, quality: int, countdown: bool = False) -> None:
        with self._lock:
            self._pending = (folder, quality, countdown)

    def stop(self) -> None:
        self._stop = True
        self.wait(5000)

    def run(self) -> None:
        try:
            r = self.source.open(self.width, self.height)
        except Exception as exc:  # noqa: BLE001
            from src.capture.errors import log_error
            log_error(f"open {self.camera}", exc)
            from src.capture.source import OpenResult, busy_message
            r = OpenResult(False, busy_message(self.camera))
        self.opened.emit(r)
        if not r.ok:
            return
        last_preview, misses, t_count, n_count, fps = 0.0, 0, time.monotonic(), 0, 0.0
        try:
            while not self._stop:
                f = self.source.read()
                if f is None:
                    misses += 1
                    if misses > 60:
                        self.stopped.emit(f"{self.camera or 'The camera'} stopped sending pictures. "
                                          "Check the cable, then press Try again.")
                        return
                    time.sleep(0.02)
                    continue
                misses = 0
                n_count += 1
                now = time.monotonic()
                if now - t_count >= 1.0:
                    fps, n_count, t_count = n_count / (now - t_count), 0, now
                with self._lock:
                    pending, self._pending = self._pending, None
                if pending is not None:
                    self._save(f, *pending)
                if now - last_preview >= 1.0 / PREVIEW_FPS:
                    last_preview = now
                    self.preview.emit(to_qimage(f, PREVIEW_MAX_W), is_no_signal(f), fps)
        finally:
            self.source.close()

    def _save(self, frame, folder, quality, countdown) -> None:
        if is_no_signal(frame):
            self.refused.emit(f"{self.camera or 'The camera'}: no signal from the camera (the card shows its "
                              "colour bars). Check the cable and that the camera is on. Nothing was saved.")
            return
        try:
            p = save_jpeg(frame, folder, self.camera, quality)
        except OSError as exc:
            from src.capture.errors import log_error
            log_error(f"save {self.camera} into {folder}", exc)
            self.refused.emit(f"The photo could not be saved in {folder}: {exc}")
            return
        self.saved.emit(str(p), frame.shape[1], frame.shape[0], countdown, to_qimage(frame, THUMB_W))
