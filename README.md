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
| **Load Intrinsic** (one camera at a time) | Pick the photo folder, camera and serial (both blank at start, typed every time), Run. If the folder was calibrated before, you can **Open results** or **Reprocess**. The report shows the PASS / NOT PASSED banner, why, what to shoot next, the 3×3 coverage grid, photos left out, and the numbers. **Save** writes `CAL_<serial>_<date>.yaml/.pdf` next to the photos, every format into `Calibration_<date>\` (fleet cameras), and publishes a PASS to the calibration store. |
| **Load Extrinsic** (one camera at a time) | Pick one camera's Old School folder and its lens (this session's Load Intrinsic result or a lens file). Old School photos → camera angles, height and lever arms. Needs a passed intrinsic per camera. Finds and labels the wall discs and tennis balls itself (old EOP files are never read; the app writes the EOPs), drops wrong targets, solves and combines the setups. Control is always the tennis-ball GCP in `control/Richmond` (never the revised GCP). *Save all formats* writes EOP + overlay per setup, YAML, JSON, CSV, PDF, PGExteriorCalibration RWC (angles unverified) and a one-page **`_CHECK.html`** for the office into `Extrinsic_<date>\`. |
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

Anything that did not pass is still written, with a `NOT_PASSED_` prefix, and is
never published.

## The calibration store

**Rule owner:** `H:\001_Mahine_App_Specs\MasterLeverarms and information.md` §11
and `H:\001_Mahine_App_Specs\Calibrations\README.md`.  Every calibration on
this project lives in one place; apps read from there, never from a hard-coded
value or an app-local copy.

The store is **one folder per calibration event**, and one file per camera
inside it:

```
Calibrations\
  YYYYMMDD[_HHMMSS]_<Type>\     <- effective datetime + type
    <ROLE>_<SERIAL>.yaml        <- the calibration itself
```

**The type name says which camera** (master doc v1.4): intrinsics are split
into `PaveIntrinsic` and `ROWIntrinsic`, so a save produces e.g.

```
20260815_202357_PaveIntrinsic\PAVE_234500499.yaml
```

Type names are owner-defined and used verbatim, mixed capitalisation and all
(`PaveIntrinsic` vs `ROWIntrinsic`).  They live in `INTRINSIC_TYPES` in
`src/calibration_store.py`.  **The app never invents one** — a role with no
type on the master list cannot be published, so a BENCH run stays local and
says so.  To publish a new camera, the owners add its type to
`Calibrations\README.md` first.

**Save** does two things: it writes the working `CAL_*.yaml` + `.pdf` pair into
the image folder, then — **if the calibration passed** — copies the YAML into
the store.  The folder stamp is the
calibration's **effective datetime** — the same datetime as the local files, so
a store entry always traces back to the run that produced it.

### Reading a calibration back

`find_latest(role, serial, at)` implements the store's selection rule: the
newest folder of that camera's type whose stamp is **≤ the collection's start
time**, and which actually holds the file.

```python
from datetime import datetime
from src.calibration_store import find_latest

yaml_path = find_latest("PAVE", "234500499", at=datetime(2026, 8, 20, 14, 0))
```

Because the type is per camera, a Pave re-shoot can never shadow ROW's
calibration — they are different types and are selected independently.  The
file check on top of that means a folder that exists but is empty, or holds a
different serial, is skipped rather than silently returned.

Date-only folders take effect at midnight.  Folders VOIDed by the owners
(`.VOID` anywhere in the name) never parse, so they can never be selected.
That check is explicit: a `.VOID` suffix lands after the type, where it would
not disqualify the folder on its own.

### Only a PASS is published

The store is append-only, so `check_publishable` refuses anything that did not
pass, and says why. It checks the **grade recorded in the file** (so a wrong
flag can't wave a bad run through) and the run's own pass/fail. A file with no
grade (made before 2026-10-31) is refused: process the photos again. A refused
calibration is not lost: the local `CAL_*` files are still written.

### Rules the app obeys (`src/calibration_store.py`)

- **Append-only.**  If the target file already exists, the publish is refused —
  the app never overwrites or deletes anything in the store.  A wrong folder is
  `.VOID`ed by the owners, not by this app; `.VOID` folders drop out of
  selection automatically.
- **Each camera gets its own folder**, named by its type, even when two
  cameras are saved seconds apart.
- **Never invents a type name.**  An undefined role fails the publish with a
  message naming the known roles; the local files are still written.
- **The store never blocks a save.**  If the drive is offline or the folder is
  missing, the local files are still written and the app warns that the
  calibration was not published.
- **Bad role or serial is refused before it becomes a permanent filename** —
  the store is append-only, so a typo like the historical `CAL_2345000499`
  would be there forever.
- Point the app at a different store with the `CALIBRATION_STORE` environment
  variable (used by the tests; leave it unset in the field).

## Command line (no GUI, never publishes)

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
  calibration_store.py     publish to / read from the shared store
  previous_runs.py         "already calibrated?" check
  photo_folders.py, van_scan.py, styles.py
  extrinsic\               Old School: oldschool, control, geo, targets, solve, run,
                           outputs, report (PDF), html_report (_CHECK.html), intrinsic_source
  widgets    app_window.py          tabs, van bar, the one status bar
    one_camera_screen.py   One camera: setup -> report, save + publish
    setup_screen.py, report_screen.py
    extrinsic_screen.py (one camera), boards_tab.py, zoom_view.py
```

## Notes

- `DetectionResult.charuco_corners` / `.charuco_ids` are historical names; they
  hold plain chessboard corners or dot centres.
- The chessboard board's measured cell size (76.39 mm) is recorded in
  `references/BoardTrueSize.md`.
