"""Tests for src/raw_loader.py — sidecar handling, decoding, idempotent batch."""

import json

import cv2
import numpy as np
import pytest

from src.raw_loader import (
    RawDecodeError,
    convert_folder,
    decode_raw,
    find_raws,
    pending_conversions,
)


def _write_rgb8(tmp_path, name="a.raw", w=8, h=4, sidecar="lucid"):
    """Small RGB8 raw + sidecar. sidecar: 'lucid' (.raw.json), 'logger' (.json),
    or None."""
    raw = tmp_path / name
    raw.write_bytes(b"\x80" * (w * h * 3))
    meta = {"width": w, "height": h}
    if sidecar == "lucid":
        meta["pixelformat"] = "RGB8"
        (tmp_path / (name + ".json")).write_text(json.dumps(meta))
    elif sidecar == "logger":
        meta["pixel_format"] = "RGB8"
        (tmp_path / (name.rsplit(".", 1)[0] + ".json")).write_text(json.dumps(meta))
    return raw


class TestDecode:
    def test_rgb8_with_lucid_sidecar(self, tmp_path):
        raw = _write_rgb8(tmp_path, sidecar="lucid")
        img = decode_raw(str(raw))
        assert img.shape == (4, 8, 3) and img.dtype == np.uint8

    def test_rgb8_with_logger_sidecar(self, tmp_path):
        raw = _write_rgb8(tmp_path, sidecar="logger")
        img = decode_raw(str(raw))
        assert img.shape == (4, 8, 3)

    def test_bayer24_decodes_and_demosaics(self, tmp_path):
        w, h = 8, 4
        px = bytes([0x56, 0x34, 0x12])  # 24-bit LE → high byte 0x12
        raw = tmp_path / "b.raw"
        raw.write_bytes(px * (w * h))
        (tmp_path / "b.raw.json").write_text(
            json.dumps({"width": w, "height": h, "pixelformat": "BayerRG24"})
        )
        img = decode_raw(str(raw))
        assert img.shape == (h, w, 3) and img.dtype == np.uint8
        assert int(img.min()) == int(img.max()) == 0x12  # uniform in → uniform out

    def test_size_mismatch_raises(self, tmp_path):
        raw = tmp_path / "c.raw"
        raw.write_bytes(b"\x00" * 10)
        (tmp_path / "c.raw.json").write_text(
            json.dumps({"width": 8, "height": 4, "pixelformat": "RGB8"})
        )
        with pytest.raises(RawDecodeError):
            decode_raw(str(raw))

    def test_unsupported_format_raises(self, tmp_path):
        raw = _write_rgb8(tmp_path, sidecar=None)
        (tmp_path / "a.raw.json").write_text(
            json.dumps({"width": 8, "height": 4, "pixelformat": "Mono12p"})
        )
        with pytest.raises(RawDecodeError):
            decode_raw(str(raw))


class TestBatch:
    def test_convert_folder_writes_pngs(self, tmp_path):
        _write_rgb8(tmp_path, "a.raw")
        _write_rgb8(tmp_path, "b.raw")
        converted, failed = convert_folder(str(tmp_path))
        assert len(converted) == 2 and failed == []
        assert (tmp_path / "a.png").exists() and (tmp_path / "b.png").exists()
        assert cv2.imread(str(tmp_path / "a.png")) is not None

    def test_idempotent_skips_existing_png(self, tmp_path):
        _write_rgb8(tmp_path, "a.raw")
        convert_folder(str(tmp_path))
        assert pending_conversions(str(tmp_path)) == []
        converted, failed = convert_folder(str(tmp_path))
        assert converted == [] and failed == []

    def test_bad_file_reported_not_raised(self, tmp_path):
        _write_rgb8(tmp_path, "good.raw")
        (tmp_path / "bad.raw").write_bytes(b"\x00" * 7)  # wrong size, no sidecar
        converted, failed = convert_folder(str(tmp_path))
        assert len(converted) == 1
        assert len(failed) == 1 and "bad.raw" in failed[0]

    def test_find_raws_sorted_nonrecursive(self, tmp_path):
        _write_rgb8(tmp_path, "z.raw")
        _write_rgb8(tmp_path, "a.raw")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.raw").write_bytes(b"\x00")
        raws = find_raws(str(tmp_path))
        assert [r.split("\\")[-1].split("/")[-1] for r in raws] == ["a.raw", "z.raw"]

    def test_progress_callback_called(self, tmp_path):
        _write_rgb8(tmp_path, "a.raw")
        messages = []
        convert_folder(str(tmp_path), progress_cb=messages.append)
        assert messages and "1/1" in messages[0]
