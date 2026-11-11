"""One current result per camera: earlier results move to Superseded\\ on Save (2026-11-11)."""

from src.superseded import FOLDER, extrinsic_results, intrinsic_results, move_to_superseded


def test_intrinsic_results_are_found_and_moved(tmp_path):
    for n in ("CAL_101324_20260401_100000.yaml", "CAL_101324_20260401_100000.pdf",
              "NOT_PASSED_CAL_101324_20260402_100000.yaml", "photo_001.png", "notes.txt"):
        (tmp_path / n).write_text("x")
    (tmp_path / "Calibration_20260401_100000").mkdir()
    (tmp_path / "Calibration_20260401_100000" / "a.xml").write_text("x")
    (tmp_path / "NotUsed").mkdir()
    old = intrinsic_results(tmp_path)
    assert [p.name for p in old] == ["CAL_101324_20260401_100000.pdf", "CAL_101324_20260401_100000.yaml",
                                     "Calibration_20260401_100000", "NOT_PASSED_CAL_101324_20260402_100000.yaml"]
    moved = move_to_superseded(old, tmp_path)
    assert len(moved) == 4 and intrinsic_results(tmp_path) == []
    assert (tmp_path / FOLDER / "Calibration_20260401_100000" / "a.xml").exists()
    assert (tmp_path / "photo_001.png").exists() and (tmp_path / "NotUsed").exists()


def test_extrinsic_results_and_name_clash(tmp_path):
    (tmp_path / "Extrinsic_20260401_100000").mkdir()
    (tmp_path / "20260404.102502").mkdir()                      # a setup folder: never moved
    (tmp_path / FOLDER / "Extrinsic_20260401_100000").mkdir(parents=True)   # already there once
    old = extrinsic_results(tmp_path)
    assert [p.name for p in old] == ["Extrinsic_20260401_100000"]
    moved = move_to_superseded(old, tmp_path)
    assert moved[0].name == "Extrinsic_20260401_100000_2" and extrinsic_results(tmp_path) == []
    assert (tmp_path / "20260404.102502").exists()
    assert move_to_superseded([], tmp_path) == []
