"""camera_db.py - read the van's camera serials from its ARAN MS SQL database (read only).

Derek, 2026-11-06.  On a van the database is on <VAN>-SERVER and is named after the
van (ARAN28 on ARAN28-SERVER); on the dev PC a copy sits on this PC (ARAN69 on
localhost).  Table VideoDeviceConfig has one row per camera: CaptureView (ROW,
ForwardLeft, ...), CameraSerialNumber, CCDWidth / CCDHeight (photo size).

Login: always the Windows sign-in of the person running the app (Trusted_Connection).
No SQL login and no password: nothing to store, nothing to leak.

Settings (all optional) in %LOCALAPPDATA%\\SurveyorCalibration\\camera_db.json:
  {"server": "", "database": ""}
Blank server -> <VAN>-SERVER, then this PC.  Blank database -> the van name.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SETTINGS_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SurveyorCalibration"
SETTINGS = SETTINGS_DIR / "camera_db.json"
TIMEOUT_S = 4

QUERY = """
SELECT v.Name, d.VideoModuleName, d.CaptureView, d.CameraSerialNumber, d.CCDWidth, d.CCDHeight, d.Enabled
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


# ── settings ──────────────────────────────────────

def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(s: dict) -> None:
    _cache.clear()
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({k: s.get(k, "") for k in ("server", "database")}, indent=1),
                        encoding="utf-8")


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


def candidates(van: str, s: dict) -> list[tuple[str, str]]:
    """(server, database) pairs to try, in order."""
    db = s.get("database") or van
    if s.get("server"):
        return [(s["server"], db)]
    out = [(f"{van}-SERVER", db)] if van else []
    return out + [("localhost", db)]


def _plain(exc, database: str) -> str:
    """The ODBC error in a few plain words (the full text is in the run log)."""
    t = str(exc)
    if "18456" in t or "Login failed" in t:
        return (f"this Windows user is not allowed into {database}, or there is no such database "
                "(check the Database... settings)")
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
    """lookup() once per van and settings (the Database... box clears it)."""
    s = load_settings()
    key = ((van or "").upper(), json.dumps(s, sort_keys=True))
    if key not in _cache:
        _cache[key] = lookup(van, s)
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()


def lookup(van: str, settings: dict | None = None) -> DbResult:
    """The van's cameras from its database.  Never raises: problems land in .error."""
    van = (van or "").strip().upper()
    s = load_settings() if settings is None else settings
    if not van and not s.get("database"):
        return DbResult(error="No van known, so the database can't be found (type the van at the top).")
    errors = []
    for server, database in candidates(van, s):
        if not _resolves(server):
            errors.append(f"{server}: not found on the network")
            continue
        try:
            con = _connect(server, database, s)
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
        # Only enabled cameras (Derek, 2026-11-10).  An exported database can hold rows for
        # several vans: this van's rows win.
        def rank(r):
            mod = (r.VideoModuleName or "").upper().replace(" ", "")
            return mod.startswith(van) if van else True
        for r in sorted(rows, key=rank):
            if r.Enabled and r.CaptureView and r.CameraSerialNumber:
                res.cameras[r.CaptureView.replace(" ", "").upper()] = CameraRow(
                    r.CaptureView, str(r.CameraSerialNumber).strip(), int(r.CCDWidth or 0), int(r.CCDHeight or 0))
        if not res.cameras:
            res.error = f"{res.where} has no enabled cameras in VideoDeviceConfig."
        return res
    return DbResult(error="Could not read the van database - " + "; ".join(errors) + ". Type the serial.")


def test_connection(server: str, database: str, settings: dict) -> str:
    """'' if it works, else why (for the Database... dialog)."""
    try:
        con = _connect(server, database, settings)
        n = con.cursor().execute("SELECT COUNT(*) FROM VideoDeviceConfig").fetchone()[0]
        con.close()
        return "" if n else "Connected, but VideoDeviceConfig is empty."
    except Exception as exc:  # noqa: BLE001
        return str(exc).splitlines()[0]
