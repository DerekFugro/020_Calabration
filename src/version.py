"""version.py - which code made this file.  Written into the run log, the CAL yaml, the
PDF and the extrinsic results, so months later you can tell which rules applied.

Order: a VERSION file next to the app (write one when installing a copy that is not a
git checkout), else the git commit of this folder (+ "-modified" when there are
uncommitted changes), else "unknown".
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def app_version() -> str:
    f = APP_DIR / "VERSION"
    if f.is_file():
        v = f.read_text(encoding="utf-8").strip()
        if v:
            return v
    try:
        run = lambda *a: subprocess.run(["git", *a], cwd=APP_DIR, capture_output=True,  # noqa: E731
                                        text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        c = run("log", "-1", "--format=%h %cs")
        if c.returncode == 0 and c.stdout.strip():
            dirty = run("status", "--porcelain", "--untracked-files=no", "--", "src")
            return c.stdout.strip() + ("-modified" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"
