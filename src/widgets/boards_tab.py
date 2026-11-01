"""boards_tab.py — Boards tab: add a board to the library and measure its print.

Left: the boards in Cal_board.  Right: three steps.
  1. Add  — dots: pick the layout CSV (it is copied into Cal_board/<name>/);
            chessboard: squares and cell size.  Writes board.yaml + true-scale PDF.
  2. Measure the print — dots: A-B and C-D centre to centre (marked in red on
            the PDF); chessboard: full width and height.  Saves the scale.
  3. Test — pick a few photos of the board; auto-detect must pick it.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from src import board_builder as bb
from src.boards import CAL_BOARD_DIR, list_boards


def _mm_spin(val=0.0, maxv=10000.0):
    s = QDoubleSpinBox(); s.setRange(0.0, maxv); s.setDecimals(2); s.setSuffix(" mm"); s.setValue(val)
    return s


class BoardsTab(QWidget):
    boards_changed = Signal()
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()
        self._refresh()

    def _build(self) -> None:
        # Library list
        self.list = QListWidget()
        self.open_btn = QPushButton("Open board folder")
        left = QVBoxLayout()
        left.addWidget(QLabel(f"Board library:\n{CAL_BOARD_DIR}"))
        left.addWidget(self.list, 1); left.addWidget(self.open_btn)

        # 1. Add
        self.type_combo = QComboBox(); self.type_combo.addItems(["Dots (CSV layout)", "Chessboard"])
        self.name_edit = QLineEdit(); self.name_edit.setPlaceholderText("e.g. Randot-004")
        self.csv_edit = QLineEdit(); self.csv_edit.setPlaceholderText("Dot layout CSV (metres)…")
        self.csv_btn = QPushButton("Browse…")
        self.label_edit = QLineEdit(); self.label_edit.setPlaceholderText("text printed on the board (optional)")
        self.csv_info = QLabel(""); self.csv_info.setWordWrap(True)
        csv_row = QHBoxLayout(); csv_row.addWidget(self.csv_edit, 1); csv_row.addWidget(self.csv_btn)
        dots = QWidget(); f = QFormLayout(dots); f.setContentsMargins(0, 0, 0, 0)
        f.addRow("Layout CSV:", csv_row); f.addRow("Label:", self.label_edit); f.addRow(self.csv_info)
        self.sq_x = QSpinBox(); self.sq_x.setRange(3, 50); self.sq_x.setValue(12)
        self.sq_y = QSpinBox(); self.sq_y.setRange(3, 50); self.sq_y.setValue(8)
        self.cell_w = _mm_spin(76.39, 500); self.cell_h = _mm_spin(76.39, 500)
        chess = QWidget(); g = QFormLayout(chess); g.setContentsMargins(0, 0, 0, 0)
        g.addRow("Squares across:", self.sq_x); g.addRow("Squares down:", self.sq_y)
        g.addRow("Cell width:", self.cell_w); g.addRow("Cell height:", self.cell_h)
        self.kind_stack = QStackedWidget(); self.kind_stack.addWidget(dots); self.kind_stack.addWidget(chess)
        self.add_btn = QPushButton("Add board (copy CSV, write board.yaml and PDF)")
        add = QGroupBox("1. Add a board"); af = QFormLayout(add)
        af.addRow("Type:", self.type_combo); af.addRow("Name:", self.name_edit)
        af.addRow(self.kind_stack); af.addRow(self.add_btn)

        # 2. Measure — saved by itself once all four readings make sense
        self.measure_help = QLabel("Pick a board on the left."); self.measure_help.setWordWrap(True)
        self.r = [_mm_spin() for _ in range(4)]
        for sp in self.r:
            sp.setSpecialValueText("—")          # 0 = not entered; never pre-filled
        self.m1_label = QLabel("A-B, two readings:"); self.m2_label = QLabel("C-D, two readings:")
        row1 = QHBoxLayout(); row1.addWidget(self.r[0]); row1.addWidget(self.r[1])
        row2 = QHBoxLayout(); row2.addWidget(self.r[2]); row2.addWidget(self.r[3])
        self.measure_status = QLabel(""); self.measure_status.setWordWrap(True)
        self.mpdf_btn = QPushButton("Make PDF with A-B / C-D marks")
        meas = QGroupBox("2. Print it at 100%, then measure the print twice"); mf = QFormLayout(meas)
        mf.addRow(self.measure_help); mf.addRow(self.m1_label, row1); mf.addRow(self.m2_label, row2)
        mf.addRow(self.measure_status); mf.addRow(self.mpdf_btn)

        # 3. Test
        self.test_btn = QPushButton("Pick photos of this board and test auto-detect…")
        test = QGroupBox("3. Test with a few photos"); tf = QVBoxLayout(test); tf.addWidget(self.test_btn)

        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        right = QVBoxLayout()
        right.addWidget(add); right.addWidget(meas); right.addWidget(test); right.addWidget(self.log, 1)

        lay = QHBoxLayout(self)
        lw = QWidget(); lw.setLayout(left); lw.setMaximumWidth(330)
        lay.addWidget(lw); rw = QWidget(); rw.setLayout(right); lay.addWidget(rw, 1)

        self.type_combo.currentIndexChanged.connect(self.kind_stack.setCurrentIndex)
        self.csv_btn.clicked.connect(self._pick_csv)
        self.csv_edit.editingFinished.connect(self._check_csv)
        self.add_btn.clicked.connect(self._add)
        self.list.currentRowChanged.connect(self._on_select)
        for sp in self.r:
            sp.editingFinished.connect(self._measure)
        self.mpdf_btn.clicked.connect(self._make_measure_pdf)
        self.test_btn.clicked.connect(self._test)
        self.open_btn.clicked.connect(self._open_folder)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _refresh(self, select: str = "") -> None:
        errs: list[str] = []
        self._boards = list_boards(errors=errs)
        self.list.clear()
        for b in self._boards:
            kind = f"{b.num_corners} dots" if b.is_dots else f"{b.squares_x}x{b.squares_y} chessboard"
            self.list.addItem(f"{b.name}   ({kind})")
        for i, b in enumerate(self._boards):
            if select and Path(b.folder or "").name == select:
                self.list.setCurrentRow(i)
        if errs:
            self.log.appendPlainText("Skipped board folders: " + "; ".join(errs))

    def _current(self):
        i = self.list.currentRow()
        return self._boards[i] if 0 <= i < len(self._boards) else None

    def _pick_csv(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Dot layout CSV", "", "CSV / text (*.csv *.txt);;All files (*)")
        if p:
            self.csv_edit.setText(p)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(p).stem.replace("(in)", "").strip())
            self._check_csv()

    def _check_csv(self) -> None:
        p = self.csv_edit.text().strip()
        if p and os.path.isfile(p):
            self.csv_info.setText(bb.check_dot_csv(p).text())

    # ── 1. add ───────────────────────────────────────────────────────────────
    def _add(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Add board", "Give the board a name."); return
        try:
            if self.type_combo.currentIndex() == 0:
                csv = self.csv_edit.text().strip()
                if not os.path.isfile(csv):
                    QMessageBox.warning(self, "Add board", "Pick the layout CSV."); return
                chk = bb.check_dot_csv(csv)
                if not chk.dots:
                    QMessageBox.warning(self, "Add board", chk.text()); return
                if chk.problems and QMessageBox.question(
                        self, "Add board", chk.text() + "\n\nAdd it anyway?") != QMessageBox.StandardButton.Yes:
                    return
                folder = bb.create_dot_board(name, csv, self.label_edit.text().strip())
            else:
                folder = bb.create_chessboard(name, self.sq_x.value(), self.sq_y.value(),
                                              self.cell_w.value(), self.cell_h.value())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Add board", str(exc)); return
        self.log.appendPlainText(f"Added {folder}\n  board.yaml, PDF" +
                                 (", copy of the CSV" if self.type_combo.currentIndex() == 0 else ""))
        self._refresh(select=folder.name)
        self.boards_changed.emit()
        self.status.emit(f"Board added: {folder.name}.  Print the PDF at 100% and measure it.")

    # ── 2. measure ───────────────────────────────────────────────────────────
    def _on_select(self, *_a) -> None:
        b = self._current()
        if b is None:
            return
        for sp in self.r:
            sp.blockSignals(True); sp.setValue(0.0); sp.blockSignals(False)
        self.measure_status.setText("")
        try:
            spec = bb._read_spec(Path(b.folder))
            kind, n1, n2 = bb.nominal_lengths(b.folder)
        except Exception as exc:  # noqa: BLE001
            self.measure_help.setText(f"{b.name}: can't read board.yaml ({exc})."); return
        if kind == "dots":
            m = spec.get("measure") or {}
            self.mpdf_btn.setEnabled(True)
            self.m1_label.setText("A-B, two readings:"); self.m2_label.setText("C-D, two readings:")
            done = m.get("AB_measured_mm") is not None
            self.measure_help.setText(
                f"{b.name}: tape centre to centre between the red letters, each distance twice.  "
                f"File: A-B {n1:.1f} mm, C-D {n2:.1f} mm.  "
                + (f"Last measured {m.get('date', '')}: A-B {m['AB_measured_mm']:.1f}, "
                   f"C-D {m['CD_measured_mm']:.1f} mm (scale X {spec.get('scale_x', 1):.5f}, "
                   f"Y {spec.get('scale_y', 1):.5f})." if done else "NOT MEASURED YET.")
                + ("" if spec.get("measure") else "  Older board: no red marks on its PDF; "
                   "use Make PDF to print them."))
        else:
            self.mpdf_btn.setEnabled(False)
            self.m1_label.setText("Width, two readings:"); self.m2_label.setText("Height, two readings:")
            self.measure_help.setText(
                f"{b.name}: measure the squares edge to edge, full width ({b.squares_x} squares) and "
                f"full height ({b.squares_y} squares), each twice.  File: {n1:.1f} x {n2:.1f} mm.  "
                f"Now: cell {b.cell_width_mm:.2f} x {b.cell_height_mm:.2f} mm.")

    def _make_measure_pdf(self) -> None:
        b = self._current()
        if b is None or not b.is_dots:
            return
        try:
            out = bb.make_measure_pdf(b.folder)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "PDF", str(exc)); return
        self.log.appendPlainText(f"Wrote {out}")
        self._on_select()

    def _measure(self) -> None:
        """Saves by itself once all four readings are in and make sense."""
        b = self._current()
        vals = [sp.value() for sp in self.r]
        if b is None or not all(v > 0 for v in vals):
            return
        ok, msg = bb.record_measurement(b.folder, vals[:2], vals[2:])
        colour = "rgb(120,200,120)" if ok else "rgb(229,115,115)"
        self.measure_status.setStyleSheet(f"color: {colour};")
        self.measure_status.setText(msg)
        self.log.appendPlainText(f"{b.name}: {msg}")
        if ok:
            name = Path(b.folder).name
            self._refresh(select=name)
            self.boards_changed.emit()
            self.measure_status.setText(msg)

    # ── 3. test ──────────────────────────────────────────────────────────────
    def _test(self) -> None:
        b = self._current()
        if b is None:
            QMessageBox.information(self, "Test", "Pick a board on the left."); return
        paths, _ = QFileDialog.getOpenFileNames(self, "Photos of the board", "", "Images (*.jpg *.jpeg *.png)")
        if not paths:
            return
        self.status.emit("Testing auto-detect…")
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.log.appendPlainText(bb.test_detect(b.folder, paths))
        except Exception as exc:  # noqa: BLE001
            self.log.appendPlainText(f"Test failed: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        self.status.emit("Test done.")

    def _open_folder(self) -> None:
        b = self._current()
        if b is not None and b.folder:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(b.folder))
