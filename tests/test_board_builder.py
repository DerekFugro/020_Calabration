"""Tests for src/board_builder.py — adding and measuring boards."""

import numpy as np
import pytest
import yaml

from src import board_builder as bb
from src.board import load_dot_layout
from src.boards import CAL_BOARD_DIR, load_board_folder

IKEA = CAL_BOARD_DIR / "ikea_road" / "ikea_road.csv"


def test_check_good_csv():
    c = bb.check_dot_csv(IKEA)
    assert c.ok and c.dots > 20 and 100 < c.width_mm < 5000 and c.min_gap_mm > 0


def test_check_rejects_non_layout(tmp_path):
    p = tmp_path / "x.csv"; p.write_text("a,b,c\n1,2,3\n")
    c = bb.check_dot_csv(p)
    assert not c.ok and c.dots == 0


def test_check_flags_millimetres(tmp_path):
    rows = [l.split() for l in IKEA.read_text().splitlines() if len(l.split()) >= 9]
    p = tmp_path / "mm.csv"
    p.write_text("\n".join(" ".join(r[:2] + [str(float(r[2]) * 1000), r[3], str(float(r[4]) * 1000)]
                                    + r[5:8] + [str(float(r[8]) * 1000)]) for r in rows))
    c = bb.check_dot_csv(p)
    assert not c.ok and any("metres" in x for x in c.problems)


def test_create_copies_csv_writes_yaml_and_pdf(tmp_path):
    folder = bb.create_dot_board("Test Board 1", IKEA, "TB1", library=tmp_path)
    assert folder.name == "Test_Board_1"
    spec = yaml.safe_load((folder / "board.yaml").read_text())
    assert (folder / spec["layout_csv"]).read_bytes() == IKEA.read_bytes()
    assert (folder / "Test_Board_1.pdf").stat().st_size > 1000
    assert spec["scale_x"] == 1.0 and spec["measure"]["AB_nominal_mm"] > 0
    b = load_board_folder(folder)
    assert b.is_dots and b.num_corners == bb.check_dot_csv(IKEA).dots
    with pytest.raises(FileExistsError):
        bb.create_dot_board("Test Board 1", IKEA, library=tmp_path)


def test_measurement_scales_the_layout(tmp_path):
    folder = bb.create_dot_board("tb", IKEA, library=tmp_path)
    xy, _ = load_dot_layout(IKEA)
    p = bb.measure_pairs(xy)
    true = xy * [1.004, 0.997]                 # the printer stretched it
    ab = np.linalg.norm(true[p["AB"][1]] - true[p["AB"][0]])
    cd = np.linalg.norm(true[p["CD"][1]] - true[p["CD"][0]])
    sx, sy = bb.save_measurement(folder, ab, cd)
    assert sx == pytest.approx(1.004, abs=1e-6) and sy == pytest.approx(0.997, abs=1e-6)
    b = load_board_folder(folder)
    assert np.allclose(b.dot_xy_mm, true, atol=1e-3)


def test_chessboard_add_and_measure(tmp_path):
    folder = bb.create_chessboard("chess", 12, 8, 76.39, 76.39, library=tmp_path)
    assert (folder / "chess.pdf").exists()
    w, h = bb.save_measurement(folder, 917.5, 611.0)
    b = load_board_folder(folder)
    assert b.cell_width_mm == pytest.approx(917.5 / 12, abs=1e-3)
    assert b.cell_height_mm == pytest.approx(611.0 / 8, abs=1e-3)


def test_pairs_are_level_and_upright():
    xy, _ = load_dot_layout(IKEA)
    p = bb.measure_pairs(xy)
    a, b, _ = p["AB"]; c, d, _ = p["CD"]
    assert abs(xy[b, 1] - xy[a, 1]) < 0.1 * abs(xy[b, 0] - xy[a, 0])
    assert abs(xy[d, 0] - xy[c, 0]) < 0.1 * abs(xy[d, 1] - xy[c, 1])


def test_measure_pdf_for_old_board(tmp_path):
    import shutil
    f = tmp_path / "old"; f.mkdir()
    shutil.copy(IKEA, f / "l.csv")
    (f / "board.yaml").write_text("name: old\ntype: dots\nlayout_csv: l.csv\n")
    out = bb.make_measure_pdf(f)
    assert out.name == "old_measure.pdf" and out.exists()
    spec = yaml.safe_load((f / "board.yaml").read_text())
    assert spec["measure"]["AB_nominal_mm"] > 0 and spec["layout_csv"] == "l.csv"


def _nominals(folder):
    return bb.nominal_lengths(folder)[1:]


def test_record_saves_good_readings_and_keeps_history(tmp_path):
    folder = bb.create_dot_board("tb", IKEA, library=tmp_path)
    ab, cd = _nominals(folder)
    ok, msg = bb.record_measurement(folder, [ab * 1.003, ab * 1.003 + 0.5], [cd, cd + 0.4])
    assert ok and "Saved" in msg
    spec = yaml.safe_load((folder / "board.yaml").read_text())
    assert spec["measure"]["AB_measured_mm"] == pytest.approx(ab * 1.003 + 0.25)
    assert load_board_folder(folder).print_measured
    ok, _ = bb.record_measurement(folder, [ab, ab], [cd, cd])
    spec = yaml.safe_load((folder / "board.yaml").read_text())
    assert ok and len(spec["measure_history"]) == 1


@pytest.mark.parametrize("ab_off,ab_spread,cd_off,word", [
    (0.0, 3.0, 0.0, "differ"),          # two readings disagree
    (0.05, 0.0, 0.0, "file says"),       # 5% off: wrong dots or scaled print
    (0.0, 0.0, -0.03, "file says"),
])
def test_record_refuses_bad_readings(tmp_path, ab_off, ab_spread, cd_off, word):
    folder = bb.create_dot_board("tb", IKEA, library=tmp_path)
    ab, cd = _nominals(folder)
    ok, msg = bb.record_measurement(folder, [ab * (1 + ab_off), ab * (1 + ab_off) + ab_spread],
                                    [cd * (1 + cd_off)] * 2)
    assert not ok and word in msg
    spec = yaml.safe_load((folder / "board.yaml").read_text())
    assert spec["measure"]["AB_measured_mm"] is None and spec["scale_x"] == 1.0
    assert not load_board_folder(folder).print_measured


def test_record_needs_two_readings(tmp_path):
    folder = bb.create_dot_board("tb", IKEA, library=tmp_path)
    ok, msg = bb.record_measurement(folder, [1000.0, 0], [500.0, 500.0])
    assert not ok and "two readings" in msg


def test_same_layout_twice_is_refused(tmp_path):
    bb.create_dot_board("first", IKEA, library=tmp_path)
    with pytest.raises(FileExistsError, match="already in the library as first"):
        bb.create_dot_board("second", IKEA, library=tmp_path)

