# Chessboard 12x8 (the app's original board)

- 12 x 8 squares, 11 x 7 inside corners, 76.39 mm squares (calipers 2026-08-18, see references/BoardTrueSize.md).
- The printed board has ArUco markers in the white squares; the app ignores them and finds the plain chessboard corners.
- `calibration_board.pdf` / `.png`: board with ArUco markers (made by `generate_board.py`).
- `calibration_board_plain.pdf` / `.png`: plain chessboard (made by `generate_board_plain.py`).
- `board_ground_truth.pdf`: measurement sheet for the board (made by `generate_ground_truth_pdf.py`).
- Run the scripts from the app folder, e.g. `python Cal_board/Chessboard_12x8/generate_board.py`. They write into this folder.
- Moved here from Cal_board\ on 2026-10-29.
