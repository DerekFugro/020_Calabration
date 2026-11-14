"""main.py — Calibration application entry point.

Opens on the start screen (src/widgets/start_screen.py, 2026-11-13).
  --folder <photo folder>   skip the start screen: Load Intrinsic with that folder
                            (SurveyorCapture's "Open in calibration app" uses this).
"""

import argparse
import multiprocessing
import sys

from PySide6.QtWidgets import QApplication

from src.styles import build_dark_palette

APP_NAME = "SurveyorCalibration"


def main() -> int:
    ap = argparse.ArgumentParser(prog=APP_NAME)
    ap.add_argument("--folder", default="", help="photo folder: open Load Intrinsic on it, no start screen")
    ap.add_argument("--camera", default="", help="with --folder: pick this camera in the top bar (SurveyorCapture)")
    args, qt_args = ap.parse_known_args(sys.argv[1:])
    from src.paths import migrate_old_name, seed_data
    migrate_old_name()
    seed_data()
    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SidewalkProfiler")
    app.setPalette(build_dark_palette())
    app.setStyle("Fusion")

    from src.widgets.launcher import Launcher
    launcher = Launcher()
    if args.folder:
        launcher.open_main("intrinsic", folder=args.folder, use_db=True, camera=args.camera)
    else:
        launcher.show()

    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # needed for the detector's worker processes in the exe
    sys.exit(main())
