"""image_review_screen.py — Screen 2: scrollable per-image acceptance list.

Populated via set_data() after detection completes.
Emits proceed_requested() when the user clicks Proceed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.detector import DetectionResult
from src.image_filter import FilterResult
from src.styles import BUTTON_H, MARGIN, SPACING
from src.widgets.image_row_widget import ImageRowWidget

# Minimum accepted images for Proceed to be enabled (matches Instructions spec)
_MIN_ACCEPTED = 6

# ── Layout constants ─────────────────────────────────────────────────────────
_HEADER_H = 28


class ImageReviewScreen(QWidget):
    """Screen 2 — per-image accepted/rejected list with summary and Proceed."""

    proceed_requested = Signal()
    back_requested    = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detections:     list[DetectionResult] = []
        self._filter_results: list[FilterResult]    = []
        self._create_widgets()
        self._create_layouts()
        self._connect_signals()
        self._apply_styles()
        self._load_initial_state()

    # ── Widget Construction ───────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        self.title_label   = QLabel("Image Review")
        self.summary_label = QLabel("No images loaded.")

        # Column header bar
        self.col_filename_label = QLabel("Filename")
        self.col_status_label   = QLabel("Status")
        self.col_corners_label  = QLabel("Corners")
        self.col_blur_label     = QLabel("Blur")
        self.col_reason_label   = QLabel("Rejection Reason")

        # Scrollable list
        self.scroll_area    = QScrollArea()
        self.scroll_content = QWidget()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_content)

        # Action buttons
        self.back_button    = QPushButton("Back")
        self.proceed_button = QPushButton("Proceed to Calibration")
        self.proceed_button.setObjectName("primary_button")
        self.proceed_button.setFixedHeight(BUTTON_H)
        self.proceed_button.setEnabled(False)

    # ── Layout ────────────────────────────────────────────────────────────────
    def _create_layouts(self) -> None:
        # Inner scrollable layout (rows added dynamically)
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(1)
        self.scroll_layout.addStretch()

        # Column header row
        self.header_layout = QHBoxLayout()
        self.header_layout.setSpacing(8)
        self.header_layout.setContentsMargins(4, 2, 4, 2)
        self.header_layout.addWidget(self.col_filename_label, 3)
        self.header_layout.addWidget(self.col_status_label,   1)
        self.header_layout.addWidget(self.col_corners_label,  1)
        self.header_layout.addWidget(self.col_blur_label,     1)
        self.header_layout.addWidget(self.col_reason_label,   3)

        # Button row
        self.button_layout = QHBoxLayout()
        self.button_layout.setSpacing(SPACING)
        self.button_layout.addWidget(self.back_button)
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.proceed_button)

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.main_layout.setSpacing(SPACING)
        self.main_layout.addWidget(self.title_label)
        self.main_layout.addWidget(self.summary_label)
        self.main_layout.addLayout(self.header_layout)
        self.main_layout.addWidget(self.scroll_area, stretch=1)
        self.main_layout.addLayout(self.button_layout)

    # ── Signals & Slots ───────────────────────────────────────────────────────
    def _connect_signals(self) -> None:
        self.proceed_button.clicked.connect(self._on_proceed_button_clicked)
        self.back_button.clicked.connect(self._on_back_button_clicked)

    # ── Styling ───────────────────────────────────────────────────────────────
    def _apply_styles(self) -> None:
        self.title_label.setStyleSheet(
            "font-size: 14pt; font-weight: bold; padding-bottom: 4px;"
        )
        self.summary_label.setStyleSheet("font-size: 10pt;")
        for lbl in (
            self.col_filename_label, self.col_status_label,
            self.col_corners_label, self.col_blur_label, self.col_reason_label,
        ):
            lbl.setStyleSheet(
                "font-size: 8pt; font-weight: bold; color: rgb(140,140,140);"
                "background-color: rgb(40,40,40); padding: 2px 4px;"
            )

    # ── Initial State ─────────────────────────────────────────────────────────
    def _load_initial_state(self) -> None:
        pass   # no persistent state for this screen

    # ── Factory / Populate / Clear (dynamic widgets) ─────────────────────────
    def _factory_image_row(
        self,
        detection: DetectionResult,
        filter_result: FilterResult,
    ) -> ImageRowWidget:
        """Factory: create one ImageRowWidget."""
        return ImageRowWidget(detection, filter_result, parent=self.scroll_content)

    def _populate_image_list(
        self,
        detections: list[DetectionResult],
        filter_results: list[FilterResult],
    ) -> None:
        """Populate the scrollable list with one row per image."""
        self._clear_image_list()
        for det, filt in zip(detections, filter_results):
            row = self._factory_image_row(det, filt)
            # Insert before the trailing stretch item
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, row)

    def _clear_image_list(self) -> None:
        """Remove all ImageRowWidgets; keep the trailing stretch."""
        # Remove all items except the last stretch
        while self.scroll_layout.count() > 1:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── Business Logic ────────────────────────────────────────────────────────
    def set_data(
        self,
        detections: list[DetectionResult],
        filter_results: list[FilterResult],
    ) -> None:
        """Called by MainWindow after detection completes."""
        self._detections     = detections
        self._filter_results = filter_results

        accepted    = sum(f.accepted for f in filter_results)
        no_corners  = sum(
            1 for f in filter_results
            if not f.accepted and "corner" in f.reason.lower()
        )
        too_blurry  = sum(
            1 for f in filter_results
            if not f.accepted and "blur" in f.reason.lower()
        )
        load_errors = sum(
            1 for f in filter_results
            if not f.accepted and "load" in f.reason.lower()
        )

        parts = [f"<b>{accepted} accepted</b>"]
        if no_corners:
            parts.append(f"{no_corners} no corners")
        if too_blurry:
            parts.append(f"{too_blurry} too blurry")
        if load_errors:
            parts.append(f"{load_errors} load error")
        parts.append(f"of {len(filter_results)} total")
        parts.append(f"need ≥ {_MIN_ACCEPTED} to proceed")

        self.summary_label.setText("  ·  ".join(parts))

        enough = accepted >= _MIN_ACCEPTED
        self.proceed_button.setEnabled(enough)
        if not enough:
            self.proceed_button.setToolTip(
                f"Need at least {_MIN_ACCEPTED} accepted images "
                f"({_MIN_ACCEPTED - accepted} more required)."
            )
        else:
            self.proceed_button.setToolTip("")

        self._populate_image_list(detections, filter_results)

    def _on_proceed_button_clicked(self) -> None:
        self.proceed_requested.emit()

    def _on_back_button_clicked(self) -> None:
        self.back_requested.emit()
