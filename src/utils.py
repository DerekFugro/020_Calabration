"""utils.py — Shared utility functions with no GUI dependencies."""

from __future__ import annotations

import glob
import os

_IMG_EXTS = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")


def photo_dates(folder: str):
    """(first, last) file time of the photos in *folder* as datetimes, or (None, None)."""
    from datetime import datetime
    ts = [os.path.getmtime(p) for p in find_images(folder)]
    if not ts:
        return None, None
    return datetime.fromtimestamp(min(ts)), datetime.fromtimestamp(max(ts))


def date_from_path(path: str):
    """The date in the deepest folder name that has one (20260403 or 2026-04-04), or None.
    Crews name folders by the day they shot, so this survives copying; file times do not."""
    import re
    from datetime import datetime
    for part in reversed(re.split(r"[\\/]", str(path))):
        for m in re.finditer(r"(?<!\d)(20\d\d)-?(\d\d)-?(\d\d)(?!\d)", part):
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


FROM_FOLDER = "folder name"
FROM_FILES = "file date (may be when the photos were copied)"


def photos_taken(folder: str):
    """(first, last, how): when the photos were taken, and where that came from."""
    d = date_from_path(folder)
    if d is not None:
        return d, d, FROM_FOLDER
    f, l = photo_dates(folder)
    return f, l, (FROM_FILES if f else "")


def find_images(folder: str) -> list[str]:
    """Return a sorted, de-duplicated list of JPG/PNG paths in *folder* (non-recursive)."""
    paths: set[str] = set()
    for ext in _IMG_EXTS:
        paths.update(glob.glob(os.path.join(folder, ext)))
    return sorted(paths)
