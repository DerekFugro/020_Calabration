"""camera_db.py - read the van's camera serials from its ARAN MS SQL database (read only).

Derek, 2026-11-06.  On a van the database is on <VAN>-SERVER and is named after the
van (ARAN28 on ARAN28-SERVER); on the dev PC a copy sits on this PC (ARAN69 on
localhost).  Table VideoDeviceConfig has one row per camera: CaptureView (ROW,
ForwardLeft, ...), CameraSerialNumber, CCDWidth / CCDHeight (photo size).

Login: always the Windows sign-in of the person running the app (Trusted_Connection).
No SQL login and no password: nothing to store, nothing to leak.

Where: <VAN>-SERVER, then this PC (a copy on a dev PC); the database is named after the
van.  No settings: the Database... box was removed (Derek, 2026-11-10).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SETTINGS_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SurveyorCalibration"
TIMEOUT_S = 4

# Every save of ARAN's camera setup writes a NEW VideoSystemConfiguration holding the whole
# camera set; the old ones stay (ARAN99: 29 of them, all Installed/Enabled).  So only the
# NEWEST configuration is the van's current cameras (Derek, 2026-11-14; ARAN99 check: adding
# a Right camera wrote configs 1068/1069 with all three cameras).  Chosen in lookup(), below.
QUERY = """
SELECT v.Name, d.VideoModuleName, d.CaptureView, d.CameraSerialNumber, d.CCDWidth, d.CCDHeight, d.Enabled,
       d.CaptureDeviceName, d.IDVideoSystemConfiguration, s.TimeChanged
FROM VideoDeviceConfig d
LEFT JOIN VideoSystemConfiguration s ON s.IDVideoSystemConfiguration = d.IDVideoSystemConfiguration
LEFT JOIN CollectionVehicles v ON v.IdCollectionVehicle = s.IDVehicle
"""


@dataclass
class CameraRow:
    camera: str
    serial: str
    width: int
    height: int
    port: str = ""          # CaptureDeviceName: the capture input, e.g. "Video (00-1 Pro Capture Dual HDMI 4K+)"
    pc: str = ""            # VideoModuleName: which van PC holds the camera, e.g. "Aran99-Server"


def newest_configuration(rows, van: str) -> list:
    """Only the rows of the newest camera configuration (TimeChanged, then id), this van's if the
    database names vans (an exported database can hold several)."""
    def is_van(r):
        name = (getattr(r, "Name", "") or "").upper().replace(" ", "")
        mod = (getattr(r, "VideoModuleName", "") or "").upper().replace(" ", "")
        return bool(van) and (name == van or mod.startswith(van))
    mine = [r for r in rows if is_van(r)] or list(rows)
    def key(r):
        t = getattr(r, "TimeChanged", None)
        return (t is not None, t or 0, getattr(r, "IDVideoSystemConfiguration", 0) or 0)
    if not mine:
        return []
    best = max(mine, key=key)
    cfg = getattr(best, "IDVideoSystemConfiguration", None)
    return [r for r in mine if getattr(r, "IDVideoSystemConfiguration", None) == cfg]


@dataclass
class DbResult:
    cameras: dict = field(default_factory=dict)     # camera name (upper) -> CameraRow
    server: str = ""
    database: str = ""
    error: str = ""

    def find(self, camera: str) -> CameraRow | None:
        return self.cameras.get((camera or "").replace(" ", "").upper())

    def names(self) -> list[str]:
        """The van's enabled cameras as the database names them, in the usual order."""
        from src.van_scan import CAMERAS, camera_from_name
        order = {c: i for i, c in enumerate(CAMERAS)}
        rows = list(self.cameras.values())
        return [r.camera for r in sorted(rows, key=lambda r: (order.get(camera_from_name(r.camera), 99), r.camera))]

    @property
    def where(self) -> str:
        return f"database {self.database} on {self.server}"


# ── connecting and reading ───────────────────────────────────────────────────

def _driver() -> str:
    import pyodbc
    have = pyodbc.drivers()
    for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"):
        if d in have:
            return d
    raise RuntimeError("No SQL Server ODBC driver on this PC (install 'ODBC Driver 18 for SQL Server').")


def _connect(server: str, database: str, s: dict | None = None):
    """Log in with this PC's Windows sign-in (no SQL login, no password)."""
    import pyodbc
    cs = (f"DRIVER={{{_driver()}}};SERVER={server};DATABASE={database};"
          "Encrypt=yes;TrustServerCertificate=yes;ApplicationIntent=ReadOnly;Trusted_Connection=yes;")
    return pyodbc.connect(cs, timeout=TIMEOUT_S, readonly=True)


def candidates(van: str) -> list[tuple[str, str]]:
    """(server, database) pairs to try, in order: the van's server, then this PC."""
    return [(f"{van}-SERVER", van), ("localhost", van)] if van else []


def _plain(exc, database: str) -> str:
    """The ODBC error in a few plain words (the full text is in the run log)."""
    t = str(exc)
    if "18456" in t or "Login failed" in t:
        return f"this Windows user is not allowed into {database}, or there is no such database"
    if "4060" in t or "Cannot open database" in t:
        return f"no database {database}"
    if "08001" in t or "timeout" in t.lower() or "Named Pipes" in t:
        return "SQL Server not reachable"
    return t.splitlines()[0][:160]


def _resolves(host: str, wait_s: float = 1.5) -> bool:
    """True if the host name resolves quickly (skips a 5 s login timeout on a dev PC)."""
    if host.lower() in ("localhost", ".", "(local)", "127.0.0.1"):
        return True
    import socket
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as Late
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        return bool(ex.submit(socket.getaddrinfo, host.split("\\")[0], None).result(timeout=wait_s))
    except (Late, OSError):
        return False
    finally:
        ex.shutdown(wait=False)


_cache: dict = {}


def lookup_cached(van: str) -> DbResult:
    """lookup() once per van per session."""
    key = (van or "").strip().upper()
    if key not in _cache:
        _cache[key] = lookup(van)
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()


def lookup(van: str) -> DbResult:
    """The van's cameras from its database.  Never raises: problems land in .error."""
    van = (van or "").strip().upper()
    if not van:
        return DbResult(error="No van known, so the database can't be found (type the van at the top).")
    errors = []
    for server, database in candidates(van):
        if not _resolves(server):
            errors.append(f"{server}: not found on the network")
            continue
        try:
            con = _connect(server, database)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{server}: {_plain(exc, database)}")
            continue
        try:
            rows = con.cursor().execute(QUERY).fetchall()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{server}/{database}: could not read the cameras ({str(exc).splitlines()[0][:120]})")
            continue
        finally:
            con.close()
        res = DbResult(server=server, database=database)
        # The newest configuration only (see QUERY), enabled cameras only (Derek, 2026-11-10).
        for r in newest_configuration(rows, van):
            if r.Enabled and r.CaptureView and r.CameraSerialNumber:
                res.cameras[r.CaptureView.replace(" ", "").upper()] = CameraRow(
                    r.CaptureView, str(r.CameraSerialNumber).strip(), int(r.CCDWidth or 0), int(r.CCDHeight or 0),
                    str(getattr(r, "CaptureDeviceName", "") or "").strip(), str(r.VideoModuleName or "").strip())
        if not res.cameras:
            res.error = f"{res.where} has no enabled cameras in VideoDeviceConfig."
        return res
    return DbResult(error="Could not read the van database - " + "; ".join(errors) + ". Type the serial.")
