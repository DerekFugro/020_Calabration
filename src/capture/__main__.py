"""SurveyorCapture: uv run python -m src.capture [--van ARAN69] [--camera ROW] [--folder <path>] [--no-db]"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(prog="SurveyorCapture")
    ap.add_argument("--van", default="")
    ap.add_argument("--camera", default="")
    ap.add_argument("--folder", default="")
    ap.add_argument("--no-db", action="store_true", help="don't use the van database (cameras from Windows inputs)")
    a, qt_args = ap.parse_known_args(sys.argv[1:])
    from PySide6.QtWidgets import QApplication

    from src.styles import build_dark_palette
    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("SurveyorCapture"); app.setOrganizationName("SidewalkProfiler")
    app.setPalette(build_dark_palette()); app.setStyle("Fusion")
    from src.capture.window import CaptureWindow
    w = CaptureWindow(van=a.van, camera=a.camera, folder=a.folder, use_db=not a.no_db)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
