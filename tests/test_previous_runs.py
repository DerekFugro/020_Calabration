from src.previous_runs import find_previous


def test_none(tmp_path):
    assert find_previous(tmp_path) == []
    assert find_previous(tmp_path / "missing") == []


def test_newest_first_with_grade(tmp_path):
    (tmp_path / "CAL_101324_20261101_120000.yaml").write_text("grade:\n  passed: false\n  headline: NOT PASSED\n")
    (tmp_path / "CAL_101324_20261102_090000.yaml").write_text("grade:\n  passed: true\n  headline: PASS\n")
    (tmp_path / "CAL_101324_20261102_090000.pdf").write_bytes(b"%PDF")
    (tmp_path / "other.yaml").write_text("x: 1")
    prev = find_previous(tmp_path)
    assert [p.passed for p in prev] == [True, False]
    assert prev[0].pdf_path is not None and prev[1].pdf_path is None
    assert prev[0].serial == "101324" and "PASS" in prev[0].text()


def test_broken_yaml_still_listed(tmp_path):
    (tmp_path / "CAL_7_20261102_090000.yaml").write_text(":::not yaml[")
    prev = find_previous(tmp_path)
    assert len(prev) == 1 and prev[0].passed is None
