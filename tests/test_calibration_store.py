"""test_calibration_store.py — Tests for the calibration store.

Store rule: master doc §11 + Calibrations\\README.md.
  - one folder per calibration event: YYYYMMDD[_HHMMSS]_<Type>\\
  - the Type names the camera: PaveIntrinsic / ROWIntrinsic (master doc v1.4)
  - one file inside it: <ROLE>_<SERIAL>.yaml
  - append-only: publish() never overwrites
  - selection: newest folder of the Type, stamp <= collection start, that
    actually holds this camera's file
  - a bad role/serial is rejected BEFORE it becomes a permanent filename
  - ONLY a passing calibration is published (append-only store, no cleanup)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import yaml

from src.board import BoardConfig
from src.calibration_store import (
    INTRINSIC_TYPES,
    StoreError,
    calibration_type,
    check_publishable,
    event_folder_name,
    find_latest,
    normalise_role,
    parse_event_folder,
    publish,
    store_available,
    store_path,
    subject_filename,
    validate_subject,
)
from src.calibrator import CalibrationResult
from src.output_writer import write_yaml


_DT = datetime(2026, 8, 15, 20, 23, 57)


def _grade(passed: bool, headline: str = ""):
    """The fields of a src/grading.GradeReport that write_yaml records."""
    from types import SimpleNamespace
    return SimpleNamespace(passed=passed, headline=headline or ("PASS" if passed else "NOT PASSED"),
                           hard_stops=[], reasons=[] if passed else ["coverage: 2 red areas"],
                           warnings=[], left_out=[], repeatability=None, more_photos=0,
                           blur_median_px=float("nan"), blurry_images=[])


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def cal():
    return CalibrationResult(
        camera_matrix=np.array(
            [[2757.591943, 0.0, 1417.737625],
             [0.0, 2758.043961, 918.775062],
             [0.0, 0.0, 1.0]],
            dtype=np.float64,
        ),
        dist_coeffs=np.array(
            [[-0.11547295, 0.11742459, -0.00099769, -0.00087287, -0.03682034]],
            dtype=np.float64,
        ),
        rms=0.340977,
        rvecs=[],
        tvecs=[],
        image_count_used=53,
        image_size=(2880, 1860),
    )


@pytest.fixture
def written_yaml(cal, tmp_path):
    """A local CAL_ YAML, as the app writes it next to the images."""
    cal.grade = _grade(True)
    folder = tmp_path / "images"
    folder.mkdir()
    return write_yaml(cal, BoardConfig(), "234500499", folder, _DT, "PAVE")


def _write_cal(tmp_path, passed, name="images", rms=0.5, image_count=45):
    """Write a local CAL_ YAML for a run whose grade passed or not."""
    result = CalibrationResult(
        camera_matrix=np.array([[2757.6, 0.0, 1417.7],
                                [0.0, 2758.0, 918.8],
                                [0.0, 0.0, 1.0]], dtype=np.float64),
        dist_coeffs=np.array([[-0.115, 0.117, -0.001, -0.0009, -0.037]],
                             dtype=np.float64),
        rms=rms, rvecs=[], tvecs=[],
        image_count_used=image_count, image_size=(2880, 1860),
    )
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    result.grade = _grade(passed)
    return write_yaml(result, BoardConfig(), "234500499", folder, _DT, "PAVE")


@pytest.fixture
def store(tmp_path):
    s = tmp_path / "Calibrations"
    s.mkdir()
    return s


# ── normalise_role ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("PAVE", "PAVE"),
        ("Pave", "PAVE"),
        ("  row  ", "ROW"),
        ("row camera", "ROW-CAMERA"),
        ("row_camera", "ROW-CAMERA"),
        ("ROW--CAMERA", "ROW-CAMERA"),
        ("", ""),
    ],
)
def test_normalise_role(raw, expected):
    assert normalise_role(raw) == expected


# ── validate_subject ─────────────────────────────────────────────────────────

def test_validate_subject_normalises():
    assert validate_subject("Pave", " 234500499 ") == ("PAVE", "234500499")


@pytest.mark.parametrize("role", ["", "   ", "-", "pave!"])
def test_validate_subject_rejects_bad_role(role):
    with pytest.raises(StoreError):
        validate_subject(role, "234500499")


@pytest.mark.parametrize("serial", ["", "  ", "2345 00499", "234/500499"])
def test_validate_subject_rejects_bad_serial(serial):
    with pytest.raises(StoreError):
        validate_subject("PAVE", serial)


# ── Type names ───────────────────────────────────────────────────────────────

def test_type_names_are_verbatim():
    """Owner-defined, mixed capitalisation — these ARE the folder names."""
    assert INTRINSIC_TYPES == {"PAVE": "PaveIntrinsic", "ROW": "ROWIntrinsic"}


@pytest.mark.parametrize("role, expected", [
    ("PAVE", "PaveIntrinsic"),
    ("Pave", "PaveIntrinsic"),
    ("row", "ROWIntrinsic"),
])
def test_calibration_type_lookup(role, expected):
    assert calibration_type(role) == expected


@pytest.mark.parametrize("role", ["BENCH", "SPARE-CAM", ""])
def test_calibration_type_refuses_undefined_role(role):
    """The app must never invent a type name — bench runs stay local."""
    with pytest.raises(StoreError):
        calibration_type(role)


def test_types_contain_no_underscore():
    """An underscore in a type would make type and subject indistinguishable."""
    for name in INTRINSIC_TYPES.values():
        assert "_" not in name


# ── Naming ───────────────────────────────────────────────────────────────────

def test_event_folder_name_uses_the_type():
    assert event_folder_name(_DT, "PAVE") == "20260815_202357_PaveIntrinsic"
    assert event_folder_name(_DT, "ROW") == "20260815_202357_ROWIntrinsic"


def test_event_folder_name_normalises_role():
    assert event_folder_name(_DT, "pave") == "20260815_202357_PaveIntrinsic"


def test_event_folder_name_refuses_undefined_role():
    with pytest.raises(StoreError):
        event_folder_name(_DT, "BENCH")


def test_subject_filename():
    assert subject_filename("Pave", "234500499") == "PAVE_234500499.yaml"


def test_event_folders_sort_chronologically():
    """Selection needs plain string sort to equal chronological order."""
    early = event_folder_name(datetime(2026, 8, 15, 9, 0, 0), "PAVE")
    late = event_folder_name(datetime(2026, 8, 15, 20, 23, 57), "PAVE")
    assert early < late


# ── parse_event_folder ───────────────────────────────────────────────────────

def test_parse_folder_with_seconds():
    assert parse_event_folder("20260815_202357_PaveIntrinsic") == (
        datetime(2026, 8, 15, 20, 23, 57), "PaveIntrinsic", ""
    )


def test_parse_date_only_folder_is_midnight():
    """The 2026-08-15 baseline folders carry a date only."""
    assert parse_event_folder("20260815_PaveIntrinsic") == (
        datetime(2026, 8, 15, 0, 0, 0), "PaveIntrinsic", ""
    )


@pytest.mark.parametrize("name, ftype", [
    ("20260815_ROWIntrinsic", "ROWIntrinsic"),
    ("20260815_DMI-Gain", "DMI-Gain"),
    ("20260815_Laser-XScale", "Laser-XScale"),
    ("20260815_Camera-Mount", "Camera-Mount"),
    ("20260816_120000_Rev-runBoresight", "Rev-runBoresight"),
    ("20260816_120000_PaveBoresight", "PaveBoresight"),
    ("20260816_120000_ROWCamera", "ROWCamera"),
])
def test_parse_every_owner_defined_type(name, ftype):
    """Every type on the master list must survive a round trip."""
    assert parse_event_folder(name)[1] == ftype


@pytest.mark.parametrize("name", [
    "README.md", "PaveIntrinsic", "2026_PaveIntrinsic", "20261301_PaveIntrinsic",
])
def test_parse_rejects_non_event_folders(name):
    assert parse_event_folder(name) is None


@pytest.mark.parametrize("name", [
    "20260815_PaveIntrinsic.VOID",
    "20260815_202357_PaveIntrinsic.VOID",
    "20260815_202357_PaveIntrinsic.void",
])
def test_void_folders_never_parse(name):
    """A VOIDed folder must never be selectable, whatever shape it has."""
    assert parse_event_folder(name) is None


# ── Store location ───────────────────────────────────────────────────────────

def test_store_path_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_STORE", str(tmp_path))
    assert store_path() == Path(str(tmp_path))


def test_store_available_false_for_missing(tmp_path):
    assert store_available(tmp_path / "nope") is False


# ── publish ──────────────────────────────────────────────────────────────────

def test_publish_creates_event_folder_and_file(written_yaml, store):
    out = publish(written_yaml, "PAVE", "234500499", _DT, store)
    assert out.exists()
    assert out.name == "PAVE_234500499.yaml"
    assert out.parent.name == "20260815_202357_PaveIntrinsic"
    assert out.parent.parent == store


def test_publish_keeps_local_file(written_yaml, store):
    publish(written_yaml, "PAVE", "234500499", _DT, store)
    assert written_yaml.exists(), "the working copy must stay next to the images"


def test_publish_content_matches(written_yaml, store):
    out = publish(written_yaml, "PAVE", "234500499", _DT, store)
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == yaml.safe_load(
        written_yaml.read_text(encoding="utf-8")
    )


def test_published_yaml_carries_role(written_yaml, store):
    out = publish(written_yaml, "PAVE", "234500499", _DT, store)
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["camera_role"] == "PAVE"


def test_publish_is_append_only(written_yaml, store):
    publish(written_yaml, "PAVE", "234500499", _DT, store)
    with pytest.raises(StoreError, match="append-only"):
        publish(written_yaml, "PAVE", "234500499", _DT, store)


def test_publish_does_not_touch_existing_file(written_yaml, store):
    out = publish(written_yaml, "PAVE", "234500499", _DT, store)
    before = out.read_bytes()
    with pytest.raises(StoreError):
        publish(written_yaml, "PAVE", "234500499", _DT, store)
    assert out.read_bytes() == before


def test_each_camera_gets_its_own_folder(written_yaml, store):
    """Two cameras saved in the same second must not share a folder."""
    a = publish(written_yaml, "PAVE", "234500499", _DT, store)
    b = publish(written_yaml, "ROW", "262503744", _DT, store)
    assert a.parent != b.parent
    assert a.parent.name.endswith("_PaveIntrinsic")
    assert b.parent.name.endswith("_ROWIntrinsic")


def test_publish_refuses_undefined_role(written_yaml, store):
    """A bench run must not invent a type name in the shared store."""
    with pytest.raises(StoreError, match="No calibration-store type"):
        publish(written_yaml, "BENCH", "234500499", _DT, store)
    assert list(store.iterdir()) == []


def test_publish_second_event_same_day_is_fine(written_yaml, store):
    publish(written_yaml, "PAVE", "234500499", _DT, store)
    later = publish(written_yaml, "PAVE", "234500499",
                    datetime(2026, 8, 15, 21, 0, 0), store)
    assert later.exists()
    assert len([d for d in store.iterdir() if d.is_dir()]) == 2


def test_publish_missing_store_raises(written_yaml, tmp_path):
    with pytest.raises(StoreError, match="not reachable"):
        publish(written_yaml, "PAVE", "234500499", _DT, tmp_path / "no_such_folder")


def test_publish_missing_source_raises(store, tmp_path):
    with pytest.raises(StoreError, match="not found"):
        publish(tmp_path / "ghost.yaml", "PAVE", "234500499", _DT, store)


def test_publish_rejects_bad_serial(written_yaml, store):
    """A typo must never become a permanent filename."""
    with pytest.raises(StoreError):
        publish(written_yaml, "PAVE", "2345 00499", _DT, store)
    assert list(store.iterdir()) == []


# ── find_latest — the selection rule ─────────────────────────────────────────

def test_find_latest_none_when_empty(store):
    assert find_latest("PAVE", "234500499", _DT, store) is None


def test_find_latest_finds_published(written_yaml, store):
    out = publish(written_yaml, "PAVE", "234500499", _DT, store)
    assert find_latest("PAVE", "234500499", datetime(2026, 9, 1), store) == out


def test_find_latest_reads_date_only_baseline_folder(written_yaml, store):
    """The seeded 20260815_PaveIntrinsic folder must be selectable."""
    baseline = store / "20260815_PaveIntrinsic"
    baseline.mkdir()
    (baseline / "PAVE_234500499.yaml").write_bytes(written_yaml.read_bytes())
    found = find_latest("PAVE", "234500499", datetime(2026, 8, 16), store)
    assert found is not None and found.parent == baseline


def test_find_latest_ignores_future_calibrations(written_yaml, store):
    """Reprocessing an old collection must not pick up a later calibration."""
    publish(written_yaml, "PAVE", "234500499", datetime(2026, 8, 20, 12, 0, 0), store)
    assert find_latest("PAVE", "234500499", datetime(2026, 8, 16), store) is None


def test_find_latest_picks_newest_in_force(written_yaml, store):
    publish(written_yaml, "PAVE", "234500499", datetime(2026, 8, 15, 9, 0, 0), store)
    newer = publish(written_yaml, "PAVE", "234500499",
                    datetime(2026, 8, 18, 9, 0, 0), store)
    latest = publish(written_yaml, "PAVE", "234500499",
                     datetime(2026, 8, 25, 9, 0, 0), store)
    assert find_latest("PAVE", "234500499", datetime(2026, 8, 20), store) == newer
    assert find_latest("PAVE", "234500499", datetime(2026, 9, 1), store) == latest


def test_find_latest_is_per_camera_not_per_folder(written_yaml, store):
    """The newest Intrinsic folder may not hold every camera.

    Cameras are calibrated one at a time, so ROW's calibration can live in an
    older folder than PAVE's.  Selection must still find it.
    """
    row = publish(written_yaml, "ROW", "262503744",
                  datetime(2026, 8, 15, 9, 0, 0), store)
    publish(written_yaml, "PAVE", "234500499",
            datetime(2026, 8, 20, 9, 0, 0), store)
    assert find_latest("ROW", "262503744", datetime(2026, 9, 1), store) == row


def test_find_latest_skips_void_folders(written_yaml, store):
    out = publish(written_yaml, "PAVE", "234500499", _DT, store)
    out.parent.rename(out.parent.with_name(out.parent.name + ".VOID"))
    assert find_latest("PAVE", "234500499", datetime(2026, 9, 1), store) is None


def test_find_latest_never_crosses_camera_types(written_yaml, store):
    """A newer PAVE calibration must not shadow ROW's, and vice versa."""
    row = publish(written_yaml, "ROW", "262503744",
                  datetime(2026, 8, 15, 9, 0, 0), store)
    pave = publish(written_yaml, "PAVE", "234500499",
                   datetime(2026, 9, 1, 10, 0, 0), store)
    at = datetime(2026, 9, 2)
    assert find_latest("PAVE", "234500499", at, store) == pave
    assert find_latest("ROW", "262503744", at, store) == row


def test_find_latest_refuses_undefined_role(written_yaml, store):
    with pytest.raises(StoreError):
        find_latest("BENCH", "234500499", _DT, store)


def test_find_latest_ignores_other_types(written_yaml, store):
    other = store / "20260816_ROWIntrinsic"
    other.mkdir()
    (other / "PAVE_234500499.yaml").write_bytes(written_yaml.read_bytes())
    assert find_latest("PAVE", "234500499", datetime(2026, 9, 1), store) is None


def test_find_latest_ignores_loose_files(written_yaml, store):
    (store / "README.md").write_text("not a calibration", encoding="utf-8")
    assert find_latest("PAVE", "234500499", datetime(2026, 9, 1), store) is None


def test_find_latest_missing_store_returns_none(tmp_path):
    assert find_latest("PAVE", "234500499", _DT, tmp_path / "gone") is None


# ── Quality gate — only a passing calibration may be published ───────────────

def test_check_publishable_accepts_a_pass(tmp_path):
    path = _write_cal(tmp_path, passed=True)
    assert check_publishable(path, True) == "PASS"


def test_check_publishable_rejects_not_passed(tmp_path):
    path = _write_cal(tmp_path, passed=False)
    with pytest.raises(StoreError, match="did not pass its grade"):
        check_publishable(path, False)


def test_check_publishable_names_the_reason(tmp_path):
    """The message must say what went wrong, not just 'failed'."""
    path = _write_cal(tmp_path, passed=False)
    with pytest.raises(StoreError, match="2 red areas"):
        check_publishable(path, False)


def test_check_publishable_rejects_failing_file_even_if_flag_says_pass(tmp_path):
    """A wrong caller flag must not wave a failing calibration through."""
    path = _write_cal(tmp_path, passed=False)
    with pytest.raises(StoreError, match="did not pass its grade"):
        check_publishable(path, passed=True)


def test_check_publishable_rejects_passing_file_when_run_failed(tmp_path):
    path = _write_cal(tmp_path, passed=True)
    with pytest.raises(StoreError, match="run did not pass"):
        check_publishable(path, passed=False)


def test_check_publishable_rejects_file_without_grade(tmp_path):
    """Old files (before 2026-10-31) carry only the RMS verdict: refused."""
    path = tmp_path / "old.yaml"
    path.write_text("serial_number: '234500499'\nverdict: Excellent\n", encoding="utf-8")
    with pytest.raises(StoreError, match="no grade"):
        check_publishable(path, passed=True)


def test_check_publishable_rejects_unreadable_file(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("verdict: [unclosed\n", encoding="utf-8")
    with pytest.raises(StoreError):
        check_publishable(path, passed=True)


def test_publish_refuses_failed_calibration(tmp_path, store):
    path = _write_cal(tmp_path, passed=False)
    with pytest.raises(StoreError):
        publish(path, "PAVE", "234500499", _DT, store, passed=False)
    assert list(store.iterdir()) == [], "nothing may be created for a failed run"


def test_publish_keeps_local_files_for_a_failed_run(tmp_path, store):
    path = _write_cal(tmp_path, passed=False)
    with pytest.raises(StoreError):
        publish(path, "PAVE", "234500499", _DT, store, passed=False)
    assert path.exists(), "a failed run still keeps its working files"


def test_publish_accepts_a_passing_calibration(tmp_path, store):
    path = _write_cal(tmp_path, passed=True)
    out = publish(path, "PAVE", "234500499", _DT, store, passed=True)
    assert out.exists()
