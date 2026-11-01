"""The image folder and NotUsed folder are recorded in every result."""
from types import SimpleNamespace

from src.photo_folders import folder_lines, folder_summary


def test_folder_summary_counts_not_used(tmp_path):
    nu = tmp_path / "NotUsed"; nu.mkdir()
    (nu / "a.jpg").write_bytes(b"x"); (nu / "b.png").write_bytes(b"x"); (nu / "why.txt").write_text("x")
    cal = SimpleNamespace(image_count_used=40, auto_removed=[("p.jpg", "high error")])
    s = folder_summary(cal, tmp_path)
    assert s["image_folder"] == str(tmp_path.resolve())
    assert s["photos_used"] == 40 and s["photos_left_out_automatically"] == 1
    assert s["photos_in_not_used"] == 2 and s["not_used_folder"].endswith("NotUsed")
    text = "\n".join(folder_lines(cal, tmp_path))
    assert "Image folder:" in text and "2 in NotUsed" in text


def test_no_not_used_folder(tmp_path):
    cal = SimpleNamespace(image_count_used=20, auto_removed=[])
    lines = folder_lines(cal, tmp_path)
    assert len(lines) == 2 and "NotUsed" not in lines[1]
