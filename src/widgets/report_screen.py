"""report_screen.py — Screen 3: calibration results, verdict, and Save button.

Populated via set_data() after calibration completes.
Emits save_requested() and new_calibration_requested().
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.board import BoardConfig
from src.calibrator import CalibrationResult
from src.coverage import GOOD, POOR, WEAK, compute_grid, limits_text
from src.quality import QualityReport
from src.styles import (
    BUTTON_H, MARGIN, SPACING,
    VERDICT_COLOURS, C_TEXT_DIM,
    C_AMBER, C_AMBER_BG, C_GREEN, C_GREEN_BG, C_RED, C_RED_BG,
)

# 3x3 coverage grid colours: (text/border, background) per status
_GRID_COLOURS = {
    GOOD: (C_GREEN, C_GREEN_BG),
    WEAK: (C_AMBER, C_AMBER_BG),
    POOR: (C_RED,   C_RED_BG),
}
_GRID_CELL_W = 180
_GRID_CELL_H = 74

# ── Layout constants ─────────────────────────────────────────────────────────
_BADGE_H      = 44
_KEY_W        = 200
_SECTION_VPAD = 6
_MATRIX_CELL  = 80
_MAX_DIST     = 14     # max distortion coefficients pre-allocated


# Reprojection error threshold above which an image is flagged as an outlier
_OUTLIER_THRESHOLD = 1.0  # pixels


class ReportScreen(QWidget):
    """Screen 3 — verdict, camera parameters, Save and New Calibration buttons."""

    save_requested                  = Signal()
    new_calibration_requested       = Signal()
    remove_and_recalibrate_requested = Signal(list)  # list[str] paths to REMOVE

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._create_widgets()
        self._create_layouts()
        self._connect_signals()
        self._apply_styles()
        self._load_initial_state()

    # ── Widget Construction ───────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        # Title
        self.title_label = QLabel("Calibration Report")

        # Verdict badge
        self.verdict_badge = QLabel("—")
        self.verdict_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict_badge.setFixedHeight(_BADGE_H)

        # Grade banner (src/grading.py): pass/fail + what to shoot next
        self.folder_label  = QLabel("")
        self.folder_label.setWordWrap(True)
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setStyleSheet("color: rgb(170,170,170); font-size: 9pt;")
        self.grade_banner  = QLabel("")
        self.grade_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grade_banner.setWordWrap(True)
        self.grade_details = QLabel("")
        self.grade_details.setWordWrap(True)
        self.grade_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # Scroll area for the results body
        self.scroll_area    = QScrollArea()
        self.scroll_content = QWidget()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_content)

        # ── Summary KV labels ──────────────────────────────────────────────
        self.rms_key_label        = QLabel("RMS Reprojection Error:")
        self.rms_val_label        = QLabel("—")

        self.images_key_label     = QLabel("Images Used:")
        self.images_val_label     = QLabel("—")

        self.focal_key_label      = QLabel("Focal Length:")
        self.focal_val_label      = QLabel("—")

        self.principal_key_label  = QLabel("Principal Point:")
        self.principal_val_label  = QLabel("—")

        self.resolution_key_label = QLabel("Image Resolution:")
        self.resolution_val_label = QLabel("—")

        self.focus_key_label      = QLabel("Focus Quality:")
        self.focus_val_label      = QLabel("—")

        # ── 3x3 image coverage section ─────────────────────────────────────
        self.grid_section_label = QLabel("Image Coverage (3 × 3)")
        self.grid_frame         = QFrame()
        self.grid_cells = [[QLabel("—") for _ in range(3)] for _ in range(3)]
        self.grid_legend        = QLabel(limits_text())
        self.grid_legend.setWordWrap(True)
        self.grid_advice        = QLabel("")
        self.grid_advice.setWordWrap(True)
        self.grid_advice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # ── Camera matrix section ──────────────────────────────────────────
        self.matrix_section_label = QLabel("Camera Matrix")
        self.matrix_frame         = QFrame()
        self.matrix_frame.setFrameShape(QFrame.Shape.Box)
        # 3×3 grid of value labels
        self.matrix_labels = [
            [QLabel("—") for _ in range(3)]
            for _ in range(3)
        ]

        # ── Distortion coefficients section ───────────────────────────────
        self.dist_section_label = QLabel("Distortion Coefficients")
        self.dist_frame         = QFrame()
        self.dist_frame.setFrameShape(QFrame.Shape.Box)
        self.dist_key_labels = [QLabel(n) for n in
                                ["k1","k2","p1","p2","k3",
                                 "k4","k5","k6","s1","s2",
                                 "s3","s4","tx","ty"]]
        self.dist_val_labels = [QLabel("—") for _ in range(_MAX_DIST)]

        # ── Board parameters section ───────────────────────────────────────
        self.board_section_label  = QLabel("Board Parameters")
        self.board_squares_key    = QLabel("Squares X × Y:")
        self.board_squares_val    = QLabel("—")
        self.board_cell_key       = QLabel("Cell Size (mm):")
        self.board_cell_val       = QLabel("—")
        self.board_marker_key     = QLabel("Marker Size (mm):")
        self.board_marker_val     = QLabel("—")
        self.board_dict_key       = QLabel("Detection:")
        self.board_dict_val       = QLabel("—")

        # ── Action buttons ─────────────────────────────────────────────────
        self.save_button    = QPushButton("Save Report (YAML + PDF)")
        self.save_button.setObjectName("primary_button")
        self.save_button.setFixedHeight(BUTTON_H)
        self.save_button.setEnabled(False)

        self.new_cal_button = QPushButton("New Calibration")
        self.new_cal_button.setFixedHeight(BUTTON_H)

        # ── Outlier panel (hidden until bad images found) ──────────────────
        self.outlier_group   = QGroupBox("Photos left out automatically")
        self.outlier_label   = QLabel()
        self.outlier_label.setWordWrap(True)
        self.recalibrate_btn = QPushButton("Remove Flagged Images & Recalibrate")
        self.recalibrate_btn.setFixedHeight(BUTTON_H)
        self.recalibrate_btn.setObjectName("primary_button")
        self._outlier_paths: list[str] = []
        self.outlier_group.hide()

    # ── Layout ────────────────────────────────────────────────────────────────
    def _create_layouts(self) -> None:
        # 3x3 coverage grid
        self.cov_grid = QGridLayout(self.grid_frame)
        self.cov_grid.setSpacing(4)
        self.cov_grid.setContentsMargins(0, 0, 0, 0)
        for r in range(3):
            for c in range(3):
                lbl = self.grid_cells[r][c]
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setFixedSize(_GRID_CELL_W, _GRID_CELL_H)
                self.cov_grid.addWidget(lbl, r, c)
        self.cov_grid.setColumnStretch(3, 1)

        # Camera matrix inner grid
        self.matrix_grid = QGridLayout(self.matrix_frame)
        self.matrix_grid.setSpacing(2)
        for r in range(3):
            for c in range(3):
                lbl = self.matrix_labels[r][c]
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setFixedSize(_MATRIX_CELL, 24)
                self.matrix_grid.addWidget(lbl, r, c)

        # Distortion coefficients inner grid
        self.dist_grid = QGridLayout(self.dist_frame)
        self.dist_grid.setSpacing(2)
        for i in range(_MAX_DIST):
            self.dist_key_labels[i].setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.dist_val_labels[i].setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.dist_val_labels[i].setFixedWidth(72)
            self.dist_grid.addWidget(self.dist_key_labels[i], 0, i)
            self.dist_grid.addWidget(self.dist_val_labels[i], 1, i)

        # Summary form (key-value pairs)
        self.summary_layout = QGridLayout()
        self.summary_layout.setSpacing(SPACING)
        self.summary_layout.setColumnMinimumWidth(0, _KEY_W)
        pairs = [
            (self.rms_key_label,        self.rms_val_label),
            (self.images_key_label,     self.images_val_label),
            (self.focal_key_label,      self.focal_val_label),
            (self.principal_key_label,  self.principal_val_label),
            (self.resolution_key_label, self.resolution_val_label),
            (self.focus_key_label,      self.focus_val_label),
        ]
        for row, (key_lbl, val_lbl) in enumerate(pairs):
            self.summary_layout.addWidget(key_lbl, row, 0)
            self.summary_layout.addWidget(val_lbl, row, 1)

        # Outlier panel layout
        self.outlier_layout = QVBoxLayout()
        self.outlier_layout.setSpacing(SPACING)
        self.outlier_layout.addWidget(self.outlier_label)
        self.outlier_layout.addWidget(self.recalibrate_btn)
        self.outlier_group.setLayout(self.outlier_layout)

        # Scroll content layout
        self.scroll_main_layout = QVBoxLayout(self.scroll_content)
        self.scroll_main_layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.scroll_main_layout.setSpacing(SPACING * 2)
        self.scroll_main_layout.addWidget(self.grade_details)
        self.scroll_main_layout.addLayout(self.summary_layout)
        self.scroll_main_layout.addWidget(self.outlier_group)
        self.scroll_main_layout.addWidget(self.grid_section_label)
        self.scroll_main_layout.addWidget(self.grid_frame)
        self.scroll_main_layout.addWidget(self.grid_legend)
        self.scroll_main_layout.addWidget(self.grid_advice)
        self.scroll_main_layout.addWidget(self.matrix_section_label)
        self.scroll_main_layout.addWidget(self.matrix_frame)
        self.scroll_main_layout.addWidget(self.dist_section_label)
        self.scroll_main_layout.addWidget(self.dist_frame)
        self.scroll_main_layout.addWidget(self.board_section_label)
        self.scroll_main_layout.addLayout(self._build_board_layout())
        self.scroll_main_layout.addStretch()

        # Button row
        self.button_layout = QHBoxLayout()
        self.button_layout.setSpacing(SPACING)
        self.button_layout.addWidget(self.new_cal_button)
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.save_button)

        # Top-level layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.main_layout.setSpacing(SPACING)
        self.main_layout.addWidget(self.title_label)
        self.main_layout.addWidget(self.folder_label)
        self.main_layout.addWidget(self.grade_banner)
        self.main_layout.addWidget(self.scroll_area, stretch=1)
        self.main_layout.addLayout(self.button_layout)

    def _build_board_layout(self) -> QGridLayout:
        """Helper: build the board parameters KV grid (used only in _create_layouts)."""
        self.board_kv_layout = QGridLayout()
        self.board_kv_layout.setSpacing(SPACING)
        self.board_kv_layout.setColumnMinimumWidth(0, _KEY_W)
        board_pairs = [
            (self.board_squares_key, self.board_squares_val),
            (self.board_cell_key,    self.board_cell_val),
            (self.board_marker_key,  self.board_marker_val),
            (self.board_dict_key,    self.board_dict_val),
        ]
        for row, (k, v) in enumerate(board_pairs):
            self.board_kv_layout.addWidget(k, row, 0)
            self.board_kv_layout.addWidget(v, row, 1)
        return self.board_kv_layout

    # ── Signals & Slots ───────────────────────────────────────────────────────
    def _connect_signals(self) -> None:
        self.save_button.clicked.connect(self._on_save_button_clicked)
        self.new_cal_button.clicked.connect(self._on_new_cal_button_clicked)
        self.recalibrate_btn.clicked.connect(self._on_recalibrate_clicked)

    # ── Styling ───────────────────────────────────────────────────────────────
    def _apply_styles(self) -> None:
        self.title_label.setStyleSheet(
            "font-size: 14pt; font-weight: bold; padding-bottom: 4px;"
        )
        self.verdict_badge.setStyleSheet(
            "font-size: 14pt; font-weight: bold; border-radius: 4px;"
        )
        dim = f"rgb({C_TEXT_DIM[0]},{C_TEXT_DIM[1]},{C_TEXT_DIM[2]})"
        for lbl in (
            self.matrix_section_label, self.dist_section_label,
            self.board_section_label, self.grid_section_label,
        ):
            lbl.setStyleSheet(
                f"font-size: 9pt; font-weight: bold; color: {dim};"
                "border-bottom: 1px solid rgb(60,60,60); padding-bottom: 2px;"
            )
        self.outlier_group.setStyleSheet(
            "QGroupBox { border: 1px solid rgb(183,28,28); border-radius: 4px;"
            " margin-top: 8px; font-weight: bold; color: rgb(229,115,115); }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
        )
        self.outlier_label.setStyleSheet("color: rgb(229,115,115); font-size: 9pt;")
        self.grid_legend.setStyleSheet(f"font-size: 8pt; color: {dim};")
        self.grid_advice.setStyleSheet("font-size: 9pt;")
        for lbl in (
            self.rms_key_label, self.images_key_label, self.focal_key_label,
            self.principal_key_label, self.resolution_key_label, self.focus_key_label,
            self.board_squares_key, self.board_cell_key,
            self.board_marker_key, self.board_dict_key,
        ):
            lbl.setStyleSheet("font-weight: bold; font-size: 9pt;")
        for lbl in self.dist_key_labels:
            lbl.setStyleSheet(f"font-size: 8pt; color: {dim};")

    # ── Initial State ─────────────────────────────────────────────────────────
    def _load_initial_state(self) -> None:
        # Hide all distortion labels until real data arrives
        for i in range(_MAX_DIST):
            self.dist_key_labels[i].hide()
            self.dist_val_labels[i].hide()

    # ── Business Logic ────────────────────────────────────────────────────────
    def set_data(
        self,
        cal_result: CalibrationResult,
        quality: QualityReport,
        board_config: BoardConfig,
        image_folder: str = "",
    ) -> None:
        """Called by MainWindow after calibration completes."""
        from src.photo_folders import folder_lines
        self.folder_label.setText("\n".join(folder_lines(cal_result, image_folder)))
        self._update_summary(cal_result, quality)
        self._update_matrix(cal_result.camera_matrix)
        self._update_dist(cal_result.dist_coeffs)
        self._update_board(board_config)
        self._update_outliers(cal_result)
        self._update_grid(cal_result)
        self._update_grade(cal_result)
        self.save_button.setEnabled(True)

    def _update_grade(self, cal_result: CalibrationResult) -> None:
        """Show the grade: PASS, or what to shoot next."""
        import html
        g = getattr(cal_result, "grade", None)
        if g is None:
            self.grade_banner.hide(); self.grade_details.hide()
            return
        fg, bg = (C_GREEN, C_GREEN_BG) if g.passed else (C_RED, C_RED_BG)
        self.grade_banner.setText(g.headline)
        self.grade_banner.setStyleSheet(
            f"font-size: 16pt; font-weight: bold; padding: 10px; border-radius: 4px;"
            f"color: rgb({fg[0]},{fg[1]},{fg[2]}); background: rgb({bg[0]},{bg[1]},{bg[2]});"
        )
        parts = []
        rp = g.repeatability
        if rp is not None:
            parts.append(f"<b>Repeatability:</b> about {rp.at_10m_mm:.0f} mm at 10 m "
                         f"({rp.est_error_p95_mrad:.2f} mrad). Limit 10 mm.")
        parts += [f"<b>STOP:</b> {html.escape(s)}" for s in g.hard_stops]
        parts += [f"&bull; {html.escape(r)}" for r in g.reasons]
        parts += [f"<span style='color:#e0b050'>&#9888; {html.escape(w)}</span>"
                  for w in getattr(g, "warnings", [])]
        bl = getattr(g, "blur_median_px", float("nan"))
        if bl == bl:
            parts.append(f"<b>Sharpness:</b> dot edge blur {bl:.1f} px (sharp is about 1 px).")
        if g.coaching:
            parts.append("<b>What to do:</b>")
            parts += [f"&nbsp;&nbsp;&rarr; {html.escape(c)}" for c in g.coaching]
        if g.worst_images:
            parts.append("<b>Worst photos:</b> " + ", ".join(
                f"{html.escape(Path(p).name)} ({e:.1f} px)" for p, e in g.worst_images))
        if not g.passed:
            parts.append("<i>Saving still writes the local files; publishing to the store "
                         "needs a PASS.</i>")
        self.grade_details.setText("<br>".join(parts))
        self.grade_banner.show(); self.grade_details.show()

    def _update_grid(self, cal_result: CalibrationResult) -> None:
        """Fill the 3x3 coverage grid (src/coverage.py)."""
        try:
            grid = compute_grid(cal_result)
        except Exception as exc:  # noqa: BLE001 — never block the report
            for row in self.grid_cells:
                for lbl in row:
                    lbl.setText("—")
                    lbl.setStyleSheet("")
            self.grid_advice.setText(f"Coverage grid not available: {exc}")
            return
        for row in grid.cells:
            for cell in row:
                lbl = self.grid_cells[cell.row][cell.col]
                fg, bg = _GRID_COLOURS[cell.status]
                err = "—" if cell.points == 0 else f"{cell.rms_px:.2f} px"
                lbl.setText(
                    f"<b>{cell.name}</b><br>"
                    f"{cell.points} points · {err}<br>"
                    f"angles {cell.tilt_spread_deg:.0f}°"
                )
                lbl.setToolTip("\n".join(cell.problems()) or "Good")
                lbl.setStyleSheet(
                    f"background: rgb({bg[0]},{bg[1]},{bg[2]});"
                    f"border: 1px solid rgb({fg[0]},{fg[1]},{fg[2]});"
                    "border-radius: 4px; font-size: 9pt;"
                )
        advice = grid.advice()
        if advice:
            self.grid_advice.setText(
                f"{grid.count(POOR)} red, {grid.count(WEAK)} yellow, "
                f"{grid.count(GOOD)} green.<br>" + "<br>".join(advice)
            )
        else:
            self.grid_advice.setText("All 9 areas are green.")

    def _update_verdict(self, quality: QualityReport) -> None:
        text_rgb, bg_rgb = VERDICT_COLOURS.get(
            quality.verdict, ((220, 220, 220), (60, 60, 60))
        )
        self.verdict_badge.setText(quality.verdict)
        self.verdict_badge.setStyleSheet(
            f"font-size: 14pt; font-weight: bold; border-radius: 4px;"
            f"color: rgb({text_rgb[0]},{text_rgb[1]},{text_rgb[2]});"
            f"background-color: rgb({bg_rgb[0]},{bg_rgb[1]},{bg_rgb[2]});"
        )

    def _update_summary(
        self, cal: CalibrationResult, quality: QualityReport
    ) -> None:
        cam = cal.camera_matrix
        self.rms_val_label.setText(f"{cal.rms:.4f} px")
        self.images_val_label.setText(
            f"{cal.image_count_used}  (need >= {quality.image_count_needed})"
        )
        self.focal_val_label.setText(
            f"fx = {cam[0,0]:.2f} px     fy = {cam[1,1]:.2f} px"
        )
        self.principal_val_label.setText(
            f"cx = {cam[0,2]:.2f} px     cy = {cam[1,2]:.2f} px"
        )
        self.resolution_val_label.setText(
            f"{cal.image_size[0]} × {cal.image_size[1]} px"
        )
        # Focus quality: a rough proxy from the accept rate
        self.focus_val_label.setText("OK (based on blur filter)")

    def _update_matrix(self, camera_matrix) -> None:
        for r in range(3):
            for c in range(3):
                self.matrix_labels[r][c].setText(f"{camera_matrix[r, c]:.4f}")

    def _update_dist(self, dist_coeffs) -> None:
        flat = dist_coeffs.flatten().tolist()
        n = len(flat)
        for i in range(_MAX_DIST):
            visible = i < n
            self.dist_key_labels[i].setVisible(visible)
            self.dist_val_labels[i].setVisible(visible)
            if visible:
                self.dist_val_labels[i].setText(f"{flat[i]:.6f}")

    def _update_board(self, cfg: BoardConfig) -> None:
        if cfg.is_dots:
            self.board_squares_key.setText("Board:")
            self.board_squares_val.setText(cfg.name)
            self.board_cell_key.setText("Dots:")
            self.board_cell_val.setText(str(cfg.num_corners))
            self.board_marker_key.setText("Layout file:")
            self.board_marker_val.setText(Path(cfg.layout_csv).name)
            self.board_dict_val.setText("Random-dot board, dot centroids")
            return
        self.board_squares_key.setText("Squares X × Y:")
        self.board_cell_key.setText("Cell Size (mm):")
        self.board_marker_key.setText("Marker Size (mm):")
        self.board_squares_val.setText(f"{cfg.squares_x} × {cfg.squares_y}")
        self.board_cell_val.setText(
            f"{cfg.cell_width_mm:.4f} × {cfg.cell_height_mm:.4f}"
        )
        self.board_marker_val.setText("—")
        self.board_dict_val.setText("Plain chessboard (ArUco ignored)")

    def _on_save_button_clicked(self) -> None:
        self.save_requested.emit()

    def _on_new_cal_button_clicked(self) -> None:
        self.new_calibration_requested.emit()

    def _on_recalibrate_clicked(self) -> None:
        self.remove_and_recalibrate_requested.emit(self._outlier_paths)

    def _update_outliers(self, cal_result: CalibrationResult) -> None:
        """List the photos src/auto_clean.py left out (no button: it is automatic)."""
        import pathlib
        self.recalibrate_btn.hide()
        removed = list(getattr(cal_result, "auto_removed", []) or [])
        self._outlier_paths = []
        if not removed:
            self.outlier_group.hide()
            return
        lines = [f"• {pathlib.Path(p).name}  —  {why}" for p, why in removed]
        self.outlier_label.setText(
            f"{len(removed)} photo(s) fit much worse than the rest or were blurry, so they were "
            "left out and the camera was calibrated again.  They stay in the folder.\n\n"
            + "\n".join(lines))
        self.outlier_group.show()
