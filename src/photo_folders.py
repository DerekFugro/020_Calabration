"""photo_folders.py — which folders a calibration's photos came from, for every report."""

from __future__ import annotations

from pathlib import Path

from src.not_used import NOT_USED_DIR

_IMG = {".jpg", ".jpeg", ".png"}


def folder_summary(cal_result, image_folder) -> dict:
    """image_folder, NotUsed folder, and photo counts (used / left out / moved)."""
    folder = Path(image_folder).resolve() if image_folder else None
    used = int(getattr(cal_result, "image_count_used", 0))
    left = len(getattr(cal_result, "auto_removed", []) or [])
    out = {"image_folder": str(folder) if folder else "", "photos_used": used,
           "photos_left_out_automatically": left, "not_used_folder": "", "photos_in_not_used": 0}
    if folder is not None:
        nu = folder / NOT_USED_DIR
        if nu.is_dir():
            out["not_used_folder"] = str(nu)
            out["photos_in_not_used"] = sum(1 for p in nu.iterdir() if p.suffix.lower() in _IMG)
    return out


def folder_lines(cal_result, image_folder) -> list[str]:
    s = folder_summary(cal_result, image_folder)
    lines = [f"Image folder: {s['image_folder'] or '(not recorded)'}",
             f"Photos: {s['photos_used']} used, {s['photos_left_out_automatically']} left out automatically"
             + (f", {s['photos_in_not_used']} in NotUsed" if s["not_used_folder"] else "")]
    if s["not_used_folder"]:
        lines.append(f"NotUsed folder: {s['not_used_folder']}  (why.txt lists each photo)")
    return lines
