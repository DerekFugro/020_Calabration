# SurveyorCalibration (repo 020_Calabration) — camera calibration for the ARAN fleet

Two programs, one installer:

- **SurveyorCalibration** — lens (intrinsic) and camera position (Old School extrinsic)
  calibration. Grades every result **PASS / NOT PASSED** (one rating, everywhere) and
  tells the crew what to re-shoot.
- **SurveyorCapture** — live picture from one van camera; grabs the board photos
  (by hand, countdown, or **Auto grab**) into a folder for the calibration app.

```powershell
uv run python main.py              # SurveyorCalibration (or double-click launch.bat)
uv run python -m src.capture       # SurveyorCapture on its own
uv run pytest                      # tests (300+)
```

The version (git commit + date) is shown in both window titles.

## Start screen

The calibration app opens on a small start screen every time. It checks the van
database in the background (`<VAN>-SERVER` from the PC name, Windows sign-in only, read
only) and shows **Use the van database** (ticked when found; untick it to work on photos
from another van). Choices:

| Choice | Opens |
|---|---|
| **Collect lens photos** | SurveyorCapture, as its own process (`--van`, `--no-db` when unticked) |
| **Calibrate lens** | main window, Load Intrinsic |
| Collect Old School photos | greyed out (later, Capture Phase 8) |
| **Camera position** | main window, Load Extrinsic |
| Boards… | main window, Boards |

`main.py --folder <photos> [--camera ROW]` skips the start screen (used by Capture's
"Open in calibration app"): Load Intrinsic opens on that folder with the camera picked.

## Main window

**Top bar** (shared by the tabs): **Home** (back to the start screen with a clean slate;
asks first if a result is not saved), **Van**, **Camera**, **Serial**, and the buttons of the
tab you are on. With the van database on, the camera list comes from the database
(newest configuration only) and the serial is filled in and locked (**Edit** unlocks
it). With it off, pick the camera from the usual list and type the serial.

| Tab | What it does |
|---|---|
| **Load Intrinsic** (one camera) | Pick the photo folder, Run. If the folder was calibrated before, **Open results** or **Reprocess**. The report shows the PASS / NOT PASSED banner, why, what to shoot next, the 3×3 coverage grid, photos left out and the numbers. **Check by re-running** compares a saved result with today's app. **Save all formats** writes `CAL_<serial>_<date>.yaml/.pdf` next to the photos and every fleet format into `Calibration_<date>\`. **Open report** opens the PDF. |
| **Load Extrinsic** (one camera) | Pick one camera's Old School folder; the lens is this session's Load Intrinsic result for the camera in the bar (or a lens file). Finds the wall discs and tennis balls itself, drops wrong targets, solves and combines the setups. Control is always the tennis-ball GCP in `control/Richmond`. If the folder was solved before you are asked: open it or solve again. **Save all formats** writes `<setup>\<photo>.EOP` beside each photo exactly as the old Old School program did, plus overlays, YAML, JSON, CSV, PDF, RWC and the office page `_CHECK.html` into `Extrinsic_<date>\`. A lens that did not pass is flagged everywhere. |
| **Boards** | Add a board (dot layout CSV or chessboard) to the board library, print the true-scale PDF, measure it, test auto-detect. |

**Saving again never leaves two answers side by side:** earlier results in the folder
(CAL_ files, `Calibration_*`, `Extrinsic_*`, EOPs beside the photos) are moved to a
`Superseded\` subfolder first (`src/superseded.py`).

## SurveyorCapture

- **Camera list:** from the van database (newest configuration; serial and size known),
  or every Windows video input (say which camera it is, type the serial). Inputs are
  found by **name**, never by number.
- **Cameras:** Magewell HDMI/SDI inputs (DirectShow) and **GOX CoaXPress cameras on the
  BitFlow card** (`src/capture/bitflow.py`). For the GOX, Capture switches the camera's
  trigger off (free run) while it has the camera and **puts the trigger back on close**;
  if Capture crashes, the next open still restores it (the original is noted in
  `%LOCALAPPDATA%\SurveyorCalibration\bitflow_board<N>_trigger.json`). It refuses to open
  the BitFlow card while ARAN's **FR Video Service** is running. Nothing else on any
  camera or card is changed.
- **Grab** (button or Space), **Countdown**, or **Take 50 photos**: one photo every 2 s
  whatever is in it (no board finding while collecting), stops at 50; move the board
  between photos. The calibration app sorts them out: unusable photos go to `NotUsed`, and
  a NOT PASSED that more photos can fix says what is missing and offers **Take 50 more**,
  which opens Capture on the same camera and folder (`--add-to`).
- **Magewell inputs:** read once a second; Capture shows what the camera itself sends
  (size, frame rate) and warns, asks and logs when the ACS size makes the card scale.
- **Folders:** the folder you pick is the *base*; each camera session gets its own
  subfolder `<Camera>_<Serial>_<YYYYMMDD_HHMMSS>` with the photos
  (`<Camera>_<date>_<time>_<ms>.jpg`, full size, never overwritten) and the log
  `CAPTURE_<date>.json`.
- The card's "No Signal" colour bars are never saved.
- **Open in calibration app** starts the calibration app on the session folder with the
  camera picked.

Capture is separate on purpose: it may import only `src.camera_db`, `src.van_scan`,
`src.version`, `src.styles`, `src.paths` and (for auto grab) `src.detector`,
`src.dot_detector`, `src.board`, `src.boards`, `src.coverage`; nothing outside
`src/capture` imports it (a test checks both). Removing `src/capture` leaves the
calibration app working. Spec, phases and results: `docs/capture/`.

## How a lens calibration is made (`src/pipeline.py`)

One path for Load Intrinsic and the CLI (`run_folder`):

1. `.raw` → PNG (Lucid frames); the board is auto-detected from the library.
2. Dots / corners found in every photo (in parallel). Chessboards
   (`src/detector.py find_chessboard`): OpenCV SB, then classic, then — for a board whose
   `board.yaml` says `finder: corner_markers` — the board's own finder
   (`src/marker_finder.py`, see Boards below). A detection with corners outside the
   picture counts as "not found".
3. Photos that can never be used (unreadable, no board, wrong size) are moved to
   `NotUsed\` with `NotUsed\why.txt` (nothing moves if more than half look unusable).
4. Calibrate; photos that fit much worse than the rest, or are blurry in a sharp set,
   are left out automatically and listed (`src/auto_clean.py`).
5. Grade (`src/grading.py`). **PASS** needs all of:
   - no hard stop (NaN, placeholder values, implausible focal length);
   - repeatability: the photos split into two random halves (6 times, median) agree
     within 0.6 mrad (6 mm at 10 m);
   - every 3×3 area has enough points and tilt (no red area);
   - not too blurry: dot edge blur ≤ 2.2 px at 1920 wide (4.4 px at 4K).

   RMS and the pixel error per square are shown but don't fail a calibration: on 68
   fleet cameras they did not predict real error.

## Boards (`Cal_board\`, copied to `C:\ProgramData\SurveyorCalibration\Cal_board`)

One folder per board with `board.yaml`. Installed copies are never overwritten.

- **Chessboard 12x8** (76.39 mm squares, measured with calipers) has a hollow square
  marker in each corner cell; the top-left square is white, so two markers sit where a
  white square would be. OpenCV's finders miss about half of the 4K GOX photos of it, so
  it has its **own finder** (`src/marker_finder.py`): find the markers, predict every
  corner, pull each onto the photo, keep it only if the grid is smooth. It returns 73
  corners — the 4 next to the markers are not true chessboard corners and are left out.
  On 71 GOX photos both could read, its corners matched OpenCV's to a median 0.001 px.
- Dot boards: `ClaudeRandomDot`, `ikea_road`, `Randot-003_…` (layout CSV + print PDF).

## Camera position (Old School) pass rules (`src/extrinsic/run.py`)

Per setup: ≥ 10 targets, leave-one-out miss ≤ 20 mm. Per camera: ≥ 3 setups, directions
agree within 1.5°, height within 0.20 m. Camera names come from where the camera points
(ROW 0°, FR +45°, FL −45°, Right +90°, Left −90°, RR +135°, RL −135°; closest wins).

## Files written

| Where | What |
|---|---|
| photo folder | `CAL_<serial>_<date>.yaml` + `.pdf`, `RUN_<date>.json` run log, `<photo>.dots.json` |
| `Calibration_<date>\` | fleet XML, PG RWC, OpenCV YAML/XML, ROS, Kalibr, COLMAP, Metashape, JSON, CSV |
| Old School setup folders | `<photo>.EOP` beside each photo (old program's naming) |
| `Extrinsic_<date>\` | EOP + overlay per setup, YAML, JSON, CSV, PDF, RWC, `_CHECK.html` |
| `Superseded\` | earlier results, moved there when you save again |

Anything that did not pass is still written, with a `NOT_PASSED_` prefix.
**Everything is saved next to the photos, and nowhere else.**

## Van database (`src/camera_db.py`)

MS SQL `<VAN>` on `<VAN>-SERVER` (then this PC), **Windows sign-in only** (no SQL login,
no password stored), read only, fixed SELECTs. ARAN writes a new configuration on every
save, so only the newest configuration (by `TimeChanged`) is used.

## Command line (no GUI)

```powershell
uv run python cli.py --list-boards
uv run python cli.py "F:\path\to\photos"                         # auto-detect, grade
uv run python cli.py "F:\path\to\photos" --serial 101324 --role ROW --save
uv run python cli.py --grade-all "F:\Camera Calibrations" --csv grades.csv --workers 8
```

The CLI leaves the photo folder alone unless `--move-unused` is given.

## Installer

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1        # from a clean commit
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Test  # uncommitted code, version "-modified"
```

PyInstaller builds both exes into one folder; Inno Setup 6 makes
`installer\Output\SurveyorCalibration_Setup_<version>.exe` (Start-menu entries for both).
The spec takes OpenSSL from Python's own folder and stops if any DLL would come from
Git for Windows (that crashed the built app). **The GOX needs BitFlow's `BFModule`**, which
is not on PyPI: install the cp312 wheel from the BitFlow release into the venv
(`uv pip install BFModule-2.0.3-cp312-cp312-win_amd64.whl`); it is not in Setup.exe yet
(licence to be read first).

## Tests

```powershell
uv run pytest
```

Self-contained: synthetic images, fake cameras, a fake BitFlow module, temp folders,
offscreen Qt. `tests/conftest.py` sends every app setting to a temp file, so tests never
touch the real Windows settings.

## Project layout

```
main.py, launch.bat        start the calibration app (start screen)
cli.py                     command line
Cal_board\                 board library (one folder per board, board.yaml)
control\Richmond\          tennis-ball GCP, site.yaml, seeds.yaml
installer\                 PyInstaller spec, Inno Setup script, build.ps1
docs\capture\              SurveyorCapture spec, phases, bench + field test results
references\                measurement records and history

src  pipeline.py           THE lens calibration path (run_folder)
  detector.py, marker_finder.py, dot_detector.py, auto_detect.py, image_filter.py
  calibrator.py, auto_clean.py, grading.py, coverage.py, not_used.py
  boards.py, board.py, board_builder.py
  camera_db.py             van database (read only), van_scan.py
  output_writer.py         CAL_ YAML + PDF;  export_formats.py  every other format
  load_saved.py            re-open a saved result;  previous_runs.py  "already calibrated?"
  superseded.py            move earlier results to Superseded\
  extrinsic\               Old School: oldschool, control, geo, targets, solve, run,
                           outputs, report, html_report, intrinsic_source, lens_check
  widgets\  start_screen.py, launcher.py (start screen + Home), app_window.py,
            camera_bar.py (top bar), one_camera_screen.py, setup_screen.py,
            report_screen.py, extrinsic_screen.py, boards_tab.py, zoom_view.py
  capture\  SurveyorCapture: window.py, grabber.py (camera thread), source.py
            (Magewell/DirectShow + fake), bitflow.py (GOX), autograb.py, cameras.py,
            saver.py, capture_log.py, nosignal.py, sizes.py, dshow_names.py, errors.py
```

## Notes

- `DetectionResult.charuco_corners` / `.charuco_ids` are historical names; they hold
  plain chessboard corners or dot centres.
- The 12x8 board's measured cell size (76.39 mm) is recorded in
  `references/BoardTrueSize.md`.
