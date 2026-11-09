"""The app was renamed 020_Calabration -> SurveyorCalibration; old folders are copied once."""

from src import camera_db, paths


def test_new_name_everywhere():
    assert paths.APP_NAME == "SurveyorCalibration"
    assert camera_db.SETTINGS_DIR.name == "SurveyorCalibration"


def test_copy_missing_never_overwrites(tmp_path):
    old, new = tmp_path / "020_Calabration", tmp_path / "SurveyorCalibration"
    (old / "sub").mkdir(parents=True)
    (old / "camera_db.json").write_text("old settings")
    (old / "camera_db.secret").write_bytes(b"old secret")
    (old / "sub" / "board.yaml").write_text("b")
    new.mkdir()
    (new / "camera_db.json").write_text("new settings")      # already there: keep it
    copied = paths.copy_missing(old, new)
    assert (new / "camera_db.json").read_text() == "new settings"
    assert (new / "camera_db.secret").read_bytes() == b"old secret"
    assert (new / "sub" / "board.yaml").read_text() == "b"
    assert len(copied) == 2
    assert (old / "camera_db.json").exists()                 # old folder left alone
    assert paths.copy_missing(old, new) == []                # second run: nothing to do


def test_copy_missing_no_old_folder(tmp_path):
    assert paths.copy_missing(tmp_path / "nope", tmp_path / "new") == []
