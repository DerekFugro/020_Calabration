---
# Implementation Plan for Calibration

> **Status: all 5 phases complete.**  This is the original build plan, kept as
> a record.  Two things in it were changed during implementation:
>
> - Phase 2 task 2 specified ArUco marker detection + `interpolateCornersCharuco`.
>   As built, `src/detector.py` uses plain chessboard detection
>   (`cv2.findChessboardCornersSB`, fallback `cv2.findChessboardCorners`).
>   The ArUco module is not used.
> - Phase 2 task 1 specified non-square cells at 76.46 / 75.99 mm.  The board
>   was re-measured 2026-08-11 and is square at 76.2 mm.  Object points are
>   still built with separate X/Y spacing, so non-square boards still work.
>
> Delivered beyond this plan: `src/raw_loader.py` (Lucid `.raw` → PNG) and
> outlier-drop-and-recalibrate on the report screen.  See `README.md`.

## Phase 1 — Environment Setup
**Complexity:** Simple
**Goal:** Create the uv virtual environment, install all dependencies, and confirm the project runs with a blank window.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| Python | 3.12 | Runtime |
| uv | latest | Environment and package management |
| PySide6 | ≥6.11.1 | GUI framework |
| opencv-contrib-python | ≥4.13.0.92 | ChArUco detection + calibration |
| numpy | (opencv dep) | Numerical operations |
| fpdf2 | ≥2.8.7 | PDF generation |
| pyyaml | ≥6.0 | YAML file output |
| pytest | ≥9.0.3 | Test runner |

### Tasks
1. Create project folder structure (`src/`, `tests/`, `assets/`)
2. Create `requirements.txt` with all pinned dependencies
3. Create uv venv: `uv venv` then `uv pip install -r requirements.txt`
4. Verify all imports succeed with a `check_env.py` script that imports each library and prints its version
5. Create `main.py` with a minimal PySide6 app that opens a blank dark-mode window (confirms GUI stack works)
6. Confirm `uv run python main.py` launches the window on Windows 11

### Done when:
- [ ] `uv run python check_env.py` prints version for every dependency with no errors
- [ ] `uv run python main.py` opens a dark window with no errors
- [ ] `uv run pytest` runs with 0 tests collected and 0 errors

---

## Phase 2 — Core Calibration Engine
**Complexity:** Moderate
**Goal:** Implement the calibration logic as a pure-Python module (no GUI) — board detection, image acceptance/rejection, custom object point generation for non-square cells, and calibration computation.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| opencv-contrib-python | ≥4.13.0.92 | ChArUco detection, calibrateCameraCharuco |
| numpy | (dep) | Object point arrays |
| pytest | ≥9.0.3 | Unit tests for this module |

### Tasks
1. Create `src/board.py` — defines board parameters (12×8, DICT_5X5_50, cell_width_mm=76.46, cell_height_mm=75.99, marker_size_mm) and builds custom non-square 3D object points
2. Create `src/detector.py` — detects ArUco markers and interpolates ChArUco corners per image; returns corner count, corner positions, IDs
3. Create `src/image_filter.py` — accepts/rejects images based on: minimum corner count (≥6), blur score (Laplacian variance threshold), reprojection contribution; returns per-image status + reason
4. Create `src/calibrator.py` — collects accepted images, calls `cv2.calibrateCamera` with custom object points, returns camera matrix, distortion coefficients, RMS error, per-image rvecs/tvecs
5. Create `src/quality.py` — evaluates RMS against thresholds (Excellent / Acceptable / Needs Improvement), checks focus score, checks image count, returns verdict dict
6. Write pytest unit tests in `tests/test_calibrator.py` covering: object point shape, threshold logic, filename generation, YAML key presence

### Done when:
- [ ] `detector.py` correctly finds corners in `Cal_Images/1.png`
- [ ] `image_filter.py` correctly accepts/rejects synthetic test cases
- [ ] `calibrator.py` returns a camera matrix and RMS value from a set of test images
- [ ] `quality.py` returns correct verdict for RMS values 0.3, 0.7, 1.2
- [ ] All pytest tests pass

---

## Phase 3 — Output Files (YAML + PDF)
**Complexity:** Moderate
**Goal:** Generate the dated YAML calibration file and PDF report from a calibration result dict.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| pyyaml | ≥6.0 | YAML serialization |
| fpdf2 | ≥2.8.7 | PDF generation |

### Tasks
1. Create `src/output_writer.py`:
   - `write_yaml(result, serial, image_folder)` — writes `CAL_<Serial>_<YYYYMMDD_HHMMSS>.yaml` to image folder
   - `write_pdf(result, serial, image_folder)` — writes `CAL_<Serial>_<YYYYMMDD_HHMMSS>.pdf` to image folder
   - Both functions check for filename collisions and append a counter if needed
2. YAML must include: camera_matrix, dist_coeffs, rms, image_count_used, serial_number, calibration_datetime, board parameters
3. PDF must include: title, datetime, serial number, verdict badge (Excellent/Acceptable/Needs Improvement), RMS value, camera matrix table, distortion coefficients, per-image results table, recommended action if verdict is Needs Improvement
4. Write pytest tests: correct filename format, no overwrite on collision, all YAML keys present, PDF file is non-zero bytes

### Done when:
- [ ] YAML file written with correct filename and all required keys
- [ ] PDF file written, opens correctly, contains all required sections
- [ ] Filename collision test passes (second write appends `_2`)
- [ ] All pytest tests pass

---

## Phase 4 — GUI Layer
**Complexity:** Complex
**Goal:** Build the three-screen PySide6 GUI wired to the calibration engine. All GUI code must follow GUI_Coding_Standards.md exactly.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| PySide6 | ≥6.11.1 | All GUI components |

### Tasks
1. Create `src/styles.py` — dark mode palette constants and stylesheet strings
2. Create `src/widgets/main_window.py` (`MainWindow(QMainWindow)`) — hosts the three screens via a `QStackedWidget`
3. Create `src/widgets/setup_screen.py` (`SetupScreen(QWidget)`) — folder path + Browse button, camera serial number input, board parameters (pre-filled, editable), Run button (disabled until serial number entered), status bar
4. Create `src/widgets/image_review_screen.py` (`ImageReviewScreen(QWidget)`) — scrollable image list using factory + populate + clear pattern; each row is an `ImageRowWidget(QWidget)` showing filename, accepted/rejected badge, reason; summary counts; Proceed button
5. Create `src/widgets/report_screen.py` (`ReportScreen(QWidget)`) — verdict badge, RMS, camera matrix, distortion coefficients, image count, focus indicator, Save Report button
6. Wire all screens: Setup → (run detection) → Image Review → (run calibration) → Report → (save files)
7. Implement settings persistence using `QSettings` (last folder, serial number, board params)
8. Run button triggers detection in a `QThread` worker to keep GUI responsive; show progress in status bar
9. Human review step: show screenshots of all three screens to user and wait for "proceed" before continuing

### Done when:
- [ ] All three screens render in dark mode with no layout errors
- [ ] Browse button opens a folder dialog and populates the path field
- [ ] Run button is disabled with no serial number, enabled when serial number is entered
- [ ] Image list populates after detection with correct accepted/rejected badges
- [ ] Report screen shows correct values from a test calibration run
- [ ] Settings persist across app restarts
- [ ] All pytest tests pass
- [ ] User has reviewed screenshots and confirmed layout

---

## Phase 5 — Testing & Polish
**Complexity:** Simple
**Goal:** Complete test coverage, edge case handling, and final packaging.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| pytest | ≥9.0.3 | Full test suite |

### Tasks
1. Add edge case tests: empty folder, folder with no detectable images, fewer than 15 accepted images (should block calibration and show warning), unreadable image files
2. Add end-to-end integration test: run full pipeline on `Cal_Images/` folder and assert YAML + PDF are produced
3. Verify output files open correctly (YAML parses cleanly, PDF is valid)
4. Polish: consistent spacing, all error messages user-friendly, no raw exception tracebacks visible in GUI
5. Create `README.md` with: setup instructions (`uv venv`, `uv pip install -r requirements.txt`, `uv run python main.py`), usage steps, output file description
6. Final full test run — all tests must pass before delivery

### Done when:
- [ ] All edge cases handled gracefully (no crashes, user-friendly messages)
- [ ] End-to-end test produces valid YAML and PDF
- [ ] Full pytest suite passes with no failures
- [ ] README covers setup and usage
- [ ] User confirms app is ready

---

## Agent Routing Per Phase
| Phase | Recommended Model Tier |
|-------|----------------------|
| 1 — Environment Setup | Sonnet |
| 2 — Core Calibration Engine | Sonnet / Opus for complex calibration decisions |
| 3 — Output Files | Sonnet |
| 4 — GUI Layer | Sonnet + human review step after widgets are built |
| 5 — Testing & Polish | Sonnet |

---

## Total Estimate
| Phase | Complexity |
|-------|------------|
| 1 — Environment Setup | Simple |
| 2 — Core Calibration Engine | Moderate |
| 3 — Output Files | Moderate |
| 4 — GUI Layer | Complex |
| 5 — Testing & Polish | Simple |

---
