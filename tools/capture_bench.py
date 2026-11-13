"""capture_bench.py - Phase 1 bench test for SurveyorCapture (docs/capture).  Not part of the app.

Read only: for each DirectShow video input it opens the input, reads a few frames,
saves ONE photo to the output folder, and closes it.  It never changes any camera or
capture-card setting.  Run only with Derek's OK, and while ARAN collection is not
collecting (and once more while it is, to see what "busy" looks like).

  uv run python tools/capture_bench.py OUT_FOLDER [--size 3840x2160] [--only "00-0"] [--frames 10]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from src.capture.dshow_names import video_inputs  # noqa: E402


def fourcc_text(v: float) -> str:
    i = int(v)
    s = "".join(chr((i >> (8 * k)) & 0xFF) for k in range(4))
    return s if s.isprintable() and s.strip() else str(i)


def bench(index: int, name: str, size, frames: int, out: Path) -> dict:
    r = {"index": index, "name": name, "requested": f"{size[0]}x{size[1]}" if size else "none"}
    t0 = time.perf_counter()
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    try:
        r["opened"] = bool(cap.isOpened())
        r["open_s"] = round(time.perf_counter() - t0, 2)
        if not r["opened"]:
            return r
        if size:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0]); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        r["reported"] = f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
        r["fourcc"] = fourcc_text(cap.get(cv2.CAP_PROP_FOURCC))
        good, last, t1 = 0, None, time.perf_counter()
        for _ in range(frames):
            ok, f = cap.read()
            if ok and f is not None:
                good += 1; last = f
        dt = time.perf_counter() - t1
        r["frames_ok"] = f"{good}/{frames}"
        r["fps"] = round(good / dt, 1) if dt > 0 else None
        if last is not None:
            r["delivered"] = f"{last.shape[1]}x{last.shape[0]}"
            r["mean_level"] = round(float(last.mean()), 1)      # ~0 = black frames (no signal?)
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60]
            p = out / f"bench_{index}_{safe}.jpg"
            cv2.imwrite(str(p), last, [cv2.IMWRITE_JPEG_QUALITY, 95])
            r["photo"] = p.name
        return r
    finally:
        cap.release()
        r["total_s"] = round(time.perf_counter() - t0, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--size", default="", help="e.g. 3840x2160 (none = what the input gives)")
    ap.add_argument("--only", default="", help="only inputs whose name contains this")
    ap.add_argument("--frames", type=int, default=10)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    size = tuple(int(v) for v in a.size.lower().split("x")) if a.size else None
    names = video_inputs()
    print(f"{len(names)} video inputs (DirectShow order = cv2.CAP_DSHOW index):")
    for i, n in enumerate(names):
        print(f"  {i}: {n}")
    results = []
    for i, n in enumerate(names):
        if a.only and a.only not in n:
            continue
        r = bench(i, n, size, a.frames, out)
        print(json.dumps(r))
        results.append(r)
    (out / f"bench_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
