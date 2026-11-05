"""Annotation viewer: a stand-alone pop-up window for the trouble-shooting files.

Isolated on purpose (Derek, 2026-11-05): it only READS the files the app leaves
beside the photos - <photo>.dots.json (lens), <photo>.targets.json (Old School) and
RUN_*.json - and imports nothing else from the app.  Open it from the app with
open_viewer(folder), or on its own:

    uv run python -m src.viewer "F:\\path\\to\\photos"
"""

from src.viewer.annotation_viewer import AnnotationViewer, open_viewer  # noqa: F401
