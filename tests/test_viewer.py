"""Pop-up photo check (src/viewer): isolated, reads only the files beside the photos."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _photo_folder(tmp_path):
    cv2.imwrite(str(tmp_path / "a.jpg"), np.full((540, 960, 3), 200, np.uint8))
    (tmp_path / "a.dots.json").write_text(json.dumps({
        "run_id": "RUN_1", "photo": "a.jpg", "status": "used", "why": "", "dots_found": 2,
        "dots": [{"n": 0, "x_px": 100.0, "y_px": 100.0, "fit_px": 0.5},
                 {"n": 7, "x_px": 300.0, "y_px": 200.0, "fit_px": None}]}))
    (tmp_path / "NotUsed").mkdir()
    cv2.imwrite(str(tmp_path / "NotUsed" / "b.jpg"), np.zeros((540, 960, 3), np.uint8))
    (tmp_path / "NotUsed" / "b.dots.json").write_text(json.dumps(
        {"photo": "b.jpg", "status": "not used", "why": "No board found", "dots": []}))
    (tmp_path / "RUN_1.json").write_text(json.dumps(
        {"run_id": "RUN_1", "pc": {"computer": "ARAN69-ROW"}, "result": {"grade": {"headline": "PASS"}}, "saved": None}))


def test_viewer_lists_and_draws(app, tmp_path):
    from src.viewer import AnnotationViewer
    _photo_folder(tmp_path)
    w = AnnotationViewer(str(tmp_path))
    assert w.list.count() == 2 and "RUN_1" in w.runs.text() and "ARAN69-ROW" in w.runs.text()
    w.filter.setCurrentText("Not used")
    assert w.list.count() == 1 and "No board found" in w.info.toPlainText()
    w.filter.setCurrentText("Used")
    assert w.list.count() == 1 and "Dots found: 2" in w.info.toPlainText()


def test_draw_targets(app, tmp_path):
    from PySide6.QtGui import QPixmap
    from src.viewer.annotation_viewer import draw
    pix = QPixmap(960, 540)
    doc = {"targets": [{"id": "1", "found": True, "used": True, "x_px": 50, "y_px": 50, "miss_mm": 7.0},
                       {"id": "50", "found": True, "used": False, "x_px": 90, "y_px": 90,
                        "dropped_why": "missed by 9 px: x", "found_by": "second look"},
                       {"id": "2", "found": False, "predicted_x_px": 200, "predicted_y_px": 200}]}
    out = draw(pix, tmp_path / "x.targets.json", doc)
    assert out.width() == 960 and not out.isNull()


def test_viewer_is_isolated():
    """The viewer imports nothing from the rest of the app."""
    import ast
    from pathlib import Path
    for f in (Path(__file__).resolve().parent.parent / "src" / "viewer").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                assert not (mod or "").startswith("src.") or mod.startswith("src.viewer"), (f.name, mod)
