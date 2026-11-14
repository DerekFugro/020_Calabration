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


def scaling(expected: tuple[int, int] | None, signal) -> str | None:
    """'upscaling' / 'downscaling' / 'rescaling' when the card must change the camera's picture to
    give the expected (ACS / database) size; None when they match or the camera's size isn't known."""
    if expected is None or signal is None or not getattr(signal, "locked", False):
        return None
    ew, eh = expected
    if (ew, eh) == (signal.width, signal.height):
        return None
    if ew >= signal.width and eh >= signal.height:
        return "upscaling"
    if ew <= signal.width and eh <= signal.height:
        return "downscaling"
    return "rescaling"


def scaling_question(expected: tuple[int, int], signal, camera: str = "", database: bool = True) -> str:
    """Plain words for the crew: the camera's own size is not the size Capture asks the card for."""
    who = camera or "This camera"
    kind = scaling(expected, signal) or "rescaling"
    where = "ACS (the van database) is set to" if database else "the size picked is"
    return (f"{who}: the camera sends {signal.text()}, but {where} {expected[0]} x {expected[1]}. "
            f"The card is {kind} the picture.\n\nDid you know this camera is set up for {kind}?\n\n"
            f"Either way, the photos are taken at {expected[0]} x {expected[1]}"
            + (", the same as ACS records." if database else ", the size picked."))
