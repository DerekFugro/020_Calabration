"""sizes.py - what size to ask the card for, and whether the camera delivered it.

Never assume 4K.  Expected size = the database's CCDWidth x CCDHeight; otherwise unknown and
the crew is asked (the card gives 640x480 if no size is asked - bench test, ARAN99)."""

from __future__ import annotations


def expected_size(cam) -> tuple[int, int] | None:
    w, h = int(getattr(cam, "width", 0) or 0), int(getattr(cam, "height", 0) or 0)
    return (w, h) if w > 0 and h > 0 else None


def size_warning(expected: tuple[int, int] | None, delivered: tuple[int, int], camera: str = "") -> str | None:
    """Plain words when the photo size isn't the expected one (a warning, never a stop)."""
    who = camera or "The camera"
    dw, dh = delivered
    if expected is None:
        if (dw, dh) == (640, 480):
            return (f"{who} gives 640 x 480 photos: that is the card's size when no size is asked, "
                    "not the camera's. Check the camera's size.")
        return None
    ew, eh = expected
    if (dw, dh) != (ew, eh):
        return (f"{who} should give {ew} x {eh} photos but gives {dw} x {dh}. "
                "The lens calibration needs the camera's full size.")
    return None
