"""geo.py — van GPS position into the site grid, and grid vs true north.

The van's Applanix position (latitude, longitude) is WGS84 as the receiver reports
it (OmniSTAR VBS: ITRF, current epoch).  The control is NAD83(2011) state plane.
The two differ by about 1-1.5 m in Virginia, so the position goes through the
ITRF2014 -> NAD83(2011) time-dependent transformation [assumption: VBS reports in
ITRF2014-compatible WGS84; the control realisation is NAD83(2011)].
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import numpy as np
from pyproj import CRS, Transformer

US_FT = 1200.0 / 3937.0


@lru_cache(maxsize=8)
def _tf(dst_epsg: int, from_epsg: int = 7912):
    # 7912 = ITRF2014 geographic 3D;  dst = projected NAD83(2011) state plane (ftUS)
    src = CRS.from_epsg(from_epsg)
    dst = CRS.from_epsg(dst_epsg)
    return Transformer.from_crs(src, dst, always_xy=True)


def decimal_year(d: date) -> float:
    return d.year + (d.timetuple().tm_yday - 0.5) / 365.25


def latlon_to_grid_m(lat: float, lon: float, dst_epsg: int, when: date) -> tuple[float, float]:
    """WGS84/ITRF latitude, longitude -> grid E, N in metres (ftUS grid converted)."""
    e, n, _h, _t = _tf(dst_epsg).transform(lon, lat, 0.0, decimal_year(when))
    return e * US_FT, n * US_FT


def true_north_in_grid_deg(lat: float, lon: float, dst_epsg: int, when: date) -> float:
    """Grid azimuth (deg, clockwise from grid north) of the true-north direction.

    grid heading = true heading + this value.
    """
    e0, n0 = latlon_to_grid_m(lat, lon, dst_epsg, when)
    e1, n1 = latlon_to_grid_m(lat + 1e-4, lon, dst_epsg, when)
    return float(np.degrees(np.arctan2(e1 - e0, n1 - n0)))


def datum_shift_m(lat: float, lon: float, dst_epsg: int, when: date) -> float:
    """How far the ITRF->NAD83 step moves the point (shown in the report)."""
    a = _tf(dst_epsg).transform(lon, lat, 0.0, decimal_year(when))
    b = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(dst_epsg), always_xy=True).transform(lon, lat)
    return float(np.hypot(a[0] - b[0], a[1] - b[1]) * US_FT)
