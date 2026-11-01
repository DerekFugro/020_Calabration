"""board_builder.py — add a calibration board to the library (Cal_board).

Flow (Boards tab, or code):
  1. check_dot_csv(csv)            read and sanity-check the user's layout CSV
  2. create_board(...)             Cal_board/<name>/: copy of the CSV, board.yaml,
                                   true-scale PDF with measuring marks A-B and C-D
  3. print it, measure A-B and C-D centre to centre
  4. save_measurement(folder, ab, cd)  writes scale_x / scale_y into board.yaml;
                                   src/boards.py applies them when it loads the board
  5. test_detect(folder, photos)   check auto-detect finds the new board

Dot CSV format (same as the Randot files): space or comma separated, metres,
one dot per line:  0  id  x  0  z  0  -1  0  radius   (x right, z up, centre 0,0)
"""

from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import yaml

from src.board import load_dot_layout
from src.boards import BOARD_FILE, CAL_BOARD_DIR

MARGIN_MM = 40.0      # page edge to outermost dot edge


@dataclass
class DotCheck:
    ok: bool
    dots: int = 0
    width_mm: float = 0.0
    height_mm: float = 0.0
    radius_min_mm: float = 0.0
    radius_max_mm: float = 0.0
    min_gap_mm: float = 0.0
    problems: list = field(default_factory=list)

    def text(self) -> str:
        if not self.dots:
            return "Not a dot layout: " + "; ".join(self.problems)
        s = (f"{self.dots} dots, layout {self.width_mm:.0f} x {self.height_mm:.0f} mm, "
             f"dot radius {self.radius_min_mm:.1f}-{self.radius_max_mm:.1f} mm, "
             f"closest gap between dots {self.min_gap_mm:.1f} mm.")
        if self.problems:
            s += "\nProblems: " + "; ".join(self.problems)
        return s


def check_dot_csv(csv_path: str | Path) -> DotCheck:
    try:
        xy, r = load_dot_layout(csv_path)
    except Exception as exc:  # noqa: BLE001
        return DotCheck(ok=False, problems=[str(exc)])
    ids = _ids(csv_path)
    c = DotCheck(ok=True, dots=len(xy),
                 width_mm=float(np.ptp(xy[:, 0]) + 2 * r.max()),
                 height_mm=float(np.ptp(xy[:, 1]) + 2 * r.max()),
                 radius_min_mm=float(r.min()), radius_max_mm=float(r.max()))
    d = np.linalg.norm(xy[:, None] - xy[None], axis=2)
    gap = d - (r[:, None] + r[None])
    np.fill_diagonal(gap, np.inf)
    c.min_gap_mm = float(gap.min())
    if len(set(ids)) != len(ids):
        c.problems.append("dot ids repeat")
    if c.min_gap_mm <= 0:
        c.problems.append("some dots overlap")
    if r.min() <= 0:
        c.problems.append("a dot radius is zero")
    if c.dots < 20:
        c.problems.append(f"only {c.dots} dots; at least 20 recommended")
    if c.width_mm < 100 or c.width_mm > 5000:
        c.problems.append(f"layout is {c.width_mm:.0f} mm wide; the CSV must be in metres")
    c.ok = not c.problems
    return c


def _ids(csv_path) -> list[int]:
    out = []
    with open(csv_path, encoding="utf-8-sig") as fh:
        for line in fh:
            v = line.replace(",", " ").split()
            if len(v) >= 9:
                out.append(int(float(v[1])))
    return out


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("_.") or "board"


# ── Measuring pairs ──────────────────────────────────────────────────────────

def measure_pairs(xy: np.ndarray) -> dict:
    """Pick A-B (across) and C-D (down) for measuring the print.

    A-B: long and as level as possible (score |dx| - 2|dy|); C-D: long and as
    upright as possible (|dy| - 2|dx|).  Upright pairs keep the X and Y scales
    well separated.  Returns {"AB": (iA, iB, nominal_mm), "CD": (iC, iD, nominal_mm)}
    with indices into xy (sorted by id, like load_dot_layout).
    """
    dx = np.abs(xy[:, None, 0] - xy[None, :, 0])
    dy = np.abs(xy[:, None, 1] - xy[None, :, 1])
    out = {}
    for key, score in (("AB", dx - 2 * dy), ("CD", dy - 2 * dx)):
        i, j = np.unravel_index(int(np.argmax(score)), score.shape)
        if xy[i, 0 if key == "AB" else 1] > xy[j, 0 if key == "AB" else 1]:
            i, j = j, i
        out[key] = (int(i), int(j), float(np.linalg.norm(xy[i] - xy[j])))
    return out


def solve_scale(xy: np.ndarray, pairs: dict, ab_mm: float, cd_mm: float) -> tuple[float, float]:
    """Scale X and Y so both measured distances fit exactly."""
    (a, b, _), (c, d, _) = pairs["AB"], pairs["CD"]
    dx1, dy1 = xy[b] - xy[a]
    dx2, dy2 = xy[d] - xy[c]
    A = np.array([[dx1 ** 2, dy1 ** 2], [dx2 ** 2, dy2 ** 2]])
    s2 = np.linalg.solve(A, np.array([ab_mm ** 2, cd_mm ** 2]))
    if (s2 <= 0).any():
        raise ValueError("Those two measurements don't fit the layout; measure again.")
    return float(math.sqrt(s2[0])), float(math.sqrt(s2[1]))


# ── PDF ──────────────────────────────────────────────────────────────────────

def dot_pdf(csv_path, out_pdf, label: str = "", created: str = "") -> tuple[float, float]:
    """True-scale PDF of the layout with A-B / C-D marks.  Returns page (W, H) mm."""
    from fpdf import FPDF
    xy, r = load_dot_layout(csv_path)          # X right, Y down, mm
    pairs = measure_pairs(xy)
    rmax = float(r.max())
    W = math.ceil((np.ptp(xy[:, 0]) + 2 * (rmax + MARGIN_MM)) / 10) * 10
    H = math.ceil((np.ptp(xy[:, 1]) + 2 * (rmax + MARGIN_MM)) / 10) * 10
    ox = W / 2 - (xy[:, 0].max() + xy[:, 0].min()) / 2
    oy = H / 2 - (xy[:, 1].max() + xy[:, 1].min()) / 2
    pdf = FPDF(unit="mm", format=(W, H))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_fill_color(0, 0, 0)
    for (x, y), rr in zip(xy, r):
        pdf.ellipse(ox + x - rr, oy + y - rr, 2 * rr, 2 * rr, style="F")
    pdf.set_fill_color(190, 190, 190)
    for x, y in xy:                            # centre marks for measuring
        pdf.ellipse(ox + x - 0.5, oy + y - 0.5, 1.0, 1.0, style="F")
    pdf.set_text_color(200, 0, 0)
    pdf.set_font("Helvetica", "", 36)   # ~13 mm letters: bigger ones (B, D) get found as dots
    for key, letters in (("AB", "AB"), ("CD", "CD")):
        i, j, _ = pairs[key]
        for idx, L in ((i, letters[0]), (j, letters[1])):
            x, y = xy[idx]
            pdf.text(ox + x + r[idx] + 3, oy + y - r[idx] - 3, L)
    # Name and date, big enough to read across a room, small enough (< 15 mm
    # letters) that the dot finder ignores them; kept inside the edge margin.
    pdf.set_text_color(60, 60, 60)
    pdf.set_font("Helvetica", "", 34)
    name_line = label + (f"   -   created {created}" if created else "")
    pdf.text(12, H - 12, name_line)
    pdf.set_text_color(110, 110, 110)
    pdf.set_font("Helvetica", "", max(12, round(W / 80)))
    ab, cd = pairs["AB"][2], pairs["CD"][2]
    pdf.text(12, 14, "Print at 100% (no scaling).  Measure centre to centre: "
                     f"A-B should be {ab:.1f} mm, C-D should be {cd:.1f} mm.")
    pdf.output(str(out_pdf))
    return W, H


def chess_pdf(squares_x, squares_y, cell_w, cell_h, out_pdf, label: str = "") -> tuple[float, float]:
    from fpdf import FPDF
    m = 30.0
    W, H = squares_x * cell_w + 2 * m, squares_y * cell_h + 2 * m
    pdf = FPDF(unit="mm", format=(W, H))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_fill_color(0, 0, 0)
    for i in range(squares_x):
        for j in range(squares_y):
            if (i + j) % 2 == 0:
                pdf.rect(m + i * cell_w, m + j * cell_h, cell_w, cell_h, style="F")
    pdf.set_font("Helvetica", "", 10); pdf.set_text_color(90, 90, 90)
    pdf.text(m, H - 10, f"{label}   Print at 100%.  Board should be {squares_x * cell_w:.1f} x "
                        f"{squares_y * cell_h:.1f} mm (squares edge to edge).")
    pdf.output(str(out_pdf))
    return W, H


# ── Create / measure ─────────────────────────────────────────────────────────

def create_dot_board(name: str, csv_path, label: str = "",
                     library: str | Path | None = None) -> Path:
    chk = check_dot_csv(csv_path)
    if not chk.dots:
        raise ValueError(chk.text())
    folder = Path(library or CAL_BOARD_DIR) / safe_name(name)
    if folder.exists():
        raise FileExistsError(f"A board folder called {folder.name} already exists.")
    folder.mkdir(parents=True)
    csv_name = safe_name(Path(csv_path).stem) + ".csv"
    shutil.copy2(csv_path, folder / csv_name)
    W, H = dot_pdf(folder / csv_name, folder / (safe_name(name) + ".pdf"), label or name,
                   created=date.today().isoformat())
    xy, _ = load_dot_layout(folder / csv_name)
    p = measure_pairs(xy)
    spec = {"name": name, "type": "dots", "layout_csv": csv_name, "label": label,
            "source_csv": str(csv_path), "added": date.today().isoformat(),
            "page_mm": [W, H],
            "measure": {"AB_nominal_mm": round(p["AB"][2], 2), "CD_nominal_mm": round(p["CD"][2], 2),
                        "AB_measured_mm": None, "CD_measured_mm": None},
            "scale_x": 1.0, "scale_y": 1.0}
    _write_spec(folder, spec)
    return folder


def create_chessboard(name: str, squares_x: int, squares_y: int, cell_w: float, cell_h: float,
                      library: str | Path | None = None) -> Path:
    folder = Path(library or CAL_BOARD_DIR) / safe_name(name)
    if folder.exists():
        raise FileExistsError(f"A board folder called {folder.name} already exists.")
    folder.mkdir(parents=True)
    W, H = chess_pdf(squares_x, squares_y, cell_w, cell_h, folder / (safe_name(name) + ".pdf"), name)
    _write_spec(folder, {"name": name, "type": "chessboard", "squares_x": int(squares_x),
                         "squares_y": int(squares_y), "cell_width_mm": float(cell_w),
                         "cell_height_mm": float(cell_h), "added": date.today().isoformat(),
                         "page_mm": [W, H], "measured": False})
    return folder


def make_measure_pdf(folder) -> Path:
    """A PDF with the A-B / C-D marks for a board added before this tab existed.

    Written as <name>_measure.pdf; the board's own PDF is left alone.  Also
    stores the nominal A-B / C-D in board.yaml.
    """
    folder = Path(folder)
    spec = _read_spec(folder)
    if spec.get("type") != "dots":
        raise ValueError("Only dot boards need the A-B / C-D marks.")
    csv = folder / spec["layout_csv"]
    out = folder / (safe_name(str(spec.get("name") or folder.name)) + "_measure.pdf")
    dot_pdf(csv, out, str(spec.get("label") or spec.get("name") or ""), created=str(spec.get("added", "")))
    xy, _ = load_dot_layout(csv)
    p = measure_pairs(xy)
    m = spec.setdefault("measure", {})
    m.update(AB_nominal_mm=round(p["AB"][2], 2), CD_nominal_mm=round(p["CD"][2], 2))
    m.setdefault("AB_measured_mm", None); m.setdefault("CD_measured_mm", None)
    spec.setdefault("scale_x", 1.0); spec.setdefault("scale_y", 1.0)
    _write_spec(folder, spec)
    return out


def save_measurement(folder, ab_mm: float, cd_mm: float) -> tuple[float, float]:
    """Dots: ab/cd are the measured A-B and C-D distances.
    Chessboard: ab/cd are the measured full board width/height (squares edge to edge)."""
    folder = Path(folder)
    spec = _read_spec(folder)
    if spec.get("type") == "chessboard":
        sx, sy = int(spec["squares_x"]), int(spec["squares_y"])
        spec["cell_width_mm"] = round(ab_mm / sx, 4)
        spec["cell_height_mm"] = round(cd_mm / sy, 4)
        spec["measured"] = {"width_mm": ab_mm, "height_mm": cd_mm, "date": date.today().isoformat()}
        _write_spec(folder, spec)
        return spec["cell_width_mm"], spec["cell_height_mm"]
    xy, _ = load_dot_layout(folder / spec["layout_csv"])
    sx, sy = solve_scale(xy, measure_pairs(xy), ab_mm, cd_mm)
    m = spec.setdefault("measure", {})
    m.update(AB_measured_mm=float(ab_mm), CD_measured_mm=float(cd_mm), date=date.today().isoformat())
    spec["scale_x"], spec["scale_y"] = round(sx, 6), round(sy, 6)
    _write_spec(folder, spec)
    return sx, sy


def _read_spec(folder: Path) -> dict:
    return yaml.safe_load((folder / BOARD_FILE).read_text(encoding="utf-8")) or {}


def _write_spec(folder: Path, spec: dict) -> None:
    (folder / BOARD_FILE).write_text(
        "# Written by the Boards tab.  scale_x / scale_y come from measuring the print.\n"
        + yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")


# ── Test ─────────────────────────────────────────────────────────────────────

def test_detect(folder, photo_paths: list[str]) -> str:
    """Run auto-detect over the photos with the whole library; plain-text result."""
    from src.auto_detect import auto_detect_board
    from src.boards import list_boards, load_board_folder
    from src.detector import detect_images
    new = load_board_folder(folder)
    boards = list_boards()
    res = auto_detect_board(photo_paths, boards)
    lines = [res.summary()]
    if res.board is None or res.board.name != new.name:
        lines.append(f"PROBLEM: auto-detect did not pick {new.name}.")
        return "\n".join(lines)
    dets = detect_images(photo_paths[:8], new, verbose=False)
    for d in dets:
        lines.append(f"  {Path(d.image_path).name}: {d.corner_count} of {new.num_corners} points")
    lines.append(f"OK: auto-detect picks {new.name}.")
    return "\n".join(lines)
