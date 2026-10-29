# ikea_road random-dot board

- Type: random-dot board, 62 dots, with handles. Not supported by the 020_Calabration app (the app only detects chessboards).
- Files: `ikea_road.csv` (dot layout) and `ikea_road.pdf` (printable board). Copied from 005_CalibrationFIles\Intrinsic_Row\Intrinsic. All other copies on F: are identical.
- Preview: `ikea_road_preview.png` (low-res render of the PDF). The PDF has no text label; it is just the 62 dots and blue centre lines.
- PDF page size: 1500 x 750 mm.
- Dot centres span x -0.696 to +0.692 m, z -0.316 to +0.318 m. Dot radii: 0.025 to 0.050 m.
- Used for: ROW camera 234500499 intrinsic (provisional), 2026-10-08 (100_AllCalibrations\20261008_ROWIntrinsic).

## CSV columns (space separated, metres)

Read from the file. Column meaning is inferred from the values.

| Col | Meaning |
|---|---|
| 1 | Always 0 |
| 2 | Dot ID (0-61) |
| 3 | X of dot centre |
| 4 | Always 0 (board plane) |
| 5 | Z of dot centre |
| 6-8 | Board normal (0, -1, 0) |
| 9 | Dot radius (checked against the ikea_road PDF: centre dot 0.025 in the CSV = 50 mm diameter on the print) |
