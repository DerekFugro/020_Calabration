"""lens_check.py — is this the right lens file for these Old School photos?  In plain words.

Derek, 2026-11-05: never refuse; warn in clear English and show the dates, because the
people loading calibrations see the numbers but can't tell what they mean.

Checks (each is OK or WARN, never a stop):
  * the lens passed its own check
  * the lens is for this camera: the lens names the camera and serial (Derek, 2026-11-10),
    checked against the Old School folder name, and against the van database's serial
    for that camera when the database answers
  * the lens file was made from photos the same size as the Old School photos
  * the lens and the Old School photos are from the same visit (dates shown)
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache

OK, WARN = "ok", "warn"
SAME_VISIT_DAYS = 7          # lens and Old School further apart than this: different visit


def nice_date(d) -> str:
    """'Sat 4 Apr 2026'."""
    if d is None:
        return "unknown"
    d = d.date() if isinstance(d, datetime) else d
    return f"{d:%a} {d.day} {d:%b %Y}"


def date_range_text(first, last) -> str:
    if first is None:
        return "unknown"
    if last is None or nice_date(first) == nice_date(last):
        return nice_date(first)
    return f"{nice_date(first)} to {nice_date(last)}"


def setup_datetime(setup) -> datetime | None:
    """When an Old School setup photo was taken: from the folder name (20260404.102502),
    else the photo's file time."""
    n = os.path.basename(getattr(setup, "folder", "") or getattr(setup, "name", ""))
    for fmt, k in (("%Y%m%d.%H%M%S", 15), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(n[:k], fmt)
        except ValueError:
            pass
    p = getattr(setup, "photo", "")
    if p and os.path.exists(p):
        return datetime.fromtimestamp(os.path.getmtime(p))
    return None


def old_school_dates(setups) -> tuple[datetime | None, datetime | None]:
    ds = [d for d in (setup_datetime(s) for s in setups) if d is not None]
    return (min(ds), max(ds)) if ds else (None, None)


@lru_cache(maxsize=64)
def _size_of(path: str, mtime: float):
    import cv2
    im = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return None if im is None else (im.shape[1], im.shape[0])


def old_school_size(setups) -> tuple[int, int] | None:
    for s in setups:
        p = getattr(s, "photo", "")
        if p and os.path.exists(p):
            got = _size_of(p, os.path.getmtime(p))
            if got is not None:
                return got
    return None


def _lens_size(intr) -> tuple[int, int, bool]:
    """(width, height, known).  Old files without a size: about twice the centre."""
    w, h = getattr(intr, "width", 0) or 0, getattr(intr, "height", 0) or 0
    if w and h:
        return int(w), int(h), True
    return int(round(2 * intr.K[0, 2])), int(round(2 * intr.K[1, 2])), False


def camera_used(intr, folder_camera: str = "") -> str:
    """The camera the extrinsic is for: the lens' camera, else the folder's."""
    return (getattr(intr, "camera", "") or "") or (folder_camera or "")


def _camera_checks(intr, folder_camera: str, db) -> list[tuple[str, str, str]]:
    out = []
    lc, fc = (getattr(intr, "camera", "") or ""), (folder_camera or "")
    ls = (intr.serial or "").strip()
    of = f" (serial {ls})" if ls else ""
    if not lc and not fc:
        out.append((WARN, "Nobody says which camera this is",
                    "Neither the lens file nor the Old School folder name says which camera this is. "
                    "Pick a lens file made by this app: it records the camera."))
    elif not lc:
        out.append((WARN, "The lens file doesn't say which camera it is for",
                    f"The folder says {fc}, so {fc} is used. Make sure the lens file is for that camera."))
    elif not fc:
        out.append((WARN, "The folder name doesn't say which camera this is",
                    f"The lens is for {lc}{of}, so {lc} is used. The solve checks where the camera points."))
    elif lc != fc:
        out.append((WARN, "The lens is for a different camera than the folder",
                    f"The lens file is for {lc}{of}. The Old School folder is {fc}. "
                    f"Pick the lens for {fc}, or the Old School folder for {lc}."))
    else:
        out.append((OK, "The lens is for this camera", f"The lens and the folder both say {lc}{of}."))

    cam = lc or fc
    if not ls:
        out.append((WARN, "The lens file has no serial number",
                    "Type the camera serial from its label."))
    elif db is not None and not getattr(db, "error", "") and cam:
        row = db.find(cam)
        if row is None:
            out.append((WARN, f"The van database has no enabled {cam} camera",
                        f"The van {db.where} lists " + (", ".join(db.names()) or "no cameras") + "."))
        elif str(row.serial).strip() != ls:
            out.append((WARN, "The lens is for a different serial than the van has",
                        f"The lens file is for serial {ls}. The van {db.where} says {cam} is serial "
                        f"{row.serial}. If the camera was swapped, redo the lens for the new camera; "
                        "otherwise check the camera label."))
        else:
            out.append((OK, "The van database agrees", f"{cam} is serial {ls} in the van {db.where}."))
    return out


def lens_checks(intr, setups, folder_camera: str = "", db=None) -> list[tuple[str, str, str]]:
    """(state, title, detail) in plain words, for the screen and the office page.
    folder_camera: the camera in the Old School folder name.  db: camera_db.DbResult or None
    (no database line when it is None or could not be read)."""
    out = []
    if intr is None:
        return [(WARN, "No lens file yet", "Run Load Intrinsic for this camera, or pick its lens file.")]

    # 1. the lens' own check
    if intr.graded_pass:
        out.append((OK, "The lens passed its own check", ""))
    elif "NOT PASSED" in (intr.source or "").upper():
        out.append((WARN, "The lens did not pass its own check",
                    "You can use it for now, but the camera's angles and height may be off. "
                    "Redo the lens soon."))
    else:
        out.append((WARN, "This app never checked this lens file",
                    "It was made by the old app (or has no grade), so nobody knows how good it is. "
                    "You can use it for now. Redo the lens with this app when you can."))

    # 2. which camera: the lens names it; the folder and the van database check it
    out += _camera_checks(intr, folder_camera, db)

    # 3. photo size
    size = old_school_size(setups)
    lw, lh, known = _lens_size(intr)
    if size is None:
        out.append((WARN, "Can't check the photo size", "No Old School photo could be opened."))
    else:
        pw, ph = size
        about = "" if known else "about "
        same = (abs(lw - pw) <= (2 if known else 0.1 * pw)) and (abs(lh - ph) <= (2 if known else 0.1 * ph))
        if same:
            out.append((OK, "The lens file matches the photo size", f"Both {pw} × {ph}."))
        else:
            out.append((WARN, "The lens file is for a different photo size",
                        f"The Old School photos are {pw} × {ph}. The lens file was made from "
                        f"{about}{lw} × {lh} photos. A lens file only works for photos of the same size, "
                        "so this is almost certainly the wrong lens file, and the results will be wrong."))

    # 4. dates
    f, l = old_school_dates(setups)
    os_txt = f"Old School photos taken: {date_range_text(f, l)}."
    ld = getattr(intr, "date", None)
    what = getattr(intr, "date_what", "") or "Lens done"
    if ld is None:
        out.append((WARN, "The lens file has no date",
                    f"{os_txt} We can't tell if the lens is from the same visit."))
    elif f is None:
        out.append((WARN, "The Old School photos have no date",
                    f"{what}: {nice_date(ld)}. We can't tell if the lens is from the same visit."))
    else:
        l_d = ld.date() if isinstance(ld, datetime) else ld
        before = (f.date() - l_d).days            # lens this many days before the first Old School photo
        after = (l_d - l.date()).days             # lens this many days after the last one
        gap = max(before, after, 0)
        both = f"{what}: {nice_date(ld)}. {os_txt}"
        if gap <= SAME_VISIT_DAYS:
            out.append((OK, "The lens and the Old School photos are from the same visit",
                        both + (f" ({gap} day{'s' if gap != 1 else ''} apart.)" if gap else "")))
        else:
            when = (f"{gap} days before the Old School photos" if before > 0
                    else f"{gap} days after the Old School photos")
            out.append((WARN, "The lens is from a different visit",
                        f"{both} The lens was done {when}. That is only OK if nobody touched the "
                        "camera's focus or zoom, or moved the lens, in between. If you're not sure, "
                        "redo the lens at this visit."))
    return out


def warnings_text(checks) -> list[str]:
    """The WARN lines as one sentence each, for the results and the saved files."""
    return [f"Lens: {t}. {d}".strip() for s, t, d in checks if s == WARN]
