"""magewell.py - what the camera really sends into a Magewell Pro Capture input (Phase 7).

Read only, through Magewell's own LibMWCapture.dll (installed with the driver in System32):
init, refresh, channel info, open the channel, read its video signal status, close, exit.
Never calls a setter (no firmware, EDID, LED, input source, scaling).

Broadcast cameras send whatever they are set to (1K or 4K, 30 - 60 frames/s); the card then
scales the picture to the size asked for.  This tells Capture the camera's own size and
frame rate, so a database (ACS) size that makes the card upscale or downscale can be shown.

The struct layout is packed (1 byte), checked 2026-11-14 on ARAN59 (driver 1.3.0.4323):
ROW 01-0 gave state 3 (locked), 1920 x 1080, total 2200 x 1125, interlaced, frame duration
333667 x 100 ns = 29.97 frames/s, aspect 16:9.  Any problem -> None (Capture carries on).
"""

from __future__ import annotations

import ctypes
import re
import threading
from dataclasses import dataclass

DLL = r"C:\Windows\System32\LibMWCapture.dll"
STATES = {0: "no signal", 1: "unsupported signal", 2: "locking", 3: "locked"}

# MWCAP_CHANNEL_INFO (packed): offsets of the fields used
_INFO_SIZE, _INFO_BOARD, _INFO_CHANNEL = 512, 222, 223
_lock = threading.Lock()                      # the DLL instance is process wide: one user at a time


class _SignalStatus(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("state", ctypes.c_int32), ("x", ctypes.c_int32), ("y", ctypes.c_int32),
                ("cx", ctypes.c_int32), ("cy", ctypes.c_int32),
                ("cxTotal", ctypes.c_int32), ("cyTotal", ctypes.c_int32),
                ("bInterlaced", ctypes.c_uint8), ("dwFrameDuration", ctypes.c_uint32),
                ("nAspectX", ctypes.c_int32), ("nAspectY", ctypes.c_int32),
                ("bSegmentedFrame", ctypes.c_uint8), ("frameType", ctypes.c_int32),
                ("colorFormat", ctypes.c_int32), ("quantRange", ctypes.c_int32),
                ("satRange", ctypes.c_int32), ("_spare", ctypes.c_uint8 * 64)]


@dataclass
class CameraSignal:
    state: str                 # "locked", "no signal", ...
    width: int = 0
    height: int = 0
    fps: float = 0.0           # frames per second (29.97, 59.94, ...)
    interlaced: bool = False

    @property
    def locked(self) -> bool:
        return self.state == "locked" and self.width > 0 and self.height > 0

    def text(self) -> str:
        """e.g. '1920 x 1080i at 29.97 frames/s'"""
        if not self.locked:
            return self.state
        return f"{self.width} x {self.height}{'i' if self.interlaced else ''} at {self.fps:.2f} frames/s"


def board_channel(port: str) -> tuple[int, int] | None:
    """'Video (01-0 Pro Capture Dual SDI 4K+)' -> (1, 0); None if not a Magewell input name."""
    m = re.search(r"\((\d+)-(\d+)\s+Pro Capture", port or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def decode_status(raw: bytes) -> CameraSignal:
    """The DLL's MWCAP_VIDEO_SIGNAL_STATUS bytes -> CameraSignal."""
    s = _SignalStatus.from_buffer_copy(raw.ljust(ctypes.sizeof(_SignalStatus), b"\0")[:ctypes.sizeof(_SignalStatus)])
    state = STATES.get(s.state, f"signal state {s.state}")
    fps = 1e7 / s.dwFrameDuration if s.dwFrameDuration else 0.0
    return CameraSignal(state, max(0, s.cx), max(0, s.cy), round(fps, 2), bool(s.bInterlaced))


def _load():
    dll = ctypes.WinDLL(DLL)
    dll.MWCaptureInitInstance.restype = ctypes.c_int
    dll.MWCaptureExitInstance.restype = None
    dll.MWRefreshDevice.restype = ctypes.c_int
    dll.MWGetChannelCount.restype = ctypes.c_int
    dll.MWGetChannelInfoByIndex.argtypes = [ctypes.c_int, ctypes.c_void_p]
    dll.MWGetChannelInfoByIndex.restype = ctypes.c_int
    dll.MWGetDevicePath.argtypes = [ctypes.c_int, ctypes.c_wchar_p]
    dll.MWGetDevicePath.restype = ctypes.c_int
    dll.MWOpenChannelByPath.argtypes = [ctypes.c_wchar_p]
    dll.MWOpenChannelByPath.restype = ctypes.c_void_p
    dll.MWGetVideoSignalStatus.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.MWGetVideoSignalStatus.restype = ctypes.c_int
    dll.MWCloseChannel.argtypes = [ctypes.c_void_p]
    dll.MWCloseChannel.restype = None
    return dll


def camera_signal(port: str) -> CameraSignal | None:
    """What the camera on this Magewell input sends, or None (not Magewell, no DLL, any error)."""
    bc = board_channel(port)
    if bc is None:
        return None
    try:
        with _lock:
            dll = _load()
            if not dll.MWCaptureInitInstance():
                return None
            try:
                dll.MWRefreshDevice()
                for i in range(dll.MWGetChannelCount()):
                    info = ctypes.create_string_buffer(_INFO_SIZE)
                    if dll.MWGetChannelInfoByIndex(i, info) != 0:
                        continue
                    if (info.raw[_INFO_BOARD], info.raw[_INFO_CHANNEL]) != bc:
                        continue
                    path = ctypes.create_unicode_buffer(512)
                    if dll.MWGetDevicePath(i, path) != 0:
                        return None
                    h = dll.MWOpenChannelByPath(path.value)
                    if not h:
                        return None
                    try:
                        st = _SignalStatus()
                        if dll.MWGetVideoSignalStatus(h, ctypes.byref(st)) != 0:
                            return None
                        return decode_status(bytes(st))
                    finally:
                        dll.MWCloseChannel(h)
                return None
            finally:
                dll.MWCaptureExitInstance()
    except Exception as exc:  # noqa: BLE001 - never stop Capture over this
        try:
            from src.capture.errors import log_error
            log_error(f"Magewell signal for {port}", exc)
        except Exception:  # noqa: BLE001
            pass
        return None
