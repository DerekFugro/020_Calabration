"""image_row_widget.py — One row in the Image Review list.

Each row shows: filename | Accepted/Rejected badge | corner count | blur | reason.
Created via the factory pattern in ImageReviewScreen.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from src.detector import DetectionResult
from src.image_filter import FilterResult
from src.styles import (
    MARGIN, SPACING, ROW_H,
    C_GREEN, C_RED, C_TEXT_DIM, C_BG_WIDGET, C_BG,
)

# ── Layout constants ─────────────────────────────────────────────────────────
_ROW_MARGIN      = 4
_ROW_SPACING     = 8
_FILENAME_W      = 260
_BADGE_W         = 76
_CORNERS_W       = 60
_BLUR_W          = 60


class ImageRowWidget(QWidget):
    """One row in the scrollable per-image results list."""

    def __init__(
        self,
        detection: DetectionResult,
        filter_result: FilterResult,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._detection    = detection
        self._filter_result = filter_result
        self._create_widgets()
        self._create_layouts()
        self._connect_signals()
        self._apply_styles()
        self._load_initial_state()

    # ── Widget Construction ───────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        self.filename_label = QLabel()
        self.filename_label.setMinimumWidth(_FILENAME_W)

        self.status_badge = QLabel()
        self.status_badge.setFixedWidth(_BADGE_W)
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.corners_label = QLabel()
        self.corners_label.setFixedWidth(_CORNERS_W)
        self.corners_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.blur_label = QLabel()
        self.blur_label.setFixedWidth(_BLUR_W)
        self.blur_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.reason_label = QLabel()

    # ── Layout ────────────────────────────────────────────────────────────────
    def _create_layouts(self) -> None:
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(
            _ROW_MARGIN, _ROW_MARGIN, _ROW_MARGIN, _ROW_MARGIN
        )
        self.main_layout.setSpacing(_ROW_SPACING)
        self.main_layout.addWidget(self.filename_label)
        self.main_layout.addWidget(self.status_badge)
        self.main_layout.addWidget(self.corners_label)
        self.main_layout.addWidget(self.blur_label)
        self.main_layout.addWidget(self.reason_label, stretch=1)

    # ── Signals & Slots ───────────────────────────────────────────────────────
    def _connect_signals(self) -> None:
        pass

    # ── Styling ───────────────────────────────────────────────────────────────
    def _apply_styles(self) -> None:
        accepted = self._filter_result.accepted
        fg = C_GREEN if accepted else C_RED

        self.status_badge.setStyleSheet(
            f"color: rgb({fg[0]},{fg[1]},{fg[2]});"
            f"font-weight: bold;"
            f"font-size: 9pt;"
        )
        self.filename_label.setStyleSheet(f"font-size: 9pt;")
        self.corners_label.setStyleSheet(
            f"color: rgb({C_TEXT_DIM[0]},{C_TEXT_DIM[1]},{C_TEXT_DIM[2]});"
            f"font-size: 9pt;"
        )
        self.blur_label.setStyleSheet(
            f"color: rgb({C_TEXT_DIM[0]},{C_TEXT_DIM[1]},{C_TEXT_DIM[2]});"
            f"font-size: 9pt;"
        )
        self.reason_label.setStyleSheet(
            f"color: rgb({C_TEXT_DIM[0]},{C_TEXT_DIM[1]},{C_TEXT_DIM[2]});"
            f"font-size: 9pt;"
        )

        # Alternate row background
        if self._filter_result.accepted:
            bg = "rgb(28,40,28)"
        else:
            bg = "rgb(40,28,28)"
        self.setStyleSheet(f"background-color: {bg};")

    # ── Initial State ─────────────────────────────────────────────────────────
    def _load_initial_state(self) -> None:
        name = os.path.basename(self._detection.image_path)
        if len(name) > 38:
            name = "…" + name[-37:]
        self.filename_label.setText(name)

        self.status_badge.setText(
            "Accepted" if self._filter_result.accepted else "Rejected"
        )
        self.corners_label.setText(
            f"{self._filter_result.corner_count} corners"
        )
        self.blur_label.setText(f"blur {self._filter_result.blur_score:.0f}")
        self.reason_label.setText(
            "" if self._filter_result.accepted else self._filter_result.reason
        )
