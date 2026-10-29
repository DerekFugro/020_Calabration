# Randot-003 (label "roadware_140_60_003") random-dot board

- Type: random-dot board, 40 dots. Not supported by the 020_Calabration app (the app only detects chessboards).
- Layout file: `Randot-003_roadware_140_60_003(in).csv` (copied from 005_CalibrationFIles\20261008_New_Surveyor\...\Board\Rear; same file as in 100_AllCalibrations\20261008_PaveIntrinsic).
- Page size 1400 x 600 mm, blue frame 1360 x 540 mm (from the PNG at 2 px/mm; the physical board was not tape-measured).
- Dot centres span x -0.644 to +0.642 m, z -0.235 to +0.230 m. Dot radii: 0.026 to 0.052 m.
- Board image: `Randot-003_roadware_140_60_003.png` (2799 x 1199 px, exactly 2 px/mm). From Downloads, where it was named `.pdf` but is really a PNG image, so it was renamed. It shows the label "roadware_140_60_003", 40 dots, a blue frame and blue centre lines. All 40 dots match the CSV to within 0.05 px.
- Print file: `Randot-003_roadware_140_60_003.pdf` - true-scale vector PDF, page 1400 x 600 mm, made by Claude on 2026-10-29 from the CSV with `..\make_dot_board_pdf.py`. Layout copied from the PNG: blue frame 1360 x 540 mm, 1 mm blue lines, board centre 309.5 mm from the page top (the PNG is not centred top-to-bottom), label top-left. Rendered back and checked against the PNG: black areas differ by 0.7% (edge pixels only).
- Before using a reprint: measure two far-apart dot centres with a tape and check against the CSV.
- The CSV in Downloads has the same numbers as this one; only the line endings differ.
- Used for: Rear (PAVE) camera 262503744 intrinsic, 2026-10-08 (100_AllCalibrations\20261008_PaveIntrinsic).

## CSV columns (space separated, metres)

Read from the file. Column meaning is inferred from the values.

| Col | Meaning |
|---|---|
| 1 | Always 0 |
| 2 | Dot ID (0-39) |
| 3 | X of dot centre |
| 4 | Always 0 (board plane) |
| 5 | Z of dot centre |
| 6-8 | Board normal (0, -1, 0) |
| 9 | Dot radius (checked against the ikea_road PDF: centre dot 0.025 in the CSV = 50 mm diameter on the print) |
