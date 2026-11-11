"""superseded.py - one current result per camera (Derek, 2026-11-11).

When a new result is saved, the earlier ones are moved into a Superseded\\ subfolder
beside them, not deleted: the folder stays clean (one current result), and an earlier
result can still be found if the new one turns out worse or the office already used it.
The move happens only after the new result is written, so a camera always has a result.

  Load Intrinsic   photo folder:   CAL_*.yaml / .pdf (NOT_PASSED_ too), Calibration_<date>\\
  Load Extrinsic   camera folder:  Extrinsic_<date>\\
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

FOLDER = "Superseded"
_CAL = re.compile(r"^(?:NOT_PASSED_)?CAL_.+_\d{8}_\d{6}(?:_\d+)?\.(?:ya?ml|pdf)$", re.I)
_CAL_DIR = re.compile(r"^Calibration_\d{8}_\d{6}$", re.I)
_EXT_DIR = re.compile(r"^Extrinsic_\d{8}_\d{6}$", re.I)


def _list(folder, keep) -> list[Path]:
    p = Path(folder)
    if not p.is_dir():
        return []
    return sorted(c for c in p.iterdir() if keep(c))


def intrinsic_results(folder) -> list[Path]:
    """Saved Load Intrinsic results in a photo folder."""
    return _list(folder, lambda c: (c.is_file() and _CAL.match(c.name)) or (c.is_dir() and _CAL_DIR.match(c.name)))


def extrinsic_results(folder) -> list[Path]:
    """Saved Load Extrinsic results in a camera's Old School folder, oldest first."""
    return _list(folder, lambda c: c.is_dir() and _EXT_DIR.match(c.name))


def move_to_superseded(paths, folder) -> list[Path]:
    """Move each path into <folder>\\Superseded\\ (a name already there gets _2, _3 ...).
    Returns where they went.  A file that can't be moved is left where it is."""
    paths = [Path(p) for p in paths if Path(p).exists()]
    if not paths:
        return []
    dest = Path(folder) / FOLDER
    dest.mkdir(exist_ok=True)
    out = []
    for p in paths:
        target = dest / p.name
        n = 2
        while target.exists():
            target = dest / f"{p.stem}_{n}{p.suffix}"
            n += 1
        try:
            shutil.move(str(p), str(target))
            out.append(target)
        except OSError:
            pass
    return out
