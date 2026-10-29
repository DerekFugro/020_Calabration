"""diagnose.py â€” Single-image chessboard detection diagnostic.

Usage:
    uv run python diagnose.py path\\to\\image.jpg

Prints what was detected and saves a debug overlay image next to the source.
"""

import sys
import pathlib
import cv2
import numpy as np

from src.board import BoardConfig


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run python diagnose.py <image_path>")
        sys.exit(1)

    img_path = pathlib.Path(sys.argv[1])
    if not img_path.exists():
        print(f"File not found: {img_path}")
        sys.exit(1)

    cfg = BoardConfig()

    # â”€â”€ Load â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    img = cv2.imread(str(img_path))
    if img is None:
        print("ERROR: cv2.imread could not load the file.")
        sys.exit(1)

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()

    print(f"\nImage        : {img_path.name}")
    print(f"Resolution   : {w} Ã— {h}")
    print(f"Blur score   : {blur_score:.1f}")

    # â”€â”€ Detect chessboard corners â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Add white border (required by findChessboardCorners when board is trimmed)
    _PAD = 60
    gray_padded = cv2.copyMakeBorder(
        gray, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_CONSTANT, value=255
    )

    pattern = (cfg.squares_x - 1, cfg.squares_y - 1)   # interior corners
    flags   = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE

    found, corners = cv2.findChessboardCorners(gray_padded, pattern, flags)

    # Shift back to original image coordinates for the overlay
    if found and corners is not None:
        corners = corners - np.array([_PAD, _PAD], dtype=np.float32)

    print(f"Pattern size : {pattern[0]} Ã— {pattern[1]} interior corners")
    print(f"Corners found: {'YES â€” ' + str(len(corners)) + ' corners' if found else 'NO'}")

    if found and corners is not None:
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        corners  = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        n = len(corners)
        if n < 6:
            print(f"â†’ Only {n} corners â€” too few (need â‰¥ 6).")
        else:
            print(f"â†’ Detection looks good!  ({n} corners will be used for calibration)")
    else:
        print("\n*** No chessboard pattern found. ***")
        print("Possible causes:")
        print(f"  1. Wrong board size â€” expecting {cfg.squares_x}Ã—{cfg.squares_y} squares")
        print("     Change Squares X / Y in Setup â†’ Board Parameters to match your board.")
        print("  2. Board partially out of frame â€” all corners must be visible.")
        print("  3. Glare / overexposure â€” use diffuse lighting, no direct flash.")
        print("  4. Insufficient contrast â€” board needs clear black-and-white squares.")
        print(f"  5. Too small in frame â€” at {w}Ã—{h} each square should be â‰¥ 20 px wide.")


    # â”€â”€ Save debug overlay â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    debug = img.copy()
    if found and corners is not None:
        cv2.drawChessboardCorners(debug, pattern, corners, found)

    label = f"{w}x{h}  blur={blur_score:.0f}  corners={'OK' if found else 'NONE'}"
    cv2.putText(debug, label, (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2, cv2.LINE_AA)

    out_path = img_path.parent / (img_path.stem + "_DEBUG.jpg")
    cv2.imwrite(str(out_path), debug, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"\nDebug image saved : {out_path}\n")


if __name__ == "__main__":
    main()
