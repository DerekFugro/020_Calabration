"""errors.py - full details of Capture's errors for whoever looks later; the crew only sees
plain words.  %LOCALAPPDATA%\\SurveyorCalibration\\capture_errors.log, rotated at 5 MB.
No passwords exist (Windows sign-in), and connection strings are never written."""

from __future__ import annotations

import os
import re
import traceback
from datetime import datetime
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024


def log_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SurveyorCalibration" / "capture_errors.log"


def log_error(what: str, exc: BaseException | None = None, path: Path | None = None) -> None:
    p = path or log_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > MAX_BYTES:
            old = p.with_suffix(".log.1")
            if old.exists():
                old.unlink()
            p.rename(old)
        text = what
        if exc is not None:
            text += "\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        text = re.sub(r"(?i)(PWD|PASSWORD)=[^;]*", r"\1=***", text)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text.rstrip()}\n")
    except OSError:
        pass                                  # logging never stops Capture
