"""utils.py — Shared utility functions with no GUI dependencies."""

from __future__ import annotations

import glob
import os

_IMG_EXTS = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")


def find_images(folder: str) -> list[str]:
    """Return a sorted, de-duplicated list of JPG/PNG paths in *folder* (non-recursive)."""
    paths: set[str] = set()
    for ext in _IMG_EXTS:
        paths.update(glob.glob(os.path.join(folder, ext)))
    return sorted(paths)
