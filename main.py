"""main.py — Calibration application entry point."""

import multiprocessing
import sys

from PySide6.QtWidgets import QApplication

from src.styles import build_dark_palette
from src.widgets.app_window import AppWindow

APP_NAME = "SurveyorCalibration"


def main() -> int:
    from src.paths import migrate_old_name, seed_data
    migrate_old_name()
    seed_data()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SidewalkProfiler")
    app.setPalette(build_dark_palette())
    app.setStyle("Fusion")

    window = AppWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # needed for the detector's worker processes in the exe
    sys.exit(main())
