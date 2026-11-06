"""paths.py - where the app's own data lives (board library, Old School sites).

From the code folder (uv run): the repo's Cal_board and control folders, as before.
Installed (PyInstaller exe): C:\\ProgramData\\020_Calabration\\Cal_board and \\control,
one shared copy for everyone on that PC.  The installer copies the boards and sites
that ship with the app there; seed_data() does the same at start-up in case it was
missed.  Files already there are never overwritten or deleted.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "020_Calabration"
FROZEN = bool(getattr(sys, "frozen", False))

# where the code and the bundled files are (the repo, or the exe's _internal folder)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

if FROZEN:
    DATA_DIR = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData") / APP_NAME
else:
    DATA_DIR = BUNDLE_DIR

CAL_BOARD_DIR = DATA_DIR / "Cal_board"
SITES_DIR = DATA_DIR / "control"


def seed_data() -> list[Path]:
    """Installed copy only: copy shipped boards/sites that are missing in DATA_DIR.
    Never overwrites.  Returns the files copied.  Problems are ignored (read-only PC)."""
    copied: list[Path] = []
    if not FROZEN:
        return copied
    for name in ("Cal_board", "control"):
        src = BUNDLE_DIR / name
        if not src.is_dir():
            continue
        for f in src.rglob("*"):
            if not f.is_file():
                continue
            dst = DATA_DIR / name / f.relative_to(src)
            if dst.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                copied.append(dst)
            except OSError:
                pass
    return copied
