"""cameras.py - the cameras Capture can pick from.

  1. the van database (src/camera_db.py: newest configuration, read only), when it is on;
  2. otherwise every DirectShow video input Windows reports: the crew says which camera it
     is and types the serial.  (No ARAN Settings XML - Derek, 2026-11-13.)
Inputs are found by NAME, never by number (ARAN99 lists 00-1 before 00-0).
A database camera on another kind of input (e.g. Right on the BitFlow CoaXPress card) is
listed but greyed out: "BitFlow camera: not supported yet" (Derek, 2026-11-14).
"""

from __future__ import annotations

import socket
from dataclasses import dataclass


@dataclass
class CaptureCamera:
    name: str                 # ROW, ForwardLeft, ... ('' = not named yet: a bare Windows input)
    port: str                 # DirectShow input name, e.g. "Video (00-1 Pro Capture Dual HDMI 4K+)"
    serial: str = ""          # text, leading zeros kept
    width: int = 0            # expected size (database), 0 = not known
    height: int = 0
    source: str = "user"      # "database" / "user"
    pc: str = ""              # van PC that holds the camera (database VideoModuleName)
    supported: bool = True
    why: str = ""             # when not supported, in plain words

    @property
    def label(self) -> str:
        who = self.name or "(not named)"
        return f"{who}  -  {self.serial or 'no serial'}  -  {self.port}" if self.name else f"{self.port}"


def resolve_index(port: str, names: list[str] | None = None) -> int | None:
    """cv2.CAP_DSHOW index of the input with this name, or None."""
    if names is None:
        from src.capture.dshow_names import video_inputs
        names = video_inputs()
    p = (port or "").strip()
    for i, n in enumerate(names):
        if n == p:
            return i
    for i, n in enumerate(names):
        if n.strip().lower() == p.lower():
            return i
    return None


def _support(port: str, names: list[str]) -> tuple[bool, str]:
    if resolve_index(port, names) is not None:
        return True, ""
    if "CXP" in port.upper() or "GOX" in port.upper():
        return False, "BitFlow camera: not supported yet."
    if port.upper().startswith("GIGE"):
        return False, "GigE camera: not supported yet."
    return False, "Its input is not on this PC."


def from_database(van: str, names: list[str] | None = None) -> tuple[list[CaptureCamera], str]:
    """(cameras, message).  message is '' or why the database gave nothing."""
    from src.camera_db import lookup_cached
    if names is None:
        from src.capture.dshow_names import video_inputs
        names = video_inputs()
    res = lookup_cached(van)
    if res.error:
        return [], res.error
    out = []
    for n in res.names():
        r = res.find(n)
        ok, why = _support(r.port, names)
        out.append(CaptureCamera(r.camera, r.port, r.serial, r.width, r.height, "database", r.pc, ok, why))
    return out, ""


def from_ports(names: list[str] | None = None) -> list[CaptureCamera]:
    """Every Windows video input; the crew names the camera and types the serial."""
    if names is None:
        from src.capture.dshow_names import video_inputs
        names = video_inputs()
    return [CaptureCamera("", n, source="user") for n in names if n]


def other_pc_warning(cam: CaptureCamera, computer: str | None = None) -> str | None:
    """The database says another PC holds this camera (e.g. ARAN69-ROW, not -SERVER)."""
    here = (computer or socket.gethostname() or "").upper()
    if cam.pc and here and cam.pc.upper() != here:
        return (f"The van database says {cam.name} is on {cam.pc}, but this PC is {here}. "
                "Its picture may come from a different input.")
    return None
