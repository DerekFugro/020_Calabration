"""not_used.py — move photos that can never be used into a NotUsed subfolder.

Moved (useless in every run):
  * the file can't be read
  * no board / too few points found
  * a different image size from the rest of the set

NOT moved: photos left out for high error or blur.  Those depend on the rest
of the set or on a setting, so they stay in place and are only listed.

Every move is logged in NotUsed/why.txt (file, reason, date).  Nothing is ever
deleted; moving a photo back out of NotUsed undoes it.  find_images() is not
recursive, so later runs skip NotUsed on their own.

Safety: if most of the set looks unusable (wrong board picked, wrong folder),
nothing is moved and the run says so.
"""

from __future__ import annotations

import os
import shutil
from collections import Counter
from datetime import datetime

from src.image_filter import FilterResult

NOT_USED_DIR = "NotUsed"
LOG_NAME = "why.txt"
MAX_SHARE = 0.5          # never move more than half the set


def mark_wrong_size(detections, filter_results) -> None:
    """Reject photos whose size differs from the most common size (in place)."""
    sizes = Counter(tuple(d.image_size) for d in detections
                    if not d.load_error and d.image_size and d.image_size[0])
    if len(sizes) < 2:
        return
    main = sizes.most_common(1)[0][0]
    for i, d in enumerate(detections):
        if d.load_error or not d.image_size or tuple(d.image_size) == main:
            continue
        filter_results[i] = FilterResult(
            accepted=False,
            reason=f"Wrong image size {d.image_size[0]}x{d.image_size[1]} "
                   f"(the set is {main[0]}x{main[1]})",
            corner_count=d.corner_count, blur_score=d.blur_score)


def unusable(detections, filter_results) -> list[tuple[int, str]]:
    """(index, reason) for photos that can never be used."""
    out = []
    for i, (d, f) in enumerate(zip(detections, filter_results)):
        if f.accepted:
            continue
        r = f.reason
        if (d.load_error or r.startswith("Too few") or r.startswith("Wrong image size")):
            if r.startswith("Too few") and d.corner_count == 0:
                r = "No board found"
            out.append((i, r))
    return out


def move_unusable(folder: str, detections, filter_results) -> tuple[list, str]:
    """Move unusable photos to <folder>/NotUsed.  Returns (moved, note).

    moved = [(file name, reason)].  Detection image paths are updated to the
    new place so thumbnails and reports still find the files.
    """
    items = unusable(detections, filter_results)
    if not items:
        return [], ""
    if len(items) > MAX_SHARE * len(detections):
        return [], (f"{len(items)} of {len(detections)} photos look unusable, so none were "
                    "moved. Check the board and the folder.")
    dest = os.path.join(folder, NOT_USED_DIR)
    os.makedirs(dest, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    moved, lines = [], []
    for i, reason in items:
        src = detections[i].image_path
        if os.path.dirname(os.path.abspath(src)) != os.path.abspath(folder) or not os.path.exists(src):
            continue
        name = os.path.basename(src)
        target = os.path.join(dest, name)
        stem, ext = os.path.splitext(name)
        k = 1
        while os.path.exists(target):
            target = os.path.join(dest, f"{stem}_{k}{ext}"); k += 1
        shutil.move(src, target)
        detections[i].image_path = target
        moved.append((os.path.basename(target), reason))
        lines.append(f"{os.path.basename(target)}\t{reason}\t{stamp}")
    if lines:
        log = os.path.join(dest, LOG_NAME)
        new = not os.path.exists(log)
        with open(log, "a", encoding="utf-8") as fh:
            if new:
                fh.write("file\treason\tmoved\n")
            fh.write("\n".join(lines) + "\n")
    note = f"Moved {len(moved)} unusable photo(s) to {NOT_USED_DIR}" if moved else ""
    return moved, note
