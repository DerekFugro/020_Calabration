"""uv run python -m src.viewer [folder]"""
import sys

from PySide6.QtWidgets import QApplication

from src.viewer.annotation_viewer import AnnotationViewer

app = QApplication(sys.argv)
w = AnnotationViewer(sys.argv[1] if len(sys.argv) > 1 else "")
w.show()
sys.exit(app.exec())
