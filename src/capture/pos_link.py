"""pos_link.py - Capture's link to the POS logger (Phase 8, Old School collection).

The POS logger is Derek's POS PPK Processor (repo POSProcessing).  Installed (the normal
case): C:\\Program Files\\Fugro Roadware\\ACSApps\\POSProcessing\\POSProcessing.exe; on a
development PC its source folder (E:\\DP\\POSProcessor, .venv pythonw.exe app.py) is used when no
install is found.  Capture starts it as a child process with pipes; the two exchange one JSON object per line
(its docs/Comunication4OtherApps.md, protocol 2).  It records the POS LV while Capture
is open; at each Old School position Capture sends `mark` with the position's folder and
the POS logger writes 5 minutes of POS navigation into that folder, then sends `mark_done`
with a summary that rates the position.

Rules from its docs: read its output all the time (a full pipe blocks it); close it with
`quit` and wait up to ~10 s for `bye`; kill it only as a last resort (the last part of
the current file may be lost).  No Qt here: the Capture window polls `messages`.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

POS_INSTALLED = r"C:\Program Files\Fugro Roadware\ACSApps\POSProcessing"
POS_SOURCE = r"E:\DP\POSProcessor"          # development PC only
EXE = "POSProcessing.exe"
NEED_PROTOCOL = 2              # 2 = mark into a given folder + mark summaries
LOGGING_WAIT_S = 30.0          # hello + logging should come within this
REPLY_WAIT_S = 10.0
BYE_WAIT_S = 10.0
HEARTBEAT_LOST_S = 180.0       # heartbeat every 60 s; none for 3 minutes = the POS app is gone
MARK_SECONDS = 300.0           # Derek 2026-11-15: 5 minutes per position

HELP = "Call for help."


class PosError(Exception):
    """A problem the crew is told about in one plain sentence."""


@dataclass
class PosStatus:
    logging: bool = False
    light: str = "grey"
    message: str = ""
    detail: str = ""
    ok_to_collect: bool = False
    session_folder: str = ""
    warnings: list = field(default_factory=list)

    @classmethod
    def from_msg(cls, d: dict) -> "PosStatus":
        return cls(logging=bool(d.get("logging")), light=str(d.get("light") or "grey"),
                   message=str(d.get("message") or ""), detail=str(d.get("detail") or ""),
                   ok_to_collect=bool(d.get("ok_to_collect")),
                   session_folder=str(d.get("session_folder") or ""),
                   warnings=list(d.get("warnings") or []))


@dataclass
class MarkResult:
    """One position's POS data: what `mark_done` (or a `closed_marks` entry) says."""
    mark: int
    label: str
    file: str = ""
    seconds: float | None = None
    rows: int = 0
    complete: bool = False
    green_whole_time: bool = False
    worst_light: str = ""
    worst_message: str = ""
    max_rms_m: tuple = (None, None, None)        # north, east, down
    spread_deg: tuple = (None, None, None)       # roll, pitch, heading
    time_type: str = ""
    first_time1_s: float | None = None
    last_time1_s: float | None = None

    @classmethod
    def from_msg(cls, d: dict) -> "MarkResult":
        return cls(mark=int(d.get("mark") or 0), label=str(d.get("label") or ""),
                   file=str(d.get("file") or ""), seconds=d.get("seconds"),
                   rows=int(d.get("rows") or 0), complete=bool(d.get("complete")),
                   green_whole_time=bool(d.get("green_whole_time")),
                   worst_light=str(d.get("worst_light") or ""),
                   worst_message=str(d.get("worst_message") or ""),
                   max_rms_m=tuple(d.get(k) for k in ("max_rms_n_m", "max_rms_e_m", "max_rms_d_m")),
                   spread_deg=tuple(d.get(k) for k in ("roll_spread_deg", "pitch_spread_deg",
                                                       "heading_spread_deg")),
                   time_type=str(d.get("time_type") or ""),
                   first_time1_s=d.get("first_time1_s"), last_time1_s=d.get("last_time1_s"))


def app_argv(app_dir: str, out: str) -> list[str]:
    """Installed: POSProcessing.exe (no console window).  Source folder: its own pythonw.exe
    app.py (not launch.bat: it drops the pipes)."""
    exe = os.path.join(app_dir, EXE)
    if os.path.isfile(exe):
        return [exe, "--surveyor", "--out", out]
    return [os.path.join(app_dir, ".venv", "Scripts", "pythonw.exe"), "app.py", "--surveyor", "--out", out]


def find_app() -> str:
    """The installed POS app, else its source folder (development PC), else the install path."""
    if os.path.isfile(os.path.join(POS_INSTALLED, EXE)):
        return POS_INSTALLED
    if os.path.isfile(os.path.join(POS_SOURCE, ".venv", "Scripts", "pythonw.exe")):
        return POS_SOURCE
    return POS_INSTALLED


def command_line(cmd: str, id=None, **fields) -> str:
    d = {"cmd": cmd, **{k: v for k, v in fields.items() if v is not None}}
    if id is not None:
        d["id"] = id
    return json.dumps(d) + "\n"


def parse_line(line: str) -> dict | None:
    """One message, or None for a blank or broken line (logged, never fatal)."""
    line = line.strip()
    if not line:
        return None
    try:
        d = json.loads(line)
    except ValueError:
        return None
    return d if isinstance(d, dict) and "type" in d else None


class PosLink:
    """One POS logger child process.  Thread safe; every call returns or raises PosError.

    `argv` / `cwd` replace the real app (tests use a fake POS logger)."""

    def __init__(self, app_dir: str | None = None, argv: list | None = None, cwd: str | None = None):
        self.app_dir = app_dir or find_app()
        self._argv, self._cwd = argv, cwd
        self.proc: subprocess.Popen | None = None
        self.messages: queue.Queue = queue.Queue()    # every message, for the window
        self.hello: dict | None = None
        self.status = PosStatus()
        self.done_marks: dict[int, MarkResult] = {}
        self.closed_marks: list[MarkResult] = []
        self.start_error = ""
        self.bye = False
        self.killed = False
        self.last_seen = 0.0
        self._replies: dict = {}
        self._next_id = 0
        self._cond = threading.Condition()
        self._write_lock = threading.Lock()
        self._reader: threading.Thread | None = None

    # ---- start --------------------------------------------------------------------------
    def start(self, out: str) -> None:
        """Start the POS logger recording into `out` (it makes SurveyorPOS_<date time> there)."""
        argv = self._argv or app_argv(self.app_dir, out)
        cwd = self._cwd or self.app_dir
        if not os.path.isfile(argv[0]) or not os.path.isdir(cwd):
            raise PosError(f"The POS logging app was not found ({self.app_dir}). {HELP}")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self.proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                         errors="replace", bufsize=1, creationflags=flags)
        except OSError as exc:
            raise PosError(f"The POS logging app could not start ({exc}). {HELP}") from exc
        self.last_seen = time.monotonic()
        self._reader = threading.Thread(target=self._read, name="pos-link", daemon=True)
        self._reader.start()

    def wait_ready(self, timeout: float = LOGGING_WAIT_S) -> PosStatus:
        """Wait for hello (protocol 2 or newer) and the first `logging` message."""
        end = time.monotonic() + timeout
        with self._cond:
            while True:
                if self.start_error:
                    raise PosError(f"The POS logging app could not record: {self.start_error} {HELP}")
                if self.hello is not None and int(self.hello.get("protocol") or 0) < NEED_PROTOCOL:
                    raise PosError("The POS logging app is too old for Old School collection "
                                   f"(protocol {self.hello.get('protocol')}, needs {NEED_PROTOCOL}). {HELP}")
                if self.hello is not None and self.status.logging:
                    return self.status
                if not self.alive:
                    raise PosError(f"The POS logging app closed by itself. {HELP}")
                left = end - time.monotonic()
                if left <= 0:
                    what = self.status.message or "no answer"
                    raise PosError(f"The POS logging app did not start recording in {timeout:.0f} s "
                                   f"({what}). {HELP}")
                self._cond.wait(min(left, 0.2))

    # ---- commands -----------------------------------------------------------------------
    def request(self, cmd: str, timeout: float = REPLY_WAIT_S, **fields) -> dict:
        """Send one command and wait for its reply (a dict with "ok")."""
        with self._cond:
            self._next_id += 1
            rid = self._next_id
        self._send(command_line(cmd, id=rid, **fields))
        end = time.monotonic() + timeout
        with self._cond:
            while rid not in self._replies:
                left = end - time.monotonic()
                if not self.alive and rid not in self._replies:
                    raise PosError(f"The POS logging app closed by itself. {HELP}")
                if left <= 0:
                    raise PosError(f"The POS logging app did not answer ({cmd}). {HELP}")
                self._cond.wait(min(left, 0.2))
            return self._replies.pop(rid)

    def refresh(self) -> PosStatus:
        self.request("status")
        return self.status

    def mark(self, label: str, folder: str, seconds: float = MARK_SECONDS) -> dict:
        """Start a position's POS CSV in `folder` (made by Capture first).  Returns the reply;
        a refusal ("Folder does not exist ...") comes back as ok False with its error."""
        if not os.path.isabs(folder):
            raise ValueError(f"folder must be a full path: {folder}")
        return self.request("mark", label=label, folder=folder, seconds=float(seconds))

    def result(self, mark: int) -> MarkResult | None:
        """The finished mark's summary, or None while it is still recording."""
        with self._cond:
            return self.done_marks.get(mark)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def lost(self) -> bool:
        """No message for 3 minutes (heartbeats come every 60 s), or the app has gone."""
        return not self.alive or time.monotonic() - self.last_seen > HEARTBEAT_LOST_S

    # ---- close --------------------------------------------------------------------------
    def close(self, wait: float = BYE_WAIT_S) -> list[MarkResult]:
        """quit, wait for bye; kill only if it does not exit in time.  Returns the marks cut short."""
        if self.proc is None:
            return []
        if self.alive:
            try:
                self.request("quit", timeout=wait)
            except PosError:
                pass
            try:
                self.proc.stdin.close()               # the app treats closed stdin as quit too
            except OSError:
                pass
            try:
                self.proc.wait(wait)
            except subprocess.TimeoutExpired:
                self.killed = True                    # last resort (its docs)
                self.proc.kill()
                self.proc.wait(5)
        if self._reader is not None:
            self._reader.join(2)
        with self._cond:
            return list(self.closed_marks)

    # ---- inside -------------------------------------------------------------------------
    def _send(self, line: str) -> None:
        if not self.alive:
            raise PosError(f"The POS logging app is not running. {HELP}")
        with self._write_lock:
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
            except (OSError, ValueError) as exc:
                raise PosError(f"The POS logging app is not running. {HELP}") from exc

    def _read(self) -> None:
        for line in self.proc.stdout:
            msg = parse_line(line)
            if msg is None:
                continue
            with self._cond:
                self._take(msg)
                self._cond.notify_all()
            self.messages.put(msg)
        with self._cond:
            self._cond.notify_all()

    def _take(self, m: dict) -> None:
        self.last_seen = time.monotonic()
        kind = m.get("type")
        if kind == "hello":
            self.hello = m
        if kind in ("logging", "heartbeat") or (kind == "reply" and "light" in m):
            self.status = PosStatus.from_msg(m)
        if kind == "mark_done":
            r = MarkResult.from_msg(m)
            self.done_marks[r.mark] = r
        if kind in ("reply", "stopped") and m.get("closed_marks"):
            self.closed_marks = [MarkResult.from_msg(c) for c in m["closed_marks"]]
        if kind == "error" and m.get("cmd") == "start":
            self.start_error = str(m.get("error") or "unknown error")
        if kind == "reply" and "id" in m:
            self._replies[m["id"]] = m
        if kind == "bye":
            self.bye = True
