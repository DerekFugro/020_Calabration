"""capture_log.py - CAPTURE_<YYYYMMDD_HHMMSS>.json beside the photos, one per session.

Never overwritten (a new session gets a new name); rewritten whole after each grab, through a
temporary file and a rename, so it is never half written.  Serials are text.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime
from pathlib import Path


class CaptureLog:
    def __init__(self, folder, van: str, camera: str, camera_source: str, port: str, serial: str,
                 expected_size, delivered_size, database_used: bool) -> None:
        from src.version import app_version
        self.folder = Path(folder)
        now = datetime.now()
        self.path = None
        self._now = now
        self.data = {
            "app_version": app_version(), "computer": socket.gethostname(), "van": van,
            "camera": camera, "camera_source": camera_source, "van_database_used": bool(database_used),
            "port": port, "serial": str(serial or ""),
            "expected_size": None if not expected_size else f"{expected_size[0]}x{expected_size[1]}",
            "delivered_size": None if not delivered_size else f"{delivered_size[0]}x{delivered_size[1]}",
            "started": now.isoformat(timespec="seconds"), "photos": [],
        }
        # Take the name now (exclusive create), so two sessions in the same second never share a log.
        self.folder.mkdir(parents=True, exist_ok=True)
        n = 1
        while True:
            p = self.folder / (f"CAPTURE_{now:%Y%m%d_%H%M%S}.json" if n == 1 else f"CAPTURE_{now:%Y%m%d_%H%M%S}_{n}.json")
            try:
                with open(p, "x", encoding="utf-8") as fh:
                    fh.write(json.dumps(self.data, indent=2, ensure_ascii=False))
                self.path = p
                break
            except FileExistsError:
                n += 1

    def add(self, photo: Path, width: int, height: int, countdown: bool = False, when: datetime | None = None) -> None:
        self.data["photos"].append({"file": Path(photo).name,
                                    "time": (when or datetime.now()).isoformat(timespec="milliseconds"),
                                    "width": int(width), "height": int(height), "countdown": bool(countdown)})
        self.write()

    def write(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
