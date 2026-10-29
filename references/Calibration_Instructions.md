---
# Instructions for Calibration

> **As-built note — updated 2026-08-15.**  This spec was written before
> implementation.  Two things changed during the build and are corrected
> throughout this document:
>
> 1. **Detection is plain chessboard, not ChArUco.**  The printed board is a
>    ChArUco board, but `src/detector.py` uses `cv2.findChessboardCornersSB`
>    (falling back to `cv2.findChessboardCorners`) with CLAHE and a white
>    padding border.  The ArUco module is not used in the calibration path.
> 2. **The board cells are square, not rectangular.**  Re-measured
>    2026-08-11 at 3.000 in × 3.000 in (76.2 mm).  The earlier non-square
>    76.46 × 75.99 mm figures, derived from an overall 36.125 in × 23.9375 in
>    measurement, are superseded.  The board was re-measured with calipers on
>    2026-08-18 and its true cell pitch is **76.39 mm**; `src/board.py` still
>    uses 76.2 because a uniform scale error has no effect on the intrinsics.
>    Measurement of record: `BoardTrueSize.md` in this folder.
>
> Two features were also added beyond this MVP: Lucid `.raw` → PNG conversion
> (`src/raw_loader.py`) and outlier-drop-and-recalibrate on the report screen.
> See `README.md` for the current as-built description.

## ⭐ Project name:
Calibration

## ⭐ Purpose:
Takes images from a folder and produces a calibration file that other software can use to remove lens distortion and enable accurate measurement from images captured by that camera.

## ⭐ Problem it solves:
Enables precise pixel-to-real-world measurement within images collected from a specific camera/lens combination. Used by technical operators who need a reliable, repeatable calibration workflow before deploying a camera for measurement tasks.

## ⭐ MVP definition:
- Compute camera intrinsic calibration (camera matrix + distortion coefficients) from a folder of calibration board images
- Automatically accept or reject individual images based on detection quality (corner count, blur). *As built: reprojection error contribution is not used as an acceptance filter — instead the report screen lists worst-reprojecting images so the operator can drop them and recalibrate.*
- Require camera serial number entry before calibration can run
- Produce a calibration quality report (RMS reprojection error, image count used, focus check, pass/fail verdict)
- Save output as both a PDF report and a YAML calibration file, named with datetime, into the source image folder
- Remember last-used folder and settings between sessions

## ⭐ Success criteria:
- RMS reprojection error < 0.5 px = Excellent (green)
- RMS reprojection error 0.5–1.0 px = Acceptable (yellow)
- RMS reprojection error > 1.0 px = Needs improvement — report must say so and suggest more/better images (red)
- At least 15 images must be accepted for calibration to proceed
- Every run produces a dated PDF report and a dated YAML file saved alongside the source images

## ⭐ Explicit non-goals / out of scope:
- No image capture — the app only reads images already on disk
- No stereo or multi-camera calibration
- No real-time camera feed or live preview
- No image editing, cropping, or undistortion preview
- No user account system or cloud storage

## ⭐ Primary user / persona:
Technical operator — comfortable with file paths and calibration concepts, but wants a clean GUI rather than a command line.

## ⭐ Top user stories:

**Story 1 — Run a calibration**
As a user, I want to select a folder of calibration board images, enter the camera serial number, and run the calibration so that I get a calibration file I can use in downstream software.
*Acceptance criteria:* App accepts the folder, validates images, runs calibration, saves YAML + PDF to that folder, and shows the result on screen.

**Story 2 — Understand image quality**
As a user, I want to see which images were accepted or rejected and why so that I can recapture bad images.
*Acceptance criteria:* Per-image list shows filename, accepted/rejected status, and reason for rejection (e.g. "too blurry", "too few corners detected").

**Story 3 — Persistent settings**
As a user, I want the app to remember my last folder and settings so that I don't have to re-enter them every session.
*Acceptance criteria:* On relaunch, the last folder path and all settings are restored automatically.

**Story 4 — Dated, traceable output**
As a user, I want the output files to include the date/time and camera serial number in their names so that I can trace which calibration belongs to which camera and session.
*Acceptance criteria:* Output filenames follow the pattern `CAL_<SerialNumber>_<YYYYMMDD_HHMMSS>.yaml` and `CAL_<SerialNumber>_<YYYYMMDD_HHMMSS>.pdf`, saved in the source image folder.

**Story 5 — Know when calibration needs more images**
As a user, I want the report to tell me if my calibration is poor and what to do about it so that I don't use a bad calibration in production.
*Acceptance criteria:* If RMS > 1.0 px or fewer than 15 images were accepted, the report displays a clear warning with a recommended action.

## ⭐ App type:
GUI Desktop (Windows 11)

## ⭐ GUI layout approach:
Pure code (PySide6, all layout written in Python — no Qt Designer .ui files).

**Dynamic widgets required:**
- Image list rows — one row per image showing filename, thumbnail (optional), accepted/rejected badge, and rejection reason. Generated at runtime after folder is loaded and detection is complete. Must use the factory + populate + clear pattern.

## ⭐ Key screens / endpoints / commands:

**Screen 1 — Main / Folder Setup**
- Folder path input with Browse button (remembers last path)
- Camera serial number input (required — Run button disabled until filled)
- Board parameters section: squares X/Y, cell width mm, cell height mm, marker size mm (pre-filled with known board defaults, editable)
- Run Calibration button
- Status bar showing current state

**Screen 2 — Image Review (shown after detection pass)**
- Scrollable list of all images with per-row status (accepted / rejected + reason)
- Summary counts: X accepted, Y rejected
- Proceed to Calibration button (disabled if < 15 accepted)

**Screen 3 — Report View (shown after calibration)**
- Overall result badge (Excellent / Acceptable / Needs Improvement)
- RMS reprojection error
- Camera matrix (fx, fy, cx, cy)
- Distortion coefficients
- Images used / total
- Focus quality indicator
- Save Report button (saves PDF + YAML, confirms file paths)

## ⭐ Roles / permissions:
None.

## ⭐ Data to store + key rules:
- **Session settings** (persisted via QSettings or a JSON config file): last image folder path, camera serial number, board parameters. Never store calibration results — those go to files.
- **YAML calibration file**: camera matrix, distortion coefficients, RMS error, image count, camera serial number, datetime, board parameters. Saved to image folder as `CAL_<SerialNumber>_<YYYYMMDD_HHMMSS>.yaml`.
- **PDF report**: human-readable summary of the calibration run including all parameters, per-image results table, pass/fail verdict. Saved to image folder as `CAL_<SerialNumber>_<YYYYMMDD_HHMMSS>.pdf`.
- Never overwrite an existing output file — if a name collision occurs, append a counter suffix.

## ⭐ Integrations:
None.

## ⭐ Target OS and hardware:
Windows 11 PC.

## ⭐ Version control and environment:
- No Git (fresh project, not requested)
- Environment: **uv** venv
- All dependencies must be installable via `uv pip install -r requirements.txt` with no manual steps
- Project must be fully runnable after environment setup with a single `uv run python main.py` (or equivalent)

## ⭐ Preferred tech stack:
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12 | Runtime |
| PySide6 | ≥6.11.1 | GUI framework — Qt6 for Python, dark mode, Windows 11 native |
| opencv-contrib-python | ≥4.13.0.92 | Chessboard corner detection + camera calibration (contrib retained for the unused ArUco module) |
| numpy | (opencv dependency) | Numerical array operations |
| fpdf2 | ≥2.8.7 | Pure-Python PDF report generation |
| pyyaml | ≥6.0 | YAML calibration file output |
| pytest | ≥9.0.3 | Automated testing |
| uv | latest | Environment and package management |

## ⭐ Testing approach:
Automated tests with **pytest**. Agent chooses test structure. At minimum cover:
- Image acceptance/rejection logic (unit tests with synthetic inputs)
- Output filename generation (correct serial number + datetime format)
- YAML file structure validation (all required keys present, correct types)
- Calibration result thresholds (correct pass/warn/fail verdict for given RMS values)

## ⭐ Preferences and tradeoffs:
No specific preferences stated. Default to: clean architecture, simple code, easy to maintain, minimize dependencies.

## ⭐ Reference material:
- `Cal_Images/1.png` — reference image of the board (3840×2160 px)
- `README.md` — **the current as-built description; read this first**
- `Cal_board/CalibrationBoard.txt` — **SUPERSEDED.** Records the old non-square derivation. Kept for history only.
- `calibration_agent_prompt.md` — **SUPERSEDED.** Specified a CLI tool (`calibrate.py`, argparse) using `cv2.aruco.calibrateCameraCharuco`. Never built; the GUI app replaced it. Kept for history only.

**Board parameters as built (`src/board.py`):**
- Board: 12 columns × 8 rows of squares → 11 × 7 interior corners
- Cell width (X): 3.000" × 25.4 = **76.2 mm**
- Cell height (Y): 3.000" × 25.4 = **76.2 mm**
- Cells **are square** (re-measured 2026-08-11). Object points are still built manually with separate X and Y spacing, so a non-square board can be entered on the Setup screen if needed.
  - Empirical check: square cells give fx/fy = 0.9998; the old non-square values gave 0.994.
- ArUco dictionary: DICT_5X5_50 — printed on the board, **not used for detection**
- Marker size: 60.0 mm default; written to the YAML for reference, not used by detection
- Detection: `cv2.findChessboardCornersSB` → fallback `cv2.findChessboardCorners`, with CLAHE and a 60 px white padding border, then `cv2.cornerSubPix`

**Filter and verdict thresholds as built:**
- Minimum corners: 6 (`MIN_CORNERS`, `src/image_filter.py`) — in practice detection is all-or-nothing
- Minimum blur score: **20.0** (`MIN_BLUR_SCORE`; user-adjustable on the Setup screen, 0 disables the check)
- Minimum accepted images to proceed: 15 (`MIN_IMAGES`, `src/quality.py`)
- Hard floor inside the calibrator: 4 images (`_MIN_IMAGES_FOR_CALIBRATION`, `src/calibrator.py`)

---

## Rules for the coding agent

- Always use dark mode (see color palette below)
- Enforce GUI_Coding_Standards (GUI.txt in ForClaude/ folder):
  - Every QWidget subclass must use the 5-method `__init__` pattern: `_create_widgets`, `_create_layouts`, `_connect_signals`, `_apply_styles`, `_load_initial_state`
  - Every widget must have a named instance variable
  - No business logic in `_create_*` methods
  - Dynamic image list rows use factory + populate + clear pattern
  - Slot methods named `_on_<widget>_<event>`
- Ask if anything is unclear BEFORE starting — never make assumptions silently
- Never delete or overwrite existing files without explicit user confirmation
- Write an implementation plan grouped into phases before writing any code
- List all required software and versions per phase
- Between each phase: run the full test suite, report results to the user, and wait for "proceed" before continuing — do not advance if any tests fail
- Each phase must leave the codebase in a runnable, working state
- If any software cannot be installed or a version conflict is found, stop immediately and report before continuing
- If unsure whether a library is current or deprecated, search the web to verify before recommending it
- Do not use AI-generated placeholder data in production logic
- Keep all secrets and config in a settings file — never hard-code paths or serial numbers

**Dark mode palette:**
```python
DARK_BG        = "#2c3e50"
DARK_BG_ALT    = "#34495e"
TEXT_PRIMARY   = "#ecf0f1"
TEXT_SECONDARY = "#bdc3c7"
ACCENT_BLUE    = "#3498db"
ACCENT_GREEN   = "#27ae60"
ACCENT_RED     = "#e74c3c"
ACCENT_ORANGE  = "#f39c12"
BORDER_COLOR   = "#1a252f"
```

## Agent Routing Hints
| Task | Recommended Model Tier |
|------|----------------------|
| Architecture decisions, spec review | Opus |
| Feature implementation, calibration engine | Sonnet |
| GUI layout implementation | Sonnet + human review before proceeding |
| Test writing | Sonnet |
| Renaming, formatting, simple edits | Haiku |

## First tasks when coding begins

1. Read `ForClaude/GUI.txt` — GUI coding standards (mandatory before any widget code)
2. Read `calibration_agent_prompt.md` — calibration engine technical spec
3. List all required software, libraries, and extensions with versions
4. Search the web to verify current stable versions and compatibility
5. Create the uv virtual environment and install all dependencies
6. Confirm setup is complete with a version summary, then wait for "proceed" before writing any application code
---
