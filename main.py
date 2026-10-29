"""main.py — Calibration application entry point."""

import sys

from PySide6.QtWidgets import QApplication

from src.styles import build_dark_palette
from src.widgets.main_window import MainWindow

APP_NAME = "Calibration"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SidewalkProfiler")
    app.setPalette(build_dark_palette())
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
