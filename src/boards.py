"""boards.py — The board library: one folder per board under Cal_board/.

Each board folder holds a board.yaml that says what the board is:

    # chessboard
    name: Chessboard 12x8
    type: chessboard
    squares_x: 12
    squares_y: 8
    cell_width_mm: 76.39
    cell_height_mm: 76.39

    # random-dot board
    name: Randot-003
    type: dots
    layout_csv: Randot-003_roadware_140_60_003(in).csv   # relative to the folder
    label: roadware_140_60_003                           # optional

Adding a new board = adding a new folder with a board.yaml.  No code change.
Folders without a board.yaml are ignored.  If no chessboard folder exists,
the built-in 12x8 chessboard (src/board.py defaults) is still offered.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.board import (
    BoardConfig,
    DEFAULT_CELL_HEIGHT_MM,
    DEFAULT_CELL_WIDTH_MM,
    DEFAULT_SQUARES_X,
    DEFAULT_SQUARES_Y,
    KIND_CHESSBOARD,
    KIND_DOTS,
)

CAL_BOARD_DIR = Path(__file__).resolve().parent.parent / "Cal_board"
BOARD_FILE = "board.yaml"


def load_board_folder(folder: str | Path) -> BoardConfig:
    """Read one board folder's board.yaml.  Raises ValueError if it is bad."""
    folder = Path(folder)
    spec_path = folder / BOARD_FILE
    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read {spec_path}: {exc}") from None

    kind = str(spec.get("type", "")).strip().lower()
    name = str(spec.get("name") or folder.name)

    if kind == KIND_DOTS:
        csv_name = spec.get("layout_csv")
        if not csv_name:
            raise ValueError(f"{spec_path}: a dots board needs layout_csv.")
        csv_path = folder / str(csv_name)
        if not csv_path.is_file():
            raise ValueError(f"{spec_path}: layout file not found: {csv_path}")
        b = BoardConfig.from_dot_csv(
            csv_path, name=name, label=str(spec.get("label") or ""),
            folder=str(folder),
        )
        # Measured print size (Boards tab): stretch the layout to the real board.
        sx = float(spec.get("scale_x", 1.0) or 1.0)
        sy = float(spec.get("scale_y", 1.0) or 1.0)
        if (sx, sy) != (1.0, 1.0):
            b.dot_xy_mm = b.dot_xy_mm * [sx, sy]
            b.dot_radius_mm = b.dot_radius_mm * (sx + sy) / 2
        return b

    if kind == KIND_CHESSBOARD:
        return BoardConfig(
            squares_x=int(spec.get("squares_x", DEFAULT_SQUARES_X)),
            squares_y=int(spec.get("squares_y", DEFAULT_SQUARES_Y)),
            cell_width_mm=float(spec.get("cell_width_mm", DEFAULT_CELL_WIDTH_MM)),
            cell_height_mm=float(spec.get("cell_height_mm", DEFAULT_CELL_HEIGHT_MM)),
            kind=KIND_CHESSBOARD, name=name, folder=str(folder),
        )

    raise ValueError(f"{spec_path}: type must be 'chessboard' or 'dots', got {kind!r}.")


def list_boards(cal_board_dir: str | Path | None = None,
                errors: list[str] | None = None) -> list[BoardConfig]:
    """Every board in the library, chessboards first, then by name.

    Bad board folders are skipped; their messages are appended to *errors*
    when a list is passed, so the GUI can show them.
    """
    root = Path(cal_board_dir) if cal_board_dir else CAL_BOARD_DIR
    boards: list[BoardConfig] = []
    if root.is_dir():
        for sub in sorted(p for p in root.iterdir() if p.is_dir()):
            if not (sub / BOARD_FILE).is_file():
                continue
            try:
                boards.append(load_board_folder(sub))
            except ValueError as exc:
                if errors is not None:
                    errors.append(str(exc))
    if not any(b.kind == KIND_CHESSBOARD for b in boards):
        boards.append(BoardConfig())          # built-in 12x8 chessboard
    boards.sort(key=lambda b: (b.kind != KIND_CHESSBOARD, b.name.lower()))
    return boards


def find_board(name: str, boards: list[BoardConfig]) -> BoardConfig | None:
    """Look a board up by name or folder name (case-insensitive)."""
    key = name.strip().lower()
    for b in boards:
        if b.name.lower() == key or (b.folder and Path(b.folder).name.lower() == key):
            return b
    return None
