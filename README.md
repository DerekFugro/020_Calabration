# Sidewalk Profiler — Camera Calibration Tool

Calibrates a USB or machine-vision camera against any board in the
**board library** (`Cal_board/`): the **12 × 8 square chessboard** (11 × 7
interior corners) or a **random-dot board** (Randot-003, ikea_road).  The
board can be picked from a list or **auto-detected** from the images.
Outputs a YAML intrinsics file and a PDF report that can be imported directly
into the profiler pipeline.

## Board library and auto-detect (added 2026-10-29)

- Each board has its own folder in `Cal_board/` with a `board.yaml`
  (see `src/boards.py` for the format).  Add a folder = add a board; no code
  change.  Current boards: `Chessboard_12x8`, `Randot-003_roadware_140_60_003`,
  `ikea_road`.
- Setup screen: **Board** list.  "Auto-detect" (default) tries every board on
  8 sample images and uses the one found in the most images.  One board per
  calibration run.  The squares / cell-size boxes are used only for the
  chessboard.
- Dot boards (`src/dot_detector.py`): blob centres are matched to the layout
  CSV, then the calibrator re-matches on undistorted points and calibrates a
  second time.  The YAML gets a `board: type: random_dot` block and
  `detection_method: dot_centroid`.
- Command line (no GUI, never publishes to the store):

  ```powershell
  uv run python cli.py --list-boards
  uv run python cli.py "F:\path\to\images"                     # auto-detect
  uv run python cli.py "F:\path\to\images" --board ikea_road
  uv run python cli.py "F:\path\to\images" --serial 262503744 --role PAVE --save
  ```
- Check run 2026-10-29: Rear 262503744 Randot-003 images (42) gave fx 2065.22,
  fy 2066.68, RMS 1.067 px, the same as the filed 20261008_PaveIntrinsic.
- Backup of the code before this change: `_backup_20261029_before_boards/`.

## Grade: pass, or what to shoot next (added 2026-10-31)

Every calibration is graded (`src/grading.py`). PASS needs all of:

- no hard stop (NaN, placeholder values such as an exact image-centre principal point with zero distortion, implausible focal length);
- repeatability: first and second half of the photos calibrated separately agree within 1 mrad (10 mm at 10 m) after removing a common camera rotation;
- every 3 x 3 area has enough points and board tilt;
- 15 or more usable photos and RMS under 2 px.

Otherwise the report says NOT GOOD ENOUGH and lists, per area, how many more photos to take and how, plus the worst photos to remove. A failed grade still saves the local files but is not published to the store. Command line: `python cli.py <folder>` prints the grade; `python cli.py --grade-all <root> --csv grades.csv --workers 8` grades every image folder under a root. Dot boards no longer use the blur filter (it rejected sharp dot photos).

## Image coverage grid (added 2026-10-31)

The report screen and the PDF show a 3 × 3 grid over the camera image.  Each
area shows how many board points landed there, the reprojection error of those
points, and how much the board angle varied there.  Green / yellow / red, with
the area's colour set by its worst measure, plus a line of advice for every
non-green area.  Limits are at the top of `src/coverage.py`.

> **Detection note** — the printed board is a ChArUco board (DICT\_5X5\_50
> markers in the white squares), but this app does **not** use the ArUco
> module.  `src/detector.py` treats the board as a plain chessboard and calls
> `cv2.findChessboardCornersSB`, falling back to `cv2.findChessboardCorners`.
> The ArUco markers are ignored.  `BoardConfig.get_charuco_board()` still
> exists but nothing in the calibration path calls it.

---

## Requirements

| Dependency | Version |
|---|---|
| Python | 3.12 |
| uv | 0.11+ |
| PySide6 | 6.11+ |
| opencv-contrib-python | 4.13+ |
| fpdf2 | 2.8+ |
| pyyaml | 6.0+ |
| unicodedata2 | 17.0+ |

> **Windows 11 note** — if AWS CLI is also installed, a `sitecustomize.py`
> shim is included in `.venv` to prevent the AWS Python 3.13 runtime from
> shadowing the project's Python 3.12 DLLs.

---

## Setup

```powershell
# 1. Clone / open the project folder
cd e:\SidewalkProfiler\Calabration

# 2. Create the virtual environment
uv venv

# 3. Install all dependencies
uv pip install -r requirements.txt
uv pip install unicodedata2   # PDF font fix on Windows

# 4. Verify the environment
uv run python check_env.py
```

All seven checks should print **OK**.

---

## Board specifications

Defaults live in `src/board.py`.

| Parameter | Value |
|---|---|
| Layout | 12 squares wide × 8 squares tall (11 × 7 interior corners) |
| Cell width | **76.39 mm** — measured with calipers 2026-08-18 |
| Cell height | **76.39 mm** — cells are square |
| Where that came from | 152.78 mm across two cells ÷ 2. The print ran 0.25% over its nominal 3.000 in (= 3.0075 in). The earlier 76.2 was the assumed nominal and was never measured. See `references/BoardTrueSize.md`. |
| Marker size | not used — removed from the app's inputs and outputs 2026-08-15; `BoardConfig` keeps a default for the board-printing helper only |
| ArUco dictionary | DICT\_5X5\_50 is printed on the board but never read; detection is plain chessboard |

> **Board measurement:** `references/BoardTrueSize.md` is the measurement of
> record — how to measure the board and what it actually reads.  Note that
> moving 76.2 → 76.39 changes **no** calibration output: only the width/height
> ratio reaches the intrinsics.  The app uses the measured value because it
> should state what was measured, not what was assumed.

### Why square cells

Earlier versions derived the cell size from an overall board measurement of
36.125 in × 23.9375 in, giving **non-square** cells of 76.46 mm × 75.99 mm.
The board was re-measured on **2026-08-11** and the cells are square at
3.000 in.  Calibrating with square cells gives fx/fy = 0.9998, versus 0.994
with the old non-square values — the square values are correct.

Calibration still builds its 3D object points manually (`BoardConfig.
get_all_object_points()`) with separate X and Y spacing, so a non-square
board can still be entered on the Setup screen if you ever use one.

`references/CalibrationBoard.txt` records the superseded non-square figures
and is kept for history only.

---

## GUI — step-by-step

```powershell
uv run python main.py
```

1. **Setup screen**
   - Click **Browse** and select the folder containing your calibration images
     (JPG or PNG, any mix of sizes). Lucid **.raw** frames are also accepted:
     they are auto-converted to PNG in place before detection (geometry/format
     from the `.raw.json` / `.json` sidecar; defaults TDR054S 2880×1860 RGB8 —
     see `src/raw_loader.py`).
   - Pick the **Role** — which camera this is on the rig (PAVE, ROW, BENCH, or
     type a new one).  The role plus the serial name the file in the shared
     calibration store, so it is required before **Run** enables.
   - Enter the **Camera Serial Number** printed on the camera body.
     The app remembers the serial used with each role: pick PAVE and the PAVE
     serial fills itself in.  You only retype it when the camera changes.
   - Adjust **Board Parameters** if your printed board differs from the
     defaults.  Squares and cell size only — marker size is not asked for,
     because chessboard detection ignores the markers.
   - Adjust **Min Blur Score** if needed (default 20.0; set 0 to disable the
     blur check entirely).
   - Click **Run Calibration**.

2. **Image Review screen**
   - Each image is shown with its acceptance status, detected corner count,
     and blur score.
   - Images are rejected automatically if they have fewer than 6 detected
     corners (`MIN_CORNERS`) or a blur score below 20.0 (`MIN_BLUR_SCORE`,
     both in `src/image_filter.py`).  The blur threshold is also adjustable
     on the Setup screen.
   - The **Proceed** button is enabled once ≥ 15 images are accepted
     (`MIN_IMAGES` in `src/quality.py`).  Note that `src/calibrator.py`
     has a separate hard floor of 4 images below which it raises.

3. **Report screen**
   - Displays the calibration verdict, RMS reprojection error, camera matrix,
     and distortion coefficients.
   - Lists the worst-reprojecting images.  You can drop the outliers and
     recalibrate without leaving the screen.
   - Click **Save** to write the output files next to the images **and**
     publish the YAML to the shared calibration store (see below).

---

## Output files

Both working files land in the image folder and share the same timestamp stem:

```
CAL_<SerialNumber>_<YYYYMMDD_HHMMSS>.yaml
CAL_<SerialNumber>_<YYYYMMDD_HHMMSS>.pdf
```

### YAML keys

```yaml
serial_number:          "SN-001"
calibration_datetime:   "2026-06-09T14:32:00"
rms_reprojection_error: 0.42
image_count_used:       22
verdict:                "Excellent"
camera_matrix:
  rows: 3
  cols: 3
  data: [fx, 0, cx, 0, fy, cy, 0, 0, 1]
dist_coeffs:
  rows: 1
  cols: 5
  data: [k1, k2, p1, p2, k3]
image_resolution:
  width:  3840
  height: 2160
board:
  squares_x:     12
  squares_y:     8
  cell_width_mm:  76.2
  cell_height_mm: 76.2
detection_method: chessboard
```

Plus `camera_role` — the role picked on the Setup screen.

> **Removed 2026-08-15: `marker_size_mm` and `aruco_dict`.**  Detection is plain
> chessboard, so the ArUco dictionary named a code path that never runs, and the
> marker size was never measured — a default value that read like data.  They
> are gone from the YAML, the PDF report, the report screen, and the Setup
> screen input.  `BoardConfig` keeps its defaults for the board-printing helper.
>
> Cell size stays: `76.2` vs the superseded `76.465 × 76.002` is how you spot a
> calibration shot against the old board.

> Board values in the YAML are whatever was entered on the Setup screen for
> that run — older files on disk may show the superseded non-square values.

---

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

### Only a passing calibration is published

The store is append-only: a bad calibration published once is there forever,
and sooner or later something processes against it.  So `publish()` refuses
anything that did not pass, and says why:

| Run | Verdict | Published? |
|---|---|---|
| RMS < 0.5, enough images | Excellent | yes |
| RMS 0.5–1.0, enough images | Acceptable | yes |
| RMS > 1.0 | Needs Improvement | **no** |
| Good RMS, fewer than `MIN_IMAGES` accepted | Excellent / Acceptable | **no** |

Both checks run (`check_publishable`): the verdict recorded *in the file*, so a
caller cannot wave a bad run through with the wrong flag, and the run's own
`QualityReport.pass_verdict`, which catches "good RMS but too few images" — a
case the verdict alone hides.

A refused calibration is not lost: the local `CAL_*.yaml` and `.pdf` are still
written, and the app tells you what to fix.  Drop the outliers on the report
screen and recalibrate, then save again.

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

The PDF report stays local — the store holds the calibration file itself.

---

## Running the tests

```powershell
uv run pytest tests/ -v
```

All tests are self-contained and require no external images.
The integration test suite renders synthetic plain-chessboard images at
runtime, at varied rotations and scales.

---

## Project structure

```
main.py                     Application entry point
launch.bat                  Double-click launcher (uv run python main.py)
requirements.txt
check_env.py                Dependency smoke-test
diagnose.py                 Single-image detection diagnostic + debug overlay
conftest.py                 pytest sys.path fix

src/
  board.py                  BoardConfig dataclass + object-point generator
  detector.py               Chessboard corner detection (findChessboardCornersSB
                            + CLAHE + white padding + cornerSubPix)
  image_filter.py           Accept/reject logic (min corners, blur score)
  calibrator.py             cv2.calibrateCamera wrapper + per-image error
  quality.py                RMS verdict (Excellent / Acceptable / Needs Improvement)
  output_writer.py          YAML + PDF writer
  calibration_store.py      Publish a calibration to H:\001_Mahine_App_Specs\Calibrations
  raw_loader.py             Lucid .raw → PNG (RGB8 / BayerRG24 / Mono8)
  utils.py                  Shared utilities (find_images)
  workers.py                QThread workers (DetectionWorker, CalibrationWorker)
  styles.py                 Dark-mode QPalette + Qt stylesheet
  widgets/
    main_window.py          Root QMainWindow — screen orchestration
    setup_screen.py         Screen 1 — folder, role + serial, board params
    image_review_screen.py  Screen 2 — per-image results list
    report_screen.py        Screen 3 — verdict + camera params + save
    image_row_widget.py     Factory row widget for the review list

tests/
  test_calibrator.py        Unit tests: board points, filter, quality, calibration
  test_output_writer.py     Unit tests: filename format, YAML keys, PDF validity
  test_edge_cases.py        Boundary tests: empty folder, corrupt files, rejections
  test_integration.py       End-to-end: synthetic images → YAML + PDF
  test_raw_loader.py        .raw decode + folder conversion
```

---

## Naming caveat

`DetectionResult.charuco_corners` and `.charuco_ids` are historical names
from when the app used the ArUco module.  They now hold plain chessboard
corners and sequential row-major IDs.  The names are kept because renaming
them touches `detector.py`, `calibrator.py`, and four test files.

## Tabs (2026-11)

- **Load Intrinsic > Whole van**: pick a van's Intrinsic folder; every camera folder is found
  (camera from the folder name, serial from the filed `<VAN>_<Camera>_<Serial>_intrinsic_cal.xml`),
  graded in one go, and compared to the filed calibration. *Export all formats* writes fleet XML,
  PGInteriorCalibration RWC, OpenCV YAML/XML, ROS camera_info, Kalibr, COLMAP, Metashape XML, JSON
  and CSV into `Calibration_<date>` next to the photos. Files from a calibration that did not pass
  get a `NOT_PASSED_` prefix.
- **Load Intrinsic > One camera**: the original setup / review / report flow.
- **Capture Intrinsic, Load Extrinsic, Capture Extrinsic**: placeholders, next to build.
- CLI: `python cli.py FOLDER --van ARAN65 --role ForwardRight --serial 101324 --export OUTDIR`
- **NotUsed folder**: with *Move unusable photos* on (Advanced, default on), photos that can never be
  used (unreadable, no board, wrong image size) are moved to `NotUsed\` next to the others and
  listed in `NotUsed\why.txt`. High-error or blurry photos are only left out, never moved. Nothing
  moves if more than half the set looks unusable, or when using fewer than all photos. CLI:
  `--move-unused` (off by default).
- **Boards tab**: add a board to `Cal_board`. Dots: pick the layout CSV (metres, Randot format); it is
  checked, copied into `Cal_board\<name>\`, and a true-scale PDF is made with red A-B / C-D marks.
  Print at 100%, measure A-B and C-D centre to centre, *Save measurement*: `scale_x` / `scale_y`
  go into board.yaml and are applied when the board loads. Chessboard: squares and cell size, then
  measure full width and height. *Test* runs auto-detect on a few photos. Older dot boards: *Make PDF
  with A-B / C-D marks* writes `<name>_measure.pdf` without touching the original PDF.
