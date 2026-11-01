"""zoom_view.py — an image you can zoom (mouse wheel, at the cursor) and drag around.

Double-click fits the whole image again.  Used for the Old School target overlays.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class ZoomView(QGraphicsView):
    MAX_ZOOM = 12.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setToolTip("Mouse wheel: zoom.  Drag: move.  Double-click: whole image.")
        self._fitted = True

    def set_bgr(self, img: np.ndarray | None) -> None:
        if img is None:
            self._item.setPixmap(QPixmap()); return
        rgb = np.ascontiguousarray(img[:, :, ::-1])
        q = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        keep = not self._fitted and not self._item.pixmap().isNull() \
            and self._item.pixmap().size() == q.size()
        self._item.setPixmap(QPixmap.fromImage(q))
        self._scene.setSceneRect(self._item.boundingRect())
        if not keep:
            self.fit()

    def fit(self) -> None:
        if self._item.pixmap().isNull():
            return
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self._fitted = True

    def zoom_level(self) -> float:
        return self.transform().m11()

    def wheelEvent(self, ev):
        f = 1.25 if ev.angleDelta().y() > 0 else 0.8
        if self.zoom_level() * f > self.MAX_ZOOM:
            return
        self.scale(f, f)
        self._fitted = False
        if self.zoom_level() < 0.05:
            self.fit()

    def mouseDoubleClickEvent(self, ev):
        self.fit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._fitted:
            self.fit()
