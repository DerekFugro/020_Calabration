"""nosignal.py - is this frame the capture card's own "No Signal" picture?

Bench test, ARAN99 2026-11-13 (docs/capture/bench_results.md): with nothing on an input the
Magewell card sends full-size colour bars - white, yellow, cyan, green, magenta, red, blue,
black, each 1/8 of the width - with a "No Signal" box in the middle, at whatever size was
asked.  Capture must never save that as a lens photo.
"""

from __future__ import annotations

import numpy as np

# BGR, left to right
BARS = [(255, 255, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0),
        (255, 0, 255), (0, 0, 255), (255, 0, 0), (0, 0, 0)]
TOL = 60                      # per channel (JPEG / scaling)
ROWS = (0.10, 0.25, 0.85)     # above and below the "No Signal" box


def is_no_signal(frame: np.ndarray | None) -> bool:
    """True when the frame is the card's colour-bar picture (or there is no frame)."""
    if frame is None or frame.ndim != 3 or frame.shape[0] < 16 or frame.shape[1] < 16:
        return frame is None
    h, w = frame.shape[:2]
    for fy in ROWS:
        y = int(h * fy)
        for i, want in enumerate(BARS):
            x0, x1 = int(w * (i + 0.3) / 8), int(w * (i + 0.7) / 8)
            got = frame[max(0, y - 2):y + 3, x0:x1].reshape(-1, 3).mean(axis=0)
            if np.any(np.abs(got - np.array(want, float)) > TOL):
                return False
    return True


def colour_bars(width: int, height: int) -> np.ndarray:
    """The card's no-signal picture (for FakeSource and tests): the 8 bars, a white box."""
    img = np.zeros((height, width, 3), np.uint8)
    for i, c in enumerate(BARS):
        img[:, int(width * i / 8):int(width * (i + 1) / 8)] = c
    img[int(height * 0.41):int(height * 0.55), int(width * 0.185):int(width * 0.815)] = 255
    return img
