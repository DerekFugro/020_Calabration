# Camera Calibration Software — Coding Agent Prompt

> # ⚠️ SUPERSEDED — DO NOT BUILD FROM THIS FILE
>
> Marked superseded 2026-08-15.  Kept for history only.
>
> This document specified a **command-line tool** (`calibrate.py` with
> argparse) built on `cv2.aruco.calibrateCameraCharuco`.  That tool was never
> built.  It was replaced by the PySide6 GUI application described in
> `Calibration_Instructions.md` and `README.md`.
>
> Specifically, the following in this file are **wrong** for the shipped app:
>
> | This file says | Reality |
> |---|---|
> | CLI `calibrate.py` with argparse | Three-screen PySide6 GUI, `main.py` |
> | ArUco marker detection + `interpolateCornersCharuco` | Plain chessboard: `findChessboardCornersSB` |
> | `cv2.aruco.calibrateCameraCharuco` | `cv2.calibrateCamera` with manual object points |
> | Non-square cells 76.46 × 75.99 mm | Square cells 76.2 × 76.2 mm (re-measured 2026-08-11) |
> | Output `calibration_output.yaml` | `CAL_<Serial>_<YYYYMMDD_HHMMSS>.yaml` + matching `.pdf` |
>
> **For current behaviour, read `README.md`.**

## Context

Build a Python camera calibration tool for a **ChArUco calibration board** — a checkerboard with ArUco fiducial markers embedded in the corner squares. A reference image of the board is at `Cal_Images/1.png` (3840×2160 px). The `Cal_board/` directory is reserved for any generated board assets.

The board is a **12×8 square ChArUco board** (12 columns × 8 rows of squares) with ArUco markers from the **DICT_5X5_50** dictionary placed in the white corner squares. Inspect the reference image with OpenCV's ArUco detector to confirm the dictionary before hardcoding.

### Known Physical Dimensions (from `Cal_board/CalibrationBoard.txt`)

The board was physically measured at **36.125" × 23.9375"**, giving **non-square cells**:

| | Inches | Millimeters |
|---|---|---|
| Cell width (X) | 36.125 / 12 = 3.0104" | **76.46 mm** |
| Cell height (Y) | 23.9375 / 8 = 2.9922" | **75.99 mm** |

Because the cells are rectangular (not square), **standard ChArUco calibration — which assumes a single `squareLength` — will introduce a small systematic error**. The agent must handle this by constructing object points manually:

- Build the 3D object point grid using `cell_width_mm` for X spacing and `cell_height_mm` for Y spacing instead of a single square size.
- Pass these custom object points directly to `cv2.calibrateCamera` rather than relying on `calibrateCameraCharuco`'s internal point generation.
- The ArUco marker size is proportional; use `marker_size_mm` as a separate runtime argument (measure the printed marker side length). A reasonable starting estimate is ~80% of the shorter cell dimension (~60 mm), but the user should measure and supply the exact value.

---

## Goal

Produce a Python script (`calibrate.py`) that:

1. Accepts a folder of calibration images (JPG/PNG) captured from a single camera aimed at the ChArUco board.
2. Detects the ChArUco corners and IDs in each image.
3. Runs OpenCV's camera calibration to compute intrinsic parameters.
4. Saves the results to a YAML file (`calibration_output.yaml`).

---

## Functional Requirements

### 1. CLI Interface

Use `argparse`. Required arguments:

| Flag | Description |
|------|-------------|
| `--images` | Path to folder containing calibration images |
| `--marker_size` | Physical side length of the ArUco marker in mm (float) |
| `--output` | Output YAML path (default: `calibration_output.yaml`) |

Optional arguments:

| Flag | Description |
|------|-------------|
| `--cell_width_mm` | Cell width in X direction in mm (default: **76.46**) |
| `--cell_height_mm` | Cell height in Y direction in mm (default: **75.99**) |
| `--squares_x` | Number of squares in X (default: **12**) |
| `--squares_y` | Number of squares in Y (default: **8**) |
| `--dict` | ArUco dictionary name (default: `DICT_5X5_50`) |
| `--preview` | If set, display annotated detection images in a window |
| `--min_detections` | Minimum corners required to use an image (default: 6) |

### 2. Board Detection

- Create the `cv2.aruco.CharucoBoard` with the given parameters.
- For each image:
  - Detect ArUco markers with `cv2.aruco.detectMarkers`.
  - Refine and interpolate ChArUco corners with `cv2.aruco.interpolateCornersCharuco`.
  - Skip images where fewer than `--min_detections` corners are found.
  - Log (to stdout) how many corners were found per image and whether the image was accepted or skipped.

### 3. Calibration

- Collect all accepted `charucoCorners` and `charucoIds` arrays.
- Call `cv2.aruco.calibrateCameraCharuco` to get:
  - `camera_matrix` (3×3)
  - `dist_coeffs` (1×5 or 1×8 depending on flags)
  - `rvecs`, `tvecs` per image
  - RMS reprojection error

### 4. Output

Save `calibration_output.yaml` with this structure (use `cv2.FileStorage` or PyYAML):

```yaml
calibration_date: "2026-06-09"
image_count_used: 14
rms_reprojection_error: 0.412
camera_matrix:
  rows: 3
  cols: 3
  data: [fx, 0, cx, 0, fy, cy, 0, 0, 1]
dist_coeffs:
  rows: 1
  cols: 5
  data: [k1, k2, p1, p2, k3]
image_resolution:
  width: 3840
  height: 2160
board:
  squares_x: 12
  squares_y: 8
  cell_width_mm: 76.46
  cell_height_mm: 75.99
  marker_size_mm: <user_value>
  aruco_dict: DICT_5X5_50
```

Print a summary to stdout after saving:
```
=== Calibration Result ===
Images used:        14 / 20
RMS reprojection:   0.412 px
Focal length:       fx=3521.4  fy=3519.8
Principal point:    cx=1923.1  cy=1081.6
Distortion:         [k1 k2 p1 p2 k3]
Output saved to:    calibration_output.yaml
```

### 5. Optional Preview (`--preview`)

When enabled, for each accepted image show a window with:
- The detected ChArUco corners drawn (use `cv2.aruco.drawDetectedCornersCharuco`).
- Image filename as a title.
- Press any key to advance.

---

## Error Handling

- If fewer than 4 images are accepted, exit with a clear error message before attempting calibration.
- Gracefully skip unreadable image files (log a warning, continue).
- Validate that `--marker_size < --square_size`; print an error and exit if not.

---

## Dependencies

```
opencv-contrib-python>=4.8
numpy
pyyaml
```

Include a `requirements.txt` with these pinned to `>=` minimums.

---

## File Layout

```
calibrate.py          # main script
requirements.txt
Cal_Images/           # input calibration images go here
Cal_board/            # (optional) place generated board PDF/PNG here
calibration_output.yaml  # created on successful run
```

---

## Notes for the Agent

- Use `cv2.aruco` from `opencv-contrib-python`, not the base `opencv-python` package (the contrib package includes the ArUco module).
- OpenCV 4.8+ changed the ArUco API (detectors are now objects). Write code compatible with **both** the old and new APIs using a try/except import guard, or target 4.8+ only and document that requirement.
- The reference board image (`Cal_Images/1.png`) can be used as a single test image to verify detection works before running a full calibration session. Do **not** use it as a calibration image itself — a proper calibration requires 15–30 images of the board at varied poses.
- The board may appear in images at significant angles and partial occlusion; the ChArUco detector handles this better than a plain chessboard detector.
