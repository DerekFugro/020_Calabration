"""oldschool_pos_check.py - are all the photos and all the POS data there?  (Phase 8, Derek
2026-11-15: "are we getting all the data?" ... "images and pos data")

Run with the POS app's own Python, so its file reader is used (read only):
    E:\\DP\\POSProcessor\\.venv\\Scripts\\python.exe tools\\oldschool_pos_check.py <site folder> [...]

For each Old School site folder (ExtrinsicAran<XX>_<date time>) it checks:
  * the full POS recording (SurveyorPOS_*\\LV_1_*.000, .001 ...): the POS app's reader reads
    every file; navigation (Group 1) has no gaps, accuracy (Group 2) and GNSS status (Group 3)
    are there, no broken records, the time type and the lever arms;
  * each position's POS CSV (<camera>\\PositionN\\NN_*.csv): rows, the rate, the longest gap,
    and that every row is a navigation reading in the full recording (same time and position);
  * each position's photos: as many as Capture's log lists, every one opens, full size, and
    taken while that position's POS data was logging (PC clock against POS time; the PC's
    clock offset from the POS is shown).
Writes POS_CHECK.txt in each site folder and prints the same.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

POS_APP = Path(r"E:\DP\POSProcessor")
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)


def _photos(folder: Path, lines, week: int, utc_sow, pos_t0: float, pos_t1: float, pc_fast_s: float) -> bool:
    """The position's photos: listed in the log, there, open, full size, taken during the POS logging."""
    from PIL import Image
    logs = sorted(folder.glob("CAPTURE_*.json"))
    log = json.loads(logs[-1].read_text(encoding="utf-8")) if logs else {}
    listed = [p["file"] for p in log.get("photos", [])]
    jpgs = sorted(folder.glob("*.jpg"))
    want = log.get("expected_size") or log.get("delivered_size") or ""
    bad, sizes, during, offs = [], set(), 0, []
    for f in jpgs:
        try:
            with Image.open(f) as im:
                im.load(); sizes.add(f"{im.width}x{im.height}")
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{f.name} ({exc})")
    if week and utc_sow:
        start = utc_sow(week, pos_t0); end = utc_sow(week, pos_t1)
        for p in log.get("photos", []):
            t = datetime.fromisoformat(p["time"]).astimezone(timezone.utc) - timedelta(seconds=pc_fast_s)
            if start - timedelta(seconds=2) <= t <= end + timedelta(seconds=2):
                during += 1
            offs.append((t - start).total_seconds())
    missing = sorted(set(listed) - {f.name for f in jpgs})
    ok = bool(jpgs) and not bad and not missing and len(jpgs) == len(listed) and \
        (not want or sizes == {want}) and during == len(listed)
    _say(lines, f"    photos: {len(jpgs)} in the folder, {len(listed)} in Capture's log, all open: {not bad}, "
                f"size {', '.join(sorted(sizes)) or '-'} (expected {want or '?'}), taken during the POS logging: "
                f"{during}/{len(listed)} (first photo {min(offs) if offs else float('nan'):.1f} s after the POS mark)"
                + (f", MISSING: {missing}" if missing else "") + (f", CAN'T OPEN: {bad}" if bad else "")
                + f" -> {'ALL THERE' if ok else 'PROBLEM'}")
    return ok


def off_for_clock(d) -> float:
    """Leap seconds the reader added to Group 1 (UTC -> GPS), to undo for UTC times."""
    return d.gps_utc_offset if d.time1_type == 2 and np.isfinite(d.gps_utc_offset) else 0.0


def _say(lines, *x):
    t = " ".join(str(v) for v in x)
    print(t); lines.append(t)


def check_site(site: Path) -> bool:
    sys.path.insert(0, str(POS_APP))
    from posproc.pcs import read_pcs
    lines, ok = [], True
    _say(lines, f"POS data check: {site}")
    sessions = sorted(site.glob("SurveyorPOS_*"))
    files = sorted(f for s in sessions for f in s.glob("LV_1_*.0*"))
    if not files:
        _say(lines, "  NO POS recording (.000 files) found."); return False
    d = read_pcs(files)
    g1 = d.g1
    dt = np.diff(g1["t"]) if len(g1) > 1 else np.array([0.0])
    span = float(g1["t"][-1] - g1["t"][0]) if len(g1) else 0.0
    rate = (len(g1) - 1) / span if span > 0 else 0.0
    gaps = int((dt > 0.1).sum())
    _say(lines, f"  Recording: {len(files)} file(s), {sum(f.stat().st_size for f in files) / 1e6:.1f} MB, "
                f"{span / 60:.1f} minutes")
    _say(lines, f"  Navigation (Group 1): {len(g1)} readings, {rate:.1f} a second, longest gap {dt.max():.3f} s, "
                f"gaps over 0.1 s: {gaps}")
    _say(lines, f"  Accuracy (Group 2): {len(d.g2)} readings;  GNSS status (Group 3): {len(d.g3)} readings, "
                f"satellites {int(np.median(d.g3['nsv'])) if len(d.g3) else '-'}")
    _say(lines, f"  Broken records: {d.bad_records};  time type: {d.time1_type} (2 = UTC), "
                f"GPS-UTC {d.gps_utc_offset} s;  {d.time_note or ''}")
    lv = d.lever
    _say(lines, f"  Lever arms (Message 20): {lv}")
    if gaps or d.bad_records or len(d.g2) == 0 or len(d.g3) == 0:
        ok = False
    # the reader moves Group 1 to GPS time; the mark CSV keeps the POS's own Time 1
    off = d.gps_utc_offset if d.time1_type == 2 and np.isfinite(d.gps_utc_offset) else 0.0
    week = d.gps_week
    # The PC clock against the POS (GNSS) clock: the recording folder is named with the PC's
    # time when the first data came (ARAN59 2026-11-15: the PC was 59 minutes fast, not synced).
    pc_fast_s = 0.0
    try:
        named = datetime.strptime(sessions[0].name.split("_", 1)[1], "%Y%m%d_%H%M%S").astimezone(timezone.utc)
        if d.time1_type == 2 and len(g1):
            first = GPS_EPOCH + timedelta(weeks=week, seconds=float(g1["t"][0] - off_for_clock(d)))
            pc_fast_s = (named - first).total_seconds()
    except (ValueError, IndexError):
        pass
    _say(lines, f"  PC clock against the POS (GNSS) time: {pc_fast_s:+.0f} s"
                + ("  <- the PC clock is wrong; photo times are corrected by this" if abs(pc_fast_s) > 5 else ""))

    def utc_sow(wk, sow):                 # POS Time 1 (UTC seconds of the week) -> UTC time
        return GPS_EPOCH + timedelta(weeks=wk, seconds=sow)
    positions = sorted(p for p in site.glob("*/Position*") if p.is_dir())
    csvs = {p: next(iter(sorted(p.glob("[0-9][0-9]_*.csv"))), None) for p in positions}
    for pfolder, c in csvs.items():
        if c is None:
            _say(lines, f"  {pfolder.parent.name}\\{pfolder.name}: NO POS CSV"); ok = False; continue
        with open(c, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            _say(lines, f"  {c.parent.parent.name}\\{c.parent.name}: EMPTY CSV"); ok = False; continue
        t = np.array([float(r["time1_s"]) for r in rows])
        lat = np.array([float(r["lat_deg"]) for r in rows])
        cdt = np.diff(t) if len(t) > 1 else np.array([0.0])
        cspan = float(t[-1] - t[0])
        # same readings as the full recording?
        tg = t + off
        j = np.searchsorted(g1["t"], tg)
        j = np.clip(j, 0, len(g1) - 1)
        j2 = np.clip(j - 1, 0, len(g1) - 1)
        near = np.where(np.abs(g1["t"][j] - tg) < np.abs(g1["t"][j2] - tg), j, j2)
        same_t = np.abs(g1["t"][near] - tg) < 0.002
        same_p = np.abs(g1["lat"][near] - lat) < 1e-8
        in_rec = int((same_t & same_p).sum())
        n_rec = int(((g1["t"] >= tg[0] - 1e-3) & (g1["t"] <= tg[-1] + 1e-3)).sum())
        green = sum(1 for r in rows if r.get("light") == "green")
        good = (in_rec == len(rows) and n_rec == len(rows) and cdt.max() <= 0.1)
        ok = ok and good
        _say(lines, f"  {c.parent.parent.name}\\{c.parent.name}\\{c.name}: {len(rows)} rows over {cspan:.1f} s "
                    f"({(len(rows) - 1) / cspan if cspan else 0:.1f} a second), longest gap {cdt.max():.3f} s, "
                    f"green {green}/{len(rows)};  in the full recording: {in_rec}/{len(rows)}, recording has "
                    f"{n_rec} readings in that time -> {'ALL THERE' if good else 'MISSING DATA'}")
        ok = _photos(pfolder, lines, week, utc_sow if d.time1_type == 2 else None, float(t[0]), float(t[-1]),
                     pc_fast_s) and ok
    _say(lines, f"  RESULT: {'all the photos and POS data are there' if ok else 'SOMETHING IS MISSING (see above)'}")
    (site / "POS_CHECK.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


if __name__ == "__main__":
    sites = [Path(p) for p in sys.argv[1:]]
    sys.exit(0 if all([check_site(s) for s in sites]) else 1)
