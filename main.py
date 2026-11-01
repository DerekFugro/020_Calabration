"""main.py — Calibration application entry point."""

import sys

from PySide6.QtWidgets import QApplication

from src.styles import build_dark_palette
from src.widgets.app_window import AppWindow

APP_NAME = "Calibration"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SidewalkProfiler")
    app.setPalette(build_dark_palette())
    app.setStyle("Fusion")

    window = AppWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
