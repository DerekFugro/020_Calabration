# Chessboard 12x8 (the app's original board)

- 12 x 8 squares, 11 x 7 inside corners, 76.39 mm squares (calipers 2026-08-18, see references/BoardTrueSize.md).
- The physical board is a plain chessboard with a **square-in-square marker** (dark cell, centred white hole) in each corner cell; its top-left square is white. Not ArUco.
- The app finds the corners with OpenCV's chessboard finders; when they miss (often on 4K GOX photos) it uses this board's own finder, `src/marker_finder.py`, which anchors on the four markers (`finder: corner_markers` in `board.yaml`; 2026-11-14).
- `calibration_board_plain.pdf` / `.png`: faithful copy of the physical board (made by `generate_board_plain.py`; pattern corrected 2026-11-14 — it was one square out).
- `calibration_board.pdf` / `.png`: an ArUco (ChArUco) version made by `generate_board.py`; this is **not** the physical board.
- `board_ground_truth.pdf`: measurement sheet for the board (made by `generate_ground_truth_pdf.py`).
- Run the scripts from the app folder, e.g. `python Cal_board/Chessboard_12x8/generate_board.py`. They write into this folder.
- Moved here from Cal_board\ on 2026-10-29.
