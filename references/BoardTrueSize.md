# Calibration board — true measured size

**Status:** LIVE reference for this app. Measurement of record for the physical
board.
**Measured:** 2026-08-18 by Derek, digital calipers.
**In force:** `src/board.py` uses these values as of 2026-08-18
(`DEFAULT_CELL_WIDTH_MM = DEFAULT_CELL_HEIGHT_MM = 76.39`).
**Related:** `CalibrationBoard.txt` (superseded 2026-08-11, history only),
master doc `H:\001_Mahine_App_Specs\MasterLeverarms and information.md` §8.

Provenance tags: **[measured]** verified against real data · **[stated]**
Derek's direct statement · **[inference]** reasoned, not proven.

---

## 1. The board

12 x 8 squares, 11 x 7 interior corners, printed on white stock mounted on
cardboard, with four square-in-square fiducial markers in the corner cells.
**[measured]** — confirmed by running `cv2.findChessboardCornersSB` over
`H:\Camera Calibration Files\Pave\TDR054S-C_234500499_260811190327_image24.png`:
locks on at 11 x 7 and returns 77 corners.

The corner fiducials are **not used**. Detection is plain chessboard; the ArUco
module is never called (see `src/detector.py`).

## 2. Measurement of record

| Quantity | Value | How |
|---|---|---|
| **Cell pitch** | **76.39 mm** | 152.78 mm across 2 cells / 2 **[measured]** |
| Cell pitch, inches | 3.0075 in | = 76.39 / 25.4 **[measured]** |
| Single grey square, own width | 76.59 mm | calipers, edge to edge **[measured]** |
| Ink spread | 0.10 mm per edge | (76.59 - 76.39) / 2 **[inference]** |

Cross-check, steel tape over 10 cells: 765 mm -> 76.50 mm/cell **[measured]**,
0.14% above the caliper figure. Consistent within tape resolution.

### Method — why 2 cells and not 1

Measure **the same edge on two cells two columns apart** (white->grey to
white->grey). Both jaws then sit on the same kind of transition and printed ink
spread cancels.

Measuring a single square's own width puts one jaw on a white->grey edge and the
other on grey->white, so the spread is added to the reading. That is exactly
what happened here: the single square read **0.20 mm** larger than the true
pitch, every time, in one direction. A repeatable bias, not noise.

> Anyone re-measuring this board: span 2 cells, same edge to same edge. Do not
> measure one square.

## 3. What the app uses, and why the change was safe

`src/board.py` sets `DEFAULT_CELL_WIDTH_MM = DEFAULT_CELL_HEIGHT_MM = 76.39`
**[measured]** as of 2026-08-18. It previously held 76.2 (3.000 in), which was
the assumed nominal and had never been measured.

**A uniform scale error in the board has no effect on the intrinsics.**
**[measured]** — tested directly by calibrating one fixed set of synthetic
images while varying only the cell size given to `calibrate()`:

| Cell size entered | fx/fy | RMS |
|---|---|---|
| 76.2 x 76.2 (truth) | 0.999986 | 0.046367 |
| 77.2 x 77.2 (+1.3%) | 0.999986 | 0.046367 |
| 70.0 x 70.0 (-8.1%) | 0.999986 | 0.046367 |
| 3.0 x 3.0 (inches, not mm) | 0.999986 | 0.046367 |
| 76.465 x 76.002 (non-square) | **0.994037** | 0.046376 |
| 76.2 x 74.0 (3% off in y) | **0.971850** | 0.046378 |

The object points scale, the recovered translation vectors scale with them, and
fx, fy, cx, cy and the distortion coefficients come out identical — even for a
25x error. Only the **ratio** between cell width and cell height moves the
result.

Note the 0.994037 row: it reproduces the fx/fy = 0.994 seen on the real Pave
camera with the superseded non-square values, which is what condemned them on
2026-08-11.

So 76.39 and 76.2 produce identical intrinsics. The change was made because the
app should state what was measured rather than what was assumed — not because
it improves anything numerically.

**Consequence for the record:** the two calibrations already in the store were
computed with 76.2 and their YAML says so. They remain valid and need no re-run:
identical inputs, identical intrinsics. New calibrations will record 76.39.
Master doc §8 still states 76.2 — a discrepancy for the owners to settle.

## 4. Squareness — the thing that actually matters

The Pave calibration of record reports **fx/fy = 0.999836** — 0.016% from
square **[measured]**, across 53 images and 77 corners each. If the board were
even 0.2% non-square, calibrating with square cells would have dragged fx/fy to
about 0.998. It did not.

**The camera measures the board's squareness roughly 10x finer than calipers
can.** Hand measurement is a gross-error check here (wrong board, inches/mm
mix-up, a warped or shrunken board), not a refinement.

## 5. Open

1. **Vertical 2-cell span not yet measured.** Section 2 is one direction only,
   so setting cell HEIGHT to 76.39 assumes the vertical matches the horizontal.
   Supporting evidence: the calibration's own fx/fy = 0.999836 says the two
   directions agree to 0.016%, far finer than calipers resolve. Worth one
   reading if the board is ever reprinted. Expect ~152.78 mm.
2. **Flatness not checked.** A bowed board is a real error source and no cell
   measurement detects it. Lay a straightedge across both diagonals.

## 6. When the absolute size DOES matter

Anything that solves distance, height or scale from the **board's pose**
(`rvecs`/`tvecs`) rather than from a physical reference. Using 76.2 where the
truth is 76.39 biases such a result by **+0.25%** **[inference]**.

`H:\Camera Calibration Files\barcheck.py` measures a known-length bar, not the
board, so it is unaffected today. If a board-pose method is ever added, use
76.39 mm and re-measure both directions first.

## 7. Change log

| Date | Change |
|---|---|
| 2026-08-18 | First issue. Caliper measurement (76.39 mm pitch), ink-spread finding, scale-invariance test. |
| 2026-08-18 | `src/board.py` defaults changed 76.2 -> 76.39 (Derek). No numerical effect; the app now states the measured value. |
