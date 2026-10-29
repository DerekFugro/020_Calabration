"""raw_loader.py — Detect Lucid .raw frames in the image folder and convert
them to PNGs the detection pipeline can read.

Frame geometry/format comes from the per-frame JSON sidecar when present:
  - Lucid tools (ArenaView "save raw"):  <name>.raw.json  with key "pixelformat"
  - LucidCameraLogger sidecars:          <name>.json      with key "pixel_format"
Falls back to DEFAULT_* (TDR054S: 2880x1860 RGB8) when no sidecar exists.

Supported pixel formats:
  - RGB8      — interleaved 8-bit (TDR054S on-camera tone-map): direct.
  - BayerRG24 — 24-bit packed little-endian (TRI054S): unpack → 16-bit →
                cv2 demosaic (COLOR_BayerRG2BGR) → 8-bit.
  - Mono8     — single channel, direct.

Conversion is idempotent: a .raw whose .png already exists is skipped.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Callable, Optional

import cv2
import numpy as np

DEFAULT_WIDTH = 2880
DEFAULT_HEIGHT = 1860
DEFAULT_PIXEL_FORMAT = "RGB8"


class RawDecodeError(Exception):
    """A .raw file could not be decoded to an image."""


def _sidecar_meta(raw_path: str) -> dict:
    """Return sidecar metadata for *raw_path*, or {} when none exists."""
    stem, _ = os.path.splitext(raw_path)
    for candidate in (raw_path + ".json", stem + ".json"):
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


def decode_raw(raw_path: str) -> np.ndarray:
    """Decode one .raw file to an 8-bit BGR (or mono) array.

    Raises RawDecodeError on unknown format or size mismatch.
    """
    meta = _sidecar_meta(raw_path)
    width = int(meta.get("width", DEFAULT_WIDTH))
    height = int(meta.get("height", DEFAULT_HEIGHT))
    fmt = str(meta.get("pixel_format") or meta.get("pixelformat")
              or DEFAULT_PIXEL_FORMAT)

    with open(raw_path, "rb") as f:
        data = f.read()

    def _check(expected: int) -> None:
        if len(data) != expected:
            raise RawDecodeError(
                f"{os.path.basename(raw_path)}: payload {len(data)} bytes != "
                f"expected {expected} for {fmt} {width}x{height}"
            )

    if fmt == "RGB8":
        _check(width * height * 3)
        rgb = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    if fmt == "BayerRG24":
        _check(width * height * 3)
        b = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
        b = b.astype(np.uint32)
        val24 = b[:, :, 0] | (b[:, :, 1] << 8) | (b[:, :, 2] << 16)
        bayer16 = (val24 >> 8).astype(np.uint16)
        bgr16 = cv2.cvtColor(bayer16, cv2.COLOR_BayerRG2BGR)
        return (bgr16 >> 8).astype(np.uint8)

    if fmt == "Mono8":
        _check(width * height)
        return np.frombuffer(data, dtype=np.uint8).reshape(height, width).copy()

    raise RawDecodeError(
        f"{os.path.basename(raw_path)}: unsupported pixel format {fmt!r}"
    )


def _png_path(raw_path: str) -> str:
    stem, _ = os.path.splitext(raw_path)
    return stem + ".png"


def find_raws(folder: str) -> list[str]:
    """Sorted list of .raw files in *folder* (non-recursive)."""
    return sorted(glob.glob(os.path.join(folder, "*.raw")))


def pending_conversions(folder: str) -> list[str]:
    """The .raw files in *folder* that do not have a .png yet."""
    return [r for r in find_raws(folder) if not os.path.isfile(_png_path(r))]


def convert_folder(
    folder: str,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[list[str], list[str]]:
    """Convert every pending .raw in *folder* to a PNG alongside it.

    Returns (converted_png_paths, failed_messages). Failures never raise —
    they are reported so a bad frame can't block the rest of the batch.
    """
    pending = pending_conversions(folder)
    converted: list[str] = []
    failed: list[str] = []
    for i, raw in enumerate(pending, start=1):
        if progress_cb is not None:
            progress_cb(f"Converting raw image {i}/{len(pending)}…")
        try:
            img = decode_raw(raw)
            png = _png_path(raw)
            if not cv2.imwrite(png, img):
                raise RawDecodeError(f"cv2.imwrite failed for {png}")
            converted.append(png)
        except Exception as exc:  # noqa: BLE001 - collect, don't abort the batch
            failed.append(f"{os.path.basename(raw)}: {exc}")
    return converted, failed
