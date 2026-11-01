"""Tests for src/not_used.py — moving unusable photos to NotUsed."""
import os

from src.detector import DetectionResult
from src.image_filter import FilterResult
from src.not_used import NOT_USED_DIR, mark_wrong_size, move_unusable, unusable
from src.utils import find_images


def _set(tmp_path, specs):
    """specs: list of (name, size, corners, load_error)."""
    dets, filts = [], []
    for name, size, corners, err in specs:
        p = tmp_path / name; p.write_bytes(b"x")
        dets.append(DetectionResult(str(p), size, None, None, corners, 50.0, load_error=err))
        if err:
            filts.append(FilterResult(False, "Load error: bad", 0, 0.0))
        elif corners < 12:
            filts.append(FilterResult(False, f"Too few corners detected ({corners} < 12)", corners, 50.0))
        else:
            filts.append(FilterResult(True, "", corners, 50.0))
    return dets, filts


def test_moves_only_unusable_and_logs(tmp_path):
    good = [(f"g{i}.jpg", (1920, 1080), 80, False) for i in range(8)]
    dets, filts = _set(tmp_path, good + [("noboard.jpg", (1920, 1080), 0, False),
                                         ("broken.jpg", (1920, 1080), 0, True),
                                         ("small.jpg", (1280, 720), 80, False)])
    # a high-error photo is accepted at this stage and must never move
    mark_wrong_size(dets, filts)
    assert not filts[-1].accepted and "Wrong image size" in filts[-1].reason
    moved, note = move_unusable(str(tmp_path), dets, filts)
    names = {n for n, _ in moved}
    assert names == {"noboard.jpg", "broken.jpg", "small.jpg"}
    assert dict(moved)["noboard.jpg"] == "No board found"
    assert all(os.path.exists(tmp_path / f"g{i}.jpg") for i in range(8))
    assert (tmp_path / NOT_USED_DIR / "why.txt").read_text().count("\n") == 4
    assert dets[8].image_path.endswith(os.path.join(NOT_USED_DIR, "noboard.jpg"))
    assert "Moved 3" in note
    # later runs don't see NotUsed
    assert all(NOT_USED_DIR not in p for p in find_images(str(tmp_path)))


def test_blur_rejections_stay(tmp_path):
    dets, filts = _set(tmp_path, [(f"g{i}.jpg", (1920, 1080), 80, False) for i in range(4)])
    filts[0] = FilterResult(False, "Image too blurry (blur score 5.0 < 20.0)", 80, 5.0)
    assert unusable(dets, filts) == []
    moved, note = move_unusable(str(tmp_path), dets, filts)
    assert moved == [] and note == "" and not (tmp_path / NOT_USED_DIR).exists()


def test_refuses_when_most_photos_unusable(tmp_path):
    dets, filts = _set(tmp_path, [(f"n{i}.jpg", (1920, 1080), 0, False) for i in range(6)]
                       + [("g.jpg", (1920, 1080), 80, False)])
    moved, note = move_unusable(str(tmp_path), dets, filts)
    assert moved == [] and "none were moved" in note
    assert len(find_images(str(tmp_path))) == 7


def test_name_clash_gets_suffix(tmp_path):
    (tmp_path / NOT_USED_DIR).mkdir()
    (tmp_path / NOT_USED_DIR / "a.jpg").write_bytes(b"old")
    dets, filts = _set(tmp_path, [("a.jpg", (1920, 1080), 0, False)]
                       + [(f"g{i}.jpg", (1920, 1080), 80, False) for i in range(3)])
    moved, _ = move_unusable(str(tmp_path), dets, filts)
    assert moved[0][0] == "a_1.jpg"
    assert (tmp_path / NOT_USED_DIR / "a.jpg").read_bytes() == b"old"
