"""annotation_viewer.py - pop-up window: a photo with what the app found drawn on it.

Reads only the files left beside the photos (see src/viewer/__init__.py); imports
nothing from the rest of the app, so it can be changed or lifted out on its own.

  Lens photos   (<photo>.dots.json)    every dot: number, green/amber/red by its fit,
                                       grey when there is no fit; why a photo was not used
  Old School    (<photo>.targets.json) green = used (id, miss mm), red = found but dropped
                                       (why), orange = should be in view but not found,
                                       a dashed ring = found by the second look
Wheel = zoom, drag = move, double-click = whole picture.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

DOTS, TARGETS = ".dots.json", ".targets.json"
GREEN, AMBER, RED, ORANGE, GREY, WHITE = (QColor(60, 200, 60), QColor(230, 180, 40), QColor(255, 80, 80),
                                          QColor(255, 150, 40), QColor(150, 150, 150), QColor(255, 255, 255))
MAX_DEPTH = 3                       # folder, setup folder, NotUsed


# ── reading the files ────────────────────────────────────────────────────────

def find_annotations(folder: str) -> list[Path]:
    """Every .dots.json / .targets.json in the folder and up to MAX_DEPTH levels below."""
    root = Path(folder)
    out = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        out += [Path(dirpath) / f for f in filenames if f.endswith((DOTS, TARGETS))]
    return sorted(out, key=lambda p: (str(p.parent).lower(), p.name.lower()))


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def photo_of(path: Path, doc: dict) -> Path:
    return path.with_name(doc.get("photo") or "")


def status_of(path: Path, doc: dict) -> tuple[str, QColor]:
    """Short status for the list, and its colour."""
    if path.name.endswith(TARGETS):
        return ("used" if doc.get("used") else "not used"), (GREEN if doc.get("used") else RED)
    s = doc.get("status", "")
    return s, (GREEN if s == "used" else (AMBER if "left out" in s else RED))


def run_logs(folder: str) -> list[dict]:
    return [d for d in (load(p) for p in sorted(Path(folder).glob("RUN_*.json"))) if d] if Path(folder).is_dir() else []


# ── drawing ──────────────────────────────────────────────────────────────────

def _fit_colour(fit, sc):
    if fit is None:
        return GREY
    return GREEN if fit <= 1.5 * sc else (AMBER if fit <= 3.0 * sc else RED)


def draw(pix: QPixmap, path: Path, doc: dict, numbers: bool = True) -> QPixmap:
    """A copy of the photo with the annotations drawn on it."""
    out = QPixmap(pix)
    sc = max(out.width() / 1920.0, 0.5)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont("Arial"); f.setPixelSize(int(13 * sc)); f.setBold(True); p.setFont(f)
    r = 9 * sc

    def ring(x, y, col, rad=r, dashed=False, width=2.0):
        pen = QPen(col, width * sc); pen.setStyle(Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(QPointF(x, y), rad, rad)

    def label(x, y, text, col):
        fm = p.fontMetrics(); w, h = fm.horizontalAdvance(text) + 6, fm.height() + 2
        box = QRectF(x, y - h, w, h)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(20, 20, 20, 200))); p.drawRect(box)
        p.setPen(QPen(col)); p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    if path.name.endswith(DOTS):
        for d in doc.get("dots", []):
            x, y, col = d["x_px"], d["y_px"], _fit_colour(d.get("fit_px"), sc)
            ring(x, y, col)
            if numbers:
                fit = d.get("fit_px")
                label(x + r * 1.2, y - r * 0.4, f"{d['n']}" + ("" if fit is None else f"  {fit:.1f}"), col)
    else:
        for t in doc.get("targets", []):
            if t.get("found"):
                x, y = t["x_px"], t["y_px"]
                if t.get("used"):
                    ring(x, y, GREEN, r * 1.6, width=2.5)
                    txt, col = f"{t['id']}  {t['miss_mm']:.0f} mm" if t.get("miss_mm") is not None else t["id"], GREEN
                else:
                    p.setPen(QPen(RED, 2.5 * sc))
                    p.drawLine(QPointF(x - r, y - r), QPointF(x + r, y + r)); p.drawLine(QPointF(x - r, y + r), QPointF(x + r, y - r))
                    why = (t.get("dropped_why") or "not used").split(":")[0]
                    txt, col = f"{t['id']} {why}", RED
                if t.get("found_by") == "second look":
                    ring(x, y, WHITE, r * 2.3, dashed=True, width=1.5)
                if numbers:
                    label(x + r * 2.4, y - r * 0.4, txt, col)
            elif t.get("predicted_x_px") is not None:
                x, y = t["predicted_x_px"], t["predicted_y_px"]
                ring(x, y, ORANGE, r * 1.2)
                if numbers:
                    label(x + r * 1.6, y - r * 0.4, f"{t['id']} not found", ORANGE)
    p.end()
    return out


def describe(path: Path, doc: dict) -> str:
    """The text beside the picture."""
    L = [f"{doc.get('photo', '')}    ({path.name})"]
    if doc.get("run_id"):
        L.append(f"Run: {doc['run_id']}    app {doc.get('app_version', '?')}")
    if path.name.endswith(DOTS):
        L.append(f"Status: {doc.get('status', '')}" + (f"  -  {doc['why']}" if doc.get("why") else ""))
        L.append(f"Dots found: {doc.get('dots_found')}    fit RMS: {doc.get('fit_rms_px')} px    "
                 f"edge blur: {doc.get('edge_blur_px')} px    size: {doc.get('image_size')}")
        if doc.get("in_NotUsed_folder"):
            L.append("This photo was moved to NotUsed.")
        L.append("Colours: green fit <= 1.5 px, amber <= 3 px, red more (x2 on 4K); grey = no fit.  "
                 "Number = dot on the board, then its fit in px.")
    else:
        L.append(f"Van {doc.get('van')}  {doc.get('camera')}   setup {doc.get('setup')}   "
                 f"{'USED' if doc.get('used') else 'NOT USED'}")
        for pr in doc.get("problems", []):
            L.append(f"  - {pr}")
        s = doc.get("solve") or {}
        if s:
            L.append(f"Targets used {s.get('targets_used')}, miss {s.get('miss_rms_mm')} mm RMS at "
                     f"{s.get('range_mean_m')} m; pan/tilt/roll {s.get('pan_tilt_roll_deg')}; "
                     f"up {s.get('up_above_pavement_m')} m above the pavement")
        L.append(f"In view {doc.get('targets_in_view')}, found {doc.get('targets_found')}, "
                 f"tennis balls used {doc.get('tennis_balls_used')}")
        v = doc.get("van_pose") or {}
        if v:
            L.append(f"Van pose ({v.get('csv')}): heading {v.get('heading_true_deg')}, pitch {v.get('pitch_deg')}, "
                     f"roll {v.get('roll_deg')}, GPS {v.get('gps_status')}, moved {v.get('moved_while_parked_deg')} deg")
        L.append("Green = used (miss mm), red = found but dropped (why), orange = should be in view, "
                 "not found; dashed ring = found by the second look.")
    return "\n".join(L)


# ── the window ───────────────────────────────────────────────────────────────

class _Zoom(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self._item = QGraphicsPixmapItem(); self.scene().addItem(self._item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(25, 25, 25))

    def show_pixmap(self, pix: QPixmap):
        self._item.setPixmap(pix); self.scene().setSceneRect(QRectF(pix.rect())); self.fit()

    def fit(self):
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):
        k = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(k, k)

    def mouseDoubleClickEvent(self, e):
        self.fit()


class AnnotationViewer(QWidget):
    """Pop-up window.  AnnotationViewer(folder).show(), or open_viewer(folder)."""

    def __init__(self, folder: str = "", photo: str = "", parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Photo check - what the app found")
        self.resize(1300, 820)
        self._files: list[Path] = []
        self._pix: QPixmap | None = None
        self._cur: tuple[Path, dict] | None = None

        self.folder = QLineEdit(folder); self.folder.setPlaceholderText("A photo folder or an Old School camera folder")
        browse = QPushButton("Folder..."); reload_ = QPushButton("Reload")
        self.filter = QComboBox(); self.filter.addItems(["All photos", "Used", "Not used"])
        self.numbers = QCheckBox("Numbers"); self.numbers.setChecked(True)
        self.runs = QLabel(""); self.runs.setWordWrap(True); self.runs.setStyleSheet("color: rgb(170,170,170);")
        self.list = QListWidget(); self.list.setMinimumWidth(260)
        self.view = _Zoom()
        self.info = QPlainTextEdit(); self.info.setReadOnly(True); self.info.setMaximumHeight(150)

        top = QHBoxLayout()
        top.addWidget(QLabel("Folder:")); top.addWidget(self.folder, 1); top.addWidget(browse); top.addWidget(reload_)
        top.addWidget(self.filter); top.addWidget(self.numbers)
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Wheel = zoom, drag = move, double-click = whole picture")); rl.addWidget(self.view, 1)
        rl.addWidget(self.info)
        split = QSplitter(); split.addWidget(self.list); split.addWidget(right); split.setSizes([300, 1000])
        lay = QVBoxLayout(self); lay.addLayout(top); lay.addWidget(self.runs); lay.addWidget(split, 1)

        browse.clicked.connect(self._browse)
        reload_.clicked.connect(self.reload)
        self.folder.returnPressed.connect(self.reload)
        self.filter.currentIndexChanged.connect(self._fill)
        self.numbers.toggled.connect(self._redraw)
        self.list.currentRowChanged.connect(self._show)
        if folder:
            self.reload(select=photo)

    # folder
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Folder to check", self.folder.text())
        if d:
            self.folder.setText(d); self.reload()

    def reload(self, select: str = ""):
        folder = self.folder.text().strip()
        self._files = find_annotations(folder)
        logs = run_logs(folder)
        if logs:
            last = logs[-1]
            g = ((last.get("result") or {}).get("grade") or {})
            self.runs.setText(f"{len(logs)} run log(s).  Last: {last.get('run_id')}  on {last.get('pc', {}).get('computer')}"
                              f"  -  {g.get('headline') or last.get('error') or ''}"
                              + ("  -  saved" if last.get("saved") else "  -  not saved"))
        else:
            self.runs.setText("" if self._files else "No .dots.json or .targets.json files here: run the folder in the app first.")
        self._fill(select=select)

    def _fill(self, *_a, select: str = ""):
        self.list.blockSignals(True); self.list.clear()
        want = self.filter.currentText()
        root = Path(self.folder.text().strip())
        row_sel = 0
        for p in self._files:
            doc = load(p)
            st, col = status_of(p, doc)
            if (want == "Used" and st != "used") or (want == "Not used" and st == "used"):
                continue
            rel = p.parent.relative_to(root) if p.parent != root else Path("")
            name = str(rel / (doc.get("photo") or p.name))
            it = QListWidgetItem(f"{'✓' if st == 'used' else '✗'} {name}   {st}")
            it.setForeground(QBrush(col)); it.setData(Qt.ItemDataRole.UserRole, str(p))
            self.list.addItem(it)
            if select and doc.get("photo") == os.path.basename(select):
                row_sel = self.list.count() - 1
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(row_sel); self._show(row_sel)

    # picture
    def _show(self, row: int):
        it = self.list.item(row) if row >= 0 else None
        if it is None:
            return
        p = Path(it.data(Qt.ItemDataRole.UserRole))
        doc = load(p)
        self._cur = (p, doc)
        ph = photo_of(p, doc)
        self._pix = QPixmap(str(ph)) if ph.is_file() else None
        self.info.setPlainText(describe(p, doc) + ("" if self._pix and not self._pix.isNull()
                                                   else f"\n\nPhoto not found: {ph}"))
        self._redraw()

    def _redraw(self, *_a):
        if self._cur is None or self._pix is None or self._pix.isNull():
            self.view.show_pixmap(QPixmap(16, 16)); return
        self.view.show_pixmap(draw(self._pix, *self._cur, numbers=self.numbers.isChecked()))


_open: list = []                      # keep pop-ups alive while they are open


def open_viewer(folder: str, photo: str = "", parent=None) -> AnnotationViewer:
    """Open (or re-use) the pop-up for a folder; returns the window."""
    w = AnnotationViewer(folder, photo, parent)
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    w.destroyed.connect(lambda *_: _open.remove(w) if w in _open else None)
    _open.append(w)
    w.show(); w.raise_(); w.activateWindow()
    return w
