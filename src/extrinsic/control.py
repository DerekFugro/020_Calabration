"""control.py — the surveyed targets of an Old School site (metres, local grid).

Coordinates are kept in the site's state-plane grid, converted to metres:
E, N (grid) and H (orthometric, NAVD88).  Point ids are strings, as in the files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

US_FT = 1200.0 / 3937.0
from src.paths import SITES_DIR  # noqa: E402  (repo control, or ProgramData when installed)


@dataclass
class Site:
    name: str
    folder: Path
    crs: int
    geoid_n_m: float
    ids: list = field(default_factory=list)
    enh_m: np.ndarray = None          # (N, 3) E, N, H in metres
    ground: np.ndarray = None         # (N,) bool: on the pavement

    def index(self) -> dict:
        return {pid: i for i, pid in enumerate(self.ids)}

    def xyz(self, pid: str) -> np.ndarray | None:
        i = self.index().get(str(pid))
        return None if i is None else self.enh_m[i]


def read_gcp(path) -> tuple[list[str], np.ndarray]:
    ids, pts = [], []
    for line in open(path, errors="ignore"):
        v = line.split()
        if len(v) >= 4 and v[0] != "-99":
            try:
                pts.append([float(v[1]), float(v[2]), float(v[3])]); ids.append(v[0])
            except ValueError:
                pass
    return ids, np.array(pts, float)


def load_site(name: str = "Richmond") -> Site:
    folder = SITES_DIR / name
    spec = yaml.safe_load((folder / "site.yaml").read_text(encoding="utf-8"))
    ids, ft = read_gcp(folder / spec["gcp_file"])
    s = Site(name=spec["name"], folder=folder, crs=int(spec["horizontal_crs"]),
             geoid_n_m=float(spec["geoid_separation_m"]), ids=ids, enh_m=ft * US_FT)
    s.ground = ft[:, 2] <= float(spec["ground_max_z_ft"])
    return s
