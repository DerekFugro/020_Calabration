r"""calibration_store.py — Read from and write to the single calibration store.

Binding rule: `H:\001_Mahine_App_Specs\MasterLeverarms and information.md` §11
and `H:\001_Mahine_App_Specs\Calibrations\README.md`.

  * ALL calibrations live in one place — apps read from there, never from an
    app-local copy, and never from a hard-coded value.
  * Layout is ONE FOLDER PER CALIBRATION EVENT:

        Calibrations\
          YYYYMMDD[_HHMMSS]_<Type>\    <- effective datetime + type
            <ROLE>_<SERIAL>.yaml       <- the calibration itself

    The TYPE NAME SAYS WHICH CAMERA (master doc v1.4, §11): intrinsics are
    split per camera into `PaveIntrinsic` and `ROWIntrinsic`.  That makes the
    store's selection rule — newest folder of the matching Type — unambiguous
    without opening anything, because cameras are calibrated one at a time.

    Type names are owner-defined and are used VERBATIM, including their mixed
    capitalisation.  This app never invents one: a role with no type on the
    master list cannot be published (bench runs stay local).
  * ONLY A PASSING CALIBRATION MAY BE PUBLISHED.  The store is append-only, so
    a bad calibration published once is there forever and someone will
    eventually process against it.  A failed run stays next to its images.
  * The store is APPEND-ONLY.  A superseded calibration is never overwritten or
    deleted; it documents what was in force at the time.  A wrong folder gets a
    `.VOID` suffix plus an `Issues.md` entry — done by the owners, not an app.
  * Selection: the newest folder of the matching Type whose stamp is
    **<= the collection's start time**, not the newest folder outright.

This module only ever CREATES.  It never edits, overwrites, or removes anything
already in the store.

The app keeps writing its own `CAL_<serial>_<datetime>.yaml` + `.pdf` pair into
the image folder as the working record; `publish()` copies the YAML into the
store under the store's own layout.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

# ── Store location ───────────────────────────────────────────────────────────
# Override for testing or for a machine with a different drive letter.
DEFAULT_STORE_PATH = Path(r"F:\Sidewalk\002_App\SidewalkProfilier\100_AllCalibrations")
STORE_PATH_ENV_VAR = "CALIBRATION_STORE"

# Owner-defined type names, master doc §11 / Calibrations\README.md (v1.4).
# Verbatim — note `PaveIntrinsic` vs `ROWIntrinsic` capitalisation; do not
# "tidy" these, they are the folder names on disk.
INTRINSIC_TYPES: dict[str, str] = {
    "PAVE": "PaveIntrinsic",
    "ROW":  "ROWIntrinsic",
}

# Owners VOID a bad folder by appending this suffix; it must never be selected.
VOID_MARKER = ".VOID"

_ROLE_RE   = re.compile(r"^[A-Z0-9][A-Z0-9-]*$")
_SERIAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")

# `20260815_PaveIntrinsic`, `20260815_202357_ROWIntrinsic`.  Types never contain
# `_` (they use hyphens or run together: DMI-Gain, Laser-XScale, Camera-Mount,
# Rev-runBoresight), so any `_` after the type starts an optional subject.
_FOLDER_RE = re.compile(
    r"^(?P<date>\d{8})(?:_(?P<time>\d{6}))?_(?P<type>[^_]+)(?:_(?P<subject>.+))?$"
)


class StoreError(RuntimeError):
    """Raised when a calibration cannot be published to the store."""


# ══════════════════════════════════════════════════════════════════════════════
#  Location
# ══════════════════════════════════════════════════════════════════════════════

def store_path() -> Path:
    """Return the calibration store folder (env var wins, else the default)."""
    return Path(os.environ.get(STORE_PATH_ENV_VAR) or DEFAULT_STORE_PATH)


def store_available(store: Path | None = None) -> bool:
    """True if the store folder exists and can be listed."""
    folder = Path(store) if store is not None else store_path()
    try:
        return folder.is_dir()
    except OSError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Naming
# ══════════════════════════════════════════════════════════════════════════════

def normalise_role(role: str) -> str:
    """Upper-case a role and turn spaces/underscores into hyphens.

    'Pave' -> 'PAVE';  'row camera' -> 'ROW-CAMERA'
    """
    cleaned = re.sub(r"[\s_]+", "-", str(role).strip()).upper()
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned


def validate_subject(role: str, serial: str) -> tuple[str, str]:
    """Validate role + serial, returning the normalised pair.

    A typo here becomes a permanent filename in an append-only store, so this
    is deliberately strict (see the CAL_2345000499 serial-typo entry in the
    master doc's do-not-use list).
    """
    role_norm = normalise_role(role)
    serial_norm = str(serial).strip()

    if not role_norm:
        raise StoreError("Camera role is empty — pick a role (e.g. PAVE or ROW).")
    if not _ROLE_RE.match(role_norm):
        raise StoreError(
            f"Camera role {role_norm!r} is not usable in a filename. "
            "Use letters, digits and hyphens only."
        )
    if not serial_norm:
        raise StoreError("Camera serial is empty.")
    if not _SERIAL_RE.match(serial_norm):
        raise StoreError(
            f"Camera serial {serial_norm!r} is not usable in a filename. "
            "Use letters, digits and hyphens only."
        )
    return role_norm, serial_norm


def check_publishable(yaml_path: str | Path, passed: bool | None = None) -> str:
    """Refuse anything that is not a passing calibration.  Returns "PASS".

    The store is append-only, so two independent checks:

    1. The grade recorded IN THE FILE (src/grading.py), so a caller cannot wave
       a failing calibration through by passing the wrong flag.  A file with no
       grade (made before 2026-10-31) is refused: process the photos again.
    2. *passed* — the run's own pass/fail.  None when the caller has no run.

    Raises StoreError if the calibration did not pass.
    """
    src = Path(yaml_path)
    try:
        data = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise StoreError(f"Could not read the calibration file: {exc}") from None
    tail = "Not published — the local CAL_ files were still written to the image folder."

    grade = data.get("grade") if isinstance(data, dict) else None
    if not isinstance(grade, dict) or "passed" not in grade:
        raise StoreError(
            "The calibration file has no grade, so it cannot be shown to have passed "
            f"(files from before 2026-10-31).  Process the photos again. {tail}")
    if not grade.get("passed"):
        why = "; ".join(str(x) for x in (grade.get("hard_stops") or []) + (grade.get("reasons") or []))
        raise StoreError(
            f"The calibration did not pass its grade: {grade.get('headline', '')} {why} {tail}".strip())
    if passed is False:
        raise StoreError(f"The run did not pass its grade. {tail}")
    return "PASS"


def calibration_type(role: str) -> str:
    """Return the store's Type name for a camera role.

    Raises StoreError for a role the owners have not defined a type for — the
    app must never invent a type name.  Bench or test roles land here on
    purpose: they belong next to the images, not in the shared store.
    """
    role_norm = normalise_role(role)
    if not role_norm:
        raise StoreError("Camera role is empty — pick a role (e.g. PAVE or ROW).")
    try:
        return INTRINSIC_TYPES[role_norm]
    except KeyError:
        known = ", ".join(sorted(INTRINSIC_TYPES))
        raise StoreError(
            f"No calibration-store type is defined for role {role_norm!r}, so "
            f"this calibration cannot be published. Known roles: {known}. "
            "The local CAL_ files were still written. To publish this camera, "
            "ask the owners to add a type to Calibrations\\README.md first."
        ) from None


def event_folder_name(dt: datetime, role: str) -> str:
    """`YYYYMMDD_HHMMSS_PaveIntrinsic` — the calibration event's folder.

    Seconds are always written so two calibration events on one day cannot
    collide in an append-only store.  The type name identifies the camera, so
    no reader has to open the folder to learn what it covers.

    Date-only folders (the 2026-08-15 fresh-start baseline) are READ correctly
    and take effect at midnight — see parse_event_folder.
    """
    return f"{dt.strftime('%Y%m%d_%H%M%S')}_{calibration_type(role)}"


def subject_filename(role: str, serial: str, ext: str = ".yaml") -> str:
    """`<ROLE>_<SERIAL>.yaml` — the file inside the event folder."""
    role_norm, serial_norm = validate_subject(role, serial)
    return f"{role_norm}_{serial_norm}{ext}"


def parse_event_folder(name: str) -> tuple[datetime, str, str] | None:
    """Split a store folder name into (effective datetime, type, subject).

    *subject* is "" for folders that carry no role — the 2026-08-15 baseline
    and the subject-less types (DMI-Gain, Laser-XScale, Camera-Mount).

    Returns None if the name is not a calibration event folder, or if it has
    been VOIDed by the owners.  A date-only stamp takes effect at midnight.

    The `.VOID` check is explicit on purpose: with a role in the folder name
    the marker lands in the SUBJECT field, where it would no longer disqualify
    the folder by accident.
    """
    if VOID_MARKER in name.upper():
        return None

    m = _FOLDER_RE.match(name)
    if not m:
        return None
    stamp = m.group("date") + (m.group("time") or "000000")
    try:
        dt = datetime.strptime(stamp, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return dt, m.group("type"), m.group("subject") or ""


# ══════════════════════════════════════════════════════════════════════════════
#  Read — the selection rule
# ══════════════════════════════════════════════════════════════════════════════

def find_latest(
    role: str,
    serial: str,
    at: datetime | None = None,
    store: str | Path | None = None,
) -> Path | None:
    """Return the calibration in force for this camera at time *at*.

    Implements the store's selection rule: the NEWEST folder of this camera's
    Type (`PaveIntrinsic` / `ROWIntrinsic`) whose effective stamp is <= *at*.
    The file inside is checked too, so a folder that exists but is empty or
    holds a different serial is skipped rather than silently returned.

    *at* defaults to now; pass the collection's start time when reprocessing.
    Returns None if this camera has no calibration in force.
    """
    folder = Path(store) if store is not None else store_path()
    if not store_available(folder):
        return None

    wanted = subject_filename(role, serial)
    wanted_type = calibration_type(role)
    cutoff = at or datetime.now()

    best: tuple[datetime, Path] | None = None
    for child in folder.iterdir():
        if not child.is_dir():
            continue
        parsed = parse_event_folder(child.name)
        if parsed is None:
            continue
        eff, ftype, _subject = parsed
        if ftype != wanted_type or eff > cutoff:
            continue
        candidate = child / wanted
        if candidate.is_file() and (best is None or eff > best[0]):
            best = (eff, candidate)

    return best[1] if best else None


# ══════════════════════════════════════════════════════════════════════════════
#  Write
# ══════════════════════════════════════════════════════════════════════════════

def publish(
    yaml_path: str | Path,
    role: str,
    serial: str,
    dt: datetime,
    store: str | Path | None = None,
    passed: bool | None = None,
) -> Path:
    """Copy a PASSING calibration YAML into the store.

    Creates `<store>\\YYYYMMDD_HHMMSS_<Type>\\<ROLE>_<SERIAL>.yaml`, where
    Type is this camera's owner-defined type name (e.g. `PaveIntrinsic`).
    *dt* is the calibration datetime — it becomes the folder's effective stamp,
    so it must be the SAME datetime used for the local `CAL_*` files.

    Each camera gets its own folder, named for it by type.  Replacing a file
    that is already there is refused — the store is append-only.

    *passed* is the run's own pass/fail (its grade).  A failed
    calibration is refused here and stays next to its images; see
    check_publishable.

    Returns the path of the new file in the store.
    """
    src = Path(yaml_path)
    if not src.is_file():
        raise StoreError(f"Calibration file not found: {src}")

    # Quality gate first: a failed run must never reach an append-only store.
    check_publishable(src, passed)

    # Resolve names BEFORE touching the store, so a bad role or serial fails on
    # its own terms instead of hiding behind an offline drive.
    name = subject_filename(role, serial, src.suffix or ".yaml")
    folder_name = event_folder_name(dt, role)

    root = Path(store) if store is not None else store_path()
    if not store_available(root):
        raise StoreError(
            f"Calibration store not reachable: {root}\n"
            "The local CAL_ files were still written to the image folder. "
            "Reconnect the drive and publish again, or copy the YAML in by hand."
        )
    event_dir = root / folder_name
    target = event_dir / name

    if target.exists():
        raise StoreError(
            f"{folder_name}\\{name} already exists. The store is "
            "append-only — an existing calibration is never overwritten. "
            "Ask the owners to VOID it if it is wrong."
        )

    event_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target
