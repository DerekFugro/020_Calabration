# 020_Calabration — camera calibration for the ARAN fleet

Three stages: **lens (intrinsic) → camera position (Old School extrinsic) → loop**.
The app does the clicking and the checking itself, grades every result
**PASS / NOT PASSED** (one rating, everywhere), and tells the crew what to
re-shoot.

```powershell
uv run python main.py          # or double-click launch.bat
```

## Tabs

| Tab | What it does |
|---|---|
| **Load Intrinsic** (one camera at a time) | Pick the photo folder, camera and serial (both blank at start, typed every time), Run. If the folder was calibrated before, you can **Open results** or **Reprocess**. The report shows the PASS / NOT PASSED banner, why, what to shoot next, the 3×3 coverage grid, photos left out, and the numbers. **Save** writes `CAL_<serial>_<date>.yaml/.pdf` next to the photos, every format into `Calibration_<date>\` (fleet cameras), all next to the photos. |
| **Load Extrinsic** (one camera at a time) | Pick one camera's Old School folder and its lens (this session's Load Intrinsic result or a lens file). Old School photos → camera angles, height and lever arms. A lens that did not pass (or was never graded by this app) can be used for now: it is flagged with a warning on the screen, in the YAML and on the office page. Finds and labels the wall discs and tennis balls itself (old EOP files are never read; the app writes the EOPs), drops wrong targets, solves and combines the setups. Control is always the tennis-ball GCP in `control/Richmond` (never the revised GCP). *Save all formats* writes EOP + overlay per setup, YAML, JSON, CSV, PDF, PGExteriorCalibration RWC (angles unverified) and a one-page **`_CHECK.html`** for the office into `Extrinsic_<date>\`. |
| **Boards** | Add a board (dot layout CSV or chessboard) to `Cal_board\`, print the true-scale PDF, measure it (two readings each, saved automatically), test auto-detect. |
| Capture Intrinsic / Capture Extrinsic | Planned. |

## How a lens calibration is made (`src/pipeline.py`)

One path for Load Intrinsic and the CLI (`run_folder`):

1. `.raw` → PNG (Lucid frames), board auto-detected from the library.
2. Dots / corners found in every photo (in parallel).
3. Photos that can never be used (unreadable, no board, wrong image size) are
   moved to `NotUsed\` with `NotUsed\why.txt` (`src/not_used.py`; nothing moves
   if more than half look unusable).
4. Calibrate; photos that fit much worse than the rest, or are blurry in a
   sharp set, are left out automatically and listed (`src/auto_clean.py`).
5. Grade (`src/grading.py`). **PASS** needs all of:
   - no hard stop (NaN, placeholder values, implausible focal length);
   - repeatability: the photos split into two random halves (6 times, median) agree within
     0.6 mrad (6 mm at 10 m) — changed 2026-11-02 from first-vs-second half at 10 mm;
   - every 3×3 area has enough points and tilt (**no red area**: red = too few points or too little tilt);
   - not too blurry: dot edge blur ≤ 2.2 px at 1920 wide (4.4 px at 4K); a warning above 1.6 px (3.2 px at 4K).

   RMS and the pixel error in each square are shown but don't fail a calibration (2026-11-03):
   on 68 fleet cameras they did not predict real error, and blur and 4K inflate them.

## Camera position (Old School) pass rules (`src/extrinsic/run.py`)

Per setup: ≥ 10 targets, leave-one-out miss ≤ 20 mm. Per camera: ≥ 3 setups,
directions agree within 1.5°, height within 0.20 m. Camera names come from
where the camera points (ROW 0°, FR +45°, FL −45°, Right +90°, Left −90°,
RR +135°, RL −135°; closest wins).

## Files written

| Where | What |
|---|---|
| photo folder | `CAL_<serial>_<date>.yaml` + `.pdf` (grade, numbers, photos left out) |
| `Calibration_<date>\` | fleet XML, PG RWC, OpenCV YAML/XML, ROS, Kalibr, COLMAP, Metashape, JSON, CSV |
| `Extrinsic_<date>\` | EOP + overlay per setup, YAML, JSON, CSV, PDF, RWC, `_CHECK.html` |

Anything that did not pass is still written, with a `NOT_PASSED_` prefix.

**Everything is saved next to the photos, and nowhere else.**  There is no shared
calibration store any more (2026-11-05: the app is now a generic calibration tool).

## Command line (no GUI)

```powershell
uv run python cli.py --list-boards
uv run python cli.py "F:\path\to\photos"                         # auto-detect, grade
uv run python cli.py "F:\path\to\photos" --serial 101324 --role ROW --save
uv run python cli.py "F:\path\to\photos" --van ARAN65 --role ForwardRight --serial 101324 --export OUT
uv run python cli.py --grade-all "F:\Camera Calibrations" --csv grades.csv --workers 8
```

The CLI leaves the photo folder alone unless `--move-unused` is given (then it
converts `.raw` and moves unusable photos like the GUI), so old data can be
checked without rearranging it.

## Tests

```powershell
uv run pytest
```

`pytest.ini` limits the run to `tests\` (scratch scripts in `ForClaude\` are
not tests). Self-contained: synthetic images, temp folders, offscreen Qt.

## Project layout

```
main.py, launch.bat        start the GUI
cli.py                     command line
check_env.py               dependency check
Cal_board\                 board library (one folder per board, board.yaml)
control\Richmond\          tennis-ball GCP, site.yaml, seeds.yaml
references\                measurement records and history

src  pipeline.py              THE lens calibration path (run_folder)
  workers.py               GUI threads (FolderWorker, VanIntrinsicWorker)
  boards.py, board.py, board_builder.py, auto_detect.py
  detector.py, dot_detector.py, image_filter.py, raw_loader.py, utils.py
  calibrator.py, auto_clean.py, grading.py, coverage.py, not_used.py
  output_writer.py         CAL_ YAML + PDF
  export_formats.py        every other format
  previous_runs.py         "already calibrated?" check
  photo_folders.py, van_scan.py, styles.py
  extrinsic\               Old School: oldschool, control, geo, targets, solve, run,
                           outputs, report (PDF), html_report (_CHECK.html), intrinsic_source
  widgets    app_window.py          tabs, van bar, the one status bar
    one_camera_screen.py   One camera: setup -> report, save
    setup_screen.py, report_screen.py
    extrinsic_screen.py (one camera), boards_tab.py, zoom_view.py
```

## Notes

- `DetectionResult.charuco_corners` / `.charuco_ids` are historical names; they
  hold plain chessboard corners or dot centres.
- The chessboard board's measured cell size (76.39 mm) is recorded in
  `references/BoardTrueSize.md`.
