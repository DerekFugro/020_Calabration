"""camera_db.py - read the van's camera serials from its ARAN MS SQL database (read only).

Derek, 2026-11-06.  On a van the database is on <VAN>-SERVER and is named after the
van (ARAN28 on ARAN28-SERVER); on the dev PC a copy sits on this PC (ARAN69 on
localhost).  Table VideoDeviceConfig has one row per camera: CaptureView (ROW,
ForwardLeft, ...), CameraSerialNumber, CCDWidth / CCDHeight (photo size).

Login: Windows sign-in (dev PC), or a SQL login.  A SQL password is never in the code
or the repo: it is kept in Windows' protected store (DPAPI) in the settings folder, so
only this Windows user on this PC can read it back.

Settings (all optional) in %LOCALAPPDATA%\\020_Calabration\\camera_db.json:
  {"server": "", "database": "", "auth": "windows" | "sql", "user": ""}
Blank server -> <VAN>-SERVER, then this PC.  Blank database -> the van name.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

SETTINGS_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "020_Calabration"
SETTINGS = SETTINGS_DIR / "camera_db.json"
SECRET = SETTINGS_DIR / "camera_db.secret"
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

    @property
    def where(self) -> str:
        return f"database {self.database} on {self.server}"


# ── settings and the protected password ──────────────────────────────────────

def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(s: dict) -> None:
    _cache.clear()
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({k: s.get(k, "") for k in ("server", "database", "auth", "user")}, indent=1),
                        encoding="utf-8")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows DPAPI: only this Windows user on this PC can undo it."""
    src = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if protect:
        ok = fn(ctypes.byref(src), "020_Calabration", None, None, None, 0, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError("Windows could not protect / read the stored password.")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def store_password(pw: str) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SECRET.write_text(base64.b64encode(_dpapi(pw.encode("utf-8"), True)).decode("ascii"), encoding="ascii")


def stored_password() -> str:
    try:
        return _dpapi(base64.b64decode(SECRET.read_text(encoding="ascii")), False).decode("utf-8")
    except (OSError, ValueError, AttributeError):
        return ""


# ── connecting and reading ───────────────────────────────────────────────────

def _driver() -> str:
    import pyodbc
    have = pyodbc.drivers()
    for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"):
        if d in have:
            return d
    raise RuntimeError("No SQL Server ODBC driver on this PC (install 'ODBC Driver 18 for SQL Server').")


def _connect(server: str, database: str, s: dict):
    import pyodbc
    cs = (f"DRIVER={{{_driver()}}};SERVER={server};DATABASE={database};"
          "Encrypt=yes;TrustServerCertificate=yes;ApplicationIntent=ReadOnly;")
    if s.get("auth") == "sql":
        pw = stored_password()
        if not pw:
            raise RuntimeError("A SQL login is set but no password is stored on this PC (Database... button).")
        cs += f"UID={s.get('user', '')};PWD={pw};"
    else:
        cs += "Trusted_Connection=yes;"
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
        return f"login refused, or there is no database {database} (check the Database... settings)"
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
        # an exported database can hold rows for several vans: prefer this van's, enabled ones
        def rank(r):
            mod = (r.VideoModuleName or "").upper().replace(" ", "")
            return (bool(r.Enabled), mod.startswith(van) if van else True)
        for r in sorted(rows, key=rank):
            if r.CaptureView and r.CameraSerialNumber:
                res.cameras[r.CaptureView.replace(" ", "").upper()] = CameraRow(
                    r.CaptureView, str(r.CameraSerialNumber).strip(), int(r.CCDWidth or 0), int(r.CCDHeight or 0))
        if not res.cameras:
            res.error = f"{res.where} has no cameras in VideoDeviceConfig."
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
