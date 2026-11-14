"""bitflow.py - a GOX (JAI CoaXPress) camera on the BitFlow card as a Capture frame source.

Phase 9 (Derek, 2026-11-14):
  * Open the board with the camera setup already loaded in BitFlow SysReg.
  * On a van the camera waits for the external trigger.  While Capture has it, the
    FrameStart trigger is switched Off (free run); on close the trigger settings found at
    open are put back, so ARAN finds the camera as it left it.  Nothing else is changed
    (exposure and frame rate stay as they are).
  * Refuse while ARAN's "FR Video Service" is running: it may hold the board.
  * Only open a board Windows lists: opening a board that isn't there pops up a BitFlow
    "Internal SDK Error" dialog that waits for a click (bench, 2026-11-14).
  * Frames come as Bayer; the camera's "BayerRG" is OpenCV's BayerBG (checked by eye on
    the GOX, docs/capture/bench_results.md).  More than 8 bits is scaled down to 8.
Copied and trimmed from Derek's DP_CXP app (G:\\DP\\Camera_Apps\\DP_CXP, his permission):
the DLL folders before importing BFModule, the TLParamsLocked unlock, the close order.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from src.capture.source import OpenResult

SDK_ROOT = Path(os.environ.get("SURVEYOR_BITFLOW_SDK", r"C:\BitFlow SDK 6.5"))
SERVICE = "FR Video Service"
WAIT_MS = 500
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# camera Bayer name -> OpenCV conversion (OpenCV names the pattern one pixel over)
_BAYER = {"RG": "COLOR_BayerBG2BGR", "BG": "COLOR_BayerRG2BGR",
          "GR": "COLOR_BayerGB2BGR", "GB": "COLOR_BayerGR2BGR"}


def is_bitflow_port(port: str) -> bool:
    """Database ports for the CoaXPress card look like '0-GOX-16205C-CXP'."""
    p = (port or "").upper()
    return "CXP" in p or "GOX" in p


def board_number(port: str) -> int:
    m = re.match(r"\s*(\d+)\s*-", port or "")
    return int(m.group(1)) if m else 0


def _run(cmd: list[str], timeout: float = 15) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


@lru_cache(maxsize=1)
def boards_on_pc() -> int:
    """How many BitFlow boards Windows lists (PCI vendor 118D)."""
    out = _run(["powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_PnPEntity -Filter \"PNPDeviceID like 'PCI\\\\VEN_118D%'\" "
                "| Measure-Object).Count"])
    try:
        return int(out.strip() or 0)
    except ValueError:
        return 0


def sdk_present() -> bool:
    return (SDK_ROOT / "Bin64").is_dir()


def support(port: str) -> tuple[bool, str]:
    """(can Capture open it on this PC, why not in plain words)."""
    if not sdk_present():
        return False, "BitFlow camera: the BitFlow SDK is not installed on this PC."
    n = board_number(port)
    if n >= boards_on_pc():
        return False, f"BitFlow camera: board {n} is not on this PC."
    return True, ""


def video_service_running() -> bool:
    return "RUNNING" in _run(["sc", "query", SERVICE]).upper()


def load_genicam_settings() -> None:
    """The machine's GENICAM_* settings, if this process lacks them.  Without them the
    camera's GenICam layer fails and it looks like 'no camera responded'."""
    if sys.platform != "win32":
        return
    import winreg
    key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                if name.upper().startswith("GENICAM") and name not in os.environ:
                    os.environ[name] = str(value)
                i += 1
    except OSError:
        pass


def import_bfmodule():
    for sub in ("Bin64", "CLSerial64"):
        d = SDK_ROOT / sub
        if d.is_dir() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(d))
    import BFModule  # noqa: PLC0415  (BitFlow's Python module, from the SDK's wheel)
    return BFModule


def to_bgr(raw: np.ndarray, width: int, height: int, pixel_format: str) -> np.ndarray:
    """One BitFlow buffer -> 8-bit BGR picture."""
    import cv2
    m = re.match(r"(Bayer(RG|BG|GR|GB)|Mono)(\d+)", pixel_format or "")
    bits = int(m.group(3)) if m else 8
    flat = np.asarray(raw).view(np.uint8).reshape(-1)
    if bits <= 8:
        img = flat[: width * height].reshape(height, width)
    else:
        img = (flat[: width * height * 2].view("<u2").reshape(height, width) >> (bits - 8)).astype(np.uint8)
    if m and m.group(2):
        return cv2.cvtColor(img, getattr(cv2, _BAYER[m.group(2)]))
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


class BitFlowSource:
    """FrameSource for one BitFlow board.  open/read/close all run on the GrabWorker thread."""

    def __init__(self, board: int = 0, camera: str = "", buffers: int = 4) -> None:
        self.board, self.camera, self.buffers = board, camera, buffers
        self._ciraq = self._dev = self._gtl = self._buf = self._bufs = None
        self._restore: list[tuple[str, str]] = []
        self.width = self.height = 0
        self.pixel_format = ""

    # --- GenICam helpers -------------------------------------------------------------------
    def _enum(self, name: str) -> str:
        return self._gtl.EnumerationNode(self._dev.getNode(name)).EntrySymbolic

    def _set_enum(self, name: str, value: str) -> None:
        self._gtl.EnumerationNode(self._dev.getNode(name)).EntrySymbolic = value

    def _int(self, name: str) -> int:
        return int(self._gtl.IntegerNode(self._dev.getNode(name)).IntValue)

    def _locked(self, v: int) -> None:
        self._gtl.IntegerNode(self._dev.getNode("TLParamsLocked")).IntValue = v

    def _command(self, name: str) -> None:
        try:
            self._gtl.CommandNode(self._dev.getNode(name)).Execute()
        except Exception:  # noqa: BLE001 - harmless if not running
            pass

    def _free_run(self) -> None:
        """Remember the FrameStart trigger, then switch it Off (free run)."""
        self._command("AcquisitionStop")
        self._locked(0)
        try:
            sel = self._enum("TriggerSelector")
            self._set_enum("TriggerSelector", "FrameStart")
            mode = self._enum("TriggerMode")
            self._restore = [("TriggerSelector", "FrameStart"), ("TriggerMode", mode), ("TriggerSelector", sel)]
            if mode != "Off":
                self._set_enum("TriggerMode", "Off")
            self._set_enum("TriggerSelector", sel)
        finally:
            self._locked(1)

    def _put_trigger_back(self) -> None:
        if not self._restore or self._dev is None:
            return
        self._command("AcquisitionStop")
        try:
            self._locked(0)
            for name, value in self._restore:
                self._set_enum(name, value)
        finally:
            try:
                self._locked(1)
            except Exception:  # noqa: BLE001
                pass
        self._restore = []

    # --- FrameSource -----------------------------------------------------------------------
    def open(self, width: int = 0, height: int = 0) -> OpenResult:
        """width/height are ignored: a CoaXPress camera sends its own size (shown, and warned
        about if the database says otherwise)."""
        who = self.camera or "The camera"
        if video_service_running():
            return OpenResult(False, f"ARAN's {SERVICE} is running and may be using the BitFlow card. "
                                     "Stop it first, then press Try again.")
        if self.board >= boards_on_pc():
            return OpenResult(False, f"{who}: BitFlow board {self.board} is not on this PC.")
        load_genicam_settings()
        try:
            bf = import_bfmodule()
        except Exception as exc:  # noqa: BLE001
            from src.capture.errors import log_error
            log_error("import BFModule", exc)
            return OpenResult(False, "The BitFlow Python module is not installed with this copy of Capture.")
        self._buf, self._gtl = bf.BufferAcquisition, bf.BFGTLUtils
        ciraq = self._buf.clsCircularAcquisition()
        try:
            ciraq.Open(self.board)
        except Exception as exc:  # noqa: BLE001
            return OpenResult(False, f"{who}: BitFlow board {self.board} would not open - is a camera set up "
                                     f"for it in BitFlow SysReg, or is another program using it? ({exc})")
        self._ciraq = ciraq
        try:
            self._dev = self._gtl.BFGTLDevice()
            self._dev.Open(ciraq)
        except Exception as exc:  # noqa: BLE001
            self._dev = None
            self.close()
            return OpenResult(False, f"{who}: the BitFlow board opened but the camera did not answer. "
                                     f"Check its power and cable, then press Try again. ({exc})")
        try:
            self.pixel_format = self._enum("PixelFormat")
            self.width, self.height = self._int("Width"), self._int("Height")
            self._free_run()
            self._bufs = ciraq.BufferSetup(self.buffers)
            ciraq.AqSetup(self._buf.SetupOptions.setupDefault)
            ciraq.AqControl(self._buf.AcqCommands.Start, self._buf.AcqControlOptions.Wait)
            self._command("AcquisitionStart")
        except Exception as exc:  # noqa: BLE001
            from src.capture.errors import log_error
            log_error(f"open BitFlow board {self.board}", exc)
            self.close()
            return OpenResult(False, f"{who}: the camera would not start ({exc}).")
        t0 = time.monotonic()
        while time.monotonic() - t0 < 3.0:            # first frame, like the Magewell source
            f = self.read()
            if f is not None:
                return OpenResult(True, "", f.shape[1], f.shape[0])
        self.close()
        return OpenResult(False, f"{who}: no pictures from the camera in 3 seconds. Check its cable.")

    def read(self) -> np.ndarray | None:
        if self._ciraq is None:
            return None
        try:
            cur = self._ciraq.WaitForFrame(WAIT_MS)
        except Exception:  # noqa: BLE001 - timeout
            return None
        return to_bgr(self._bufs[cur.BufferNumber], self.width, self.height, self.pixel_format)

    def close(self) -> None:
        c, self._ciraq = self._ciraq, None
        if c is not None:
            self._command("AcquisitionStop")
            for step in (lambda: c.AqControl(self._buf.AcqCommands.Stop, self._buf.AcqControlOptions.Wait),
                         c.AqCleanup, c.BufferCleanup):
                try:
                    step()
                except Exception:  # noqa: BLE001
                    pass
        try:
            self._put_trigger_back()
        except Exception as exc:  # noqa: BLE001
            from src.capture.errors import log_error
            log_error(f"put the trigger back on BitFlow board {self.board}", exc)
        if self._dev is not None:
            try:
                self._dev.Close()
            except Exception:  # noqa: BLE001
                pass
            self._dev = None
        if c is not None:
            try:
                c.Close()
            except Exception:  # noqa: BLE001
                pass
        self._bufs = None
