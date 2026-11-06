"""Open a saved lens calibration as if it had just been processed (src/load_saved.py)."""

from __future__ import annotations

import json

import cv2
import numpy as np
import yaml


def _saved_folder(tmp_path, run_id="RUN_20260403_101010"):
    K = np.array([[1000.0, 0, 960], [0, 1000.0, 540], [0, 0, 1]])
    D = np.zeros(5)
    obj = np.array([[x * 30.0, y * 30.0, 0] for y in range(6) for x in range(8)], np.float64)
    for k in range(4):
        rv, tv = np.array([0.15 * k - 0.2, 0.1, 0.0]), np.array([-100.0, -80.0, 600.0 + 40 * k])
        img, _ = cv2.projectPoints(obj, rv, tv, K, D)
        img = img.reshape(-1, 2)
        (tmp_path / f"p{k}.jpg").write_bytes(b"x")
        (tmp_path / f"p{k}.dots.json").write_text(json.dumps({
            "run_id": run_id, "photo": f"p{k}.jpg", "image_size": [1920, 1080],
            "status": "used" if k < 3 else "left out automatically", "why": "" if k < 3 else "fits worse",
            "edge_blur_px": 1.1,
            "dots": [{"n": i, "x_px": float(x), "y_px": float(y), "board_x_mm": float(o[0]),
                      "board_y_mm": float(o[1]), "fit_px": 0.0} for i, ((x, y), o) in enumerate(zip(img, obj))]}))
    y = tmp_path / "CAL_2001964_20260403_101500.yaml"
    y.write_text(yaml.safe_dump({
        "serial_number": "2001964", "camera_role": "ROW", "calibration_datetime": "2026-04-03T10:15:00",
        "app_version": "abc1234 2026-11-06", "run_id": run_id, "rms_reprojection_error": 0.5,
        "image_count_used": 3, "camera_matrix": {"data": K.ravel().tolist()},
        "dist_coeffs": {"data": D.tolist()}, "image_resolution": {"width": 1920, "height": 1080},
        "board": {"name": "no_such_board"},
        "grade": {"passed": True, "headline": "PASS: good enough to use.", "reasons": [], "warnings": [],
                  "hard_stops": [], "repeatability_p95_mrad": 0.2, "dot_edge_blur_median_px": 1.1}}))
    (tmp_path / f"{run_id}.json").write_text(json.dumps({"run_id": run_id, "pc": {"computer": "ARAN69-ROW"}}))
    return y


def test_load_saved_rebuilds_the_report(tmp_path):
    from src.coverage import compute_grid
    from src.load_saved import load_saved
    run = load_saved(_saved_folder(tmp_path))
    assert run.saved_serial == "2001964" and run.saved_role == "ROW"
    assert len(run.cal.points_used) == 3 and len(run.cal.auto_removed) == 1 and len(run.detections) == 4
    assert run.grade.passed and run.grade.steady[1] == "2 mm"
    assert "LOADED from CAL_2001964" in run.loaded_note and "ARAN69-ROW" in run.loaded_note
    assert run.run_log.endswith("RUN_20260403_101010.json")
    g = compute_grid(run.cal)                       # the 3x3 squares can be drawn
    assert sum(c.points for row in g.cells for c in row) == 3 * 48


def test_compare_and_record_check(tmp_path):
    from types import SimpleNamespace
    from src.load_saved import compare, load_saved, record_check
    run = load_saved(_saved_folder(tmp_path))
    same = SimpleNamespace(error="", cal=run.cal, grade=run.grade, passed=True)
    agrees, text = compare(run, same)
    assert agrees and "AGREES" in text and "0.0 mm" in text
    K2 = run.cal.camera_matrix.copy(); K2[0, 0] *= 1.02; K2[1, 1] *= 1.02
    other = SimpleNamespace(error="", cal=SimpleNamespace(camera_matrix=K2, dist_coeffs=run.cal.dist_coeffs,
                                                          image_size=run.cal.image_size, image_count_used=3),
                            grade=run.grade, passed=True)
    agrees2, text2 = compare(run, other)
    assert not agrees2 and "DOES NOT AGREE" in text2
    record_check(run.run_log, agrees2, text2)
    assert json.loads(open(run.run_log).read())["checks"][0]["agrees"] is False


def test_old_folder_without_dots_files(tmp_path):
    from src.load_saved import load_saved
    y = _saved_folder(tmp_path)
    for f in tmp_path.glob("*.dots.json"):
        f.unlink()
    run = load_saved(y)
    assert run.cal.points_used == [] and "No .dots.json files here" in run.loaded_note
