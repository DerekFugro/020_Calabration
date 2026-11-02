"""previous_runs.py — has this photo folder been calibrated before?

Saving writes CAL_<serial>_<YYYYMMDD_HHMMSS>.yaml/.pdf next to the photos
(src/output_writer.py).  The newest pair is the earlier result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

_NAME = re.compile(r"^(?:NOT_PASSED_)?CAL_(.+)_(\d{8}_\d{6})(?:_\d+)?\.ya?ml$", re.I)


@dataclass
class PreviousRun:
    yaml_path: Path
    pdf_path: Path | None
    serial: str
    when: datetime
    passed: bool | None
    headline: str

    def text(self) -> str:
        state = {True: "PASS", False: "NOT PASSED", None: "no grade"}[self.passed]
        return f"{self.when:%Y-%m-%d %H:%M}, serial {self.serial}: {state}"


def find_previous(folder: str | Path) -> list[PreviousRun]:
    """Earlier results in *folder*, newest first."""
    out = []
    p = Path(folder)
    if not p.is_dir():
        return out
    for f in p.iterdir():
        m = _NAME.match(f.name)
        if not m:
            continue
        try:
            when = datetime.strptime(m.group(2), "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        passed, head = None, ""
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            g = d.get("grade") or {}
            if "passed" in g:
                passed, head = bool(g["passed"]), str(g.get("headline", ""))
        except Exception:  # noqa: BLE001 — a broken file is still an earlier run
            pass
        pdf = f.with_suffix(".pdf")
        out.append(PreviousRun(f, pdf if pdf.exists() else None, m.group(1), when, passed, head))
    return sorted(out, key=lambda r: r.when, reverse=True)
