"""QGraphicsView 기반 영상 뷰어. 줌/패닝 + 폴리라인 드로잉 + 결과 토글.

폴리라인 overlay 는 두 개 ('clear', 'hazy') — 드로잉 모드에서는 active overlay 에만
정점이 추가된다. set_active_overlay(name) 로 전환.
"""
import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal, QRectF
from PyQt5.QtGui import QPainter, QPixmap, QImage, QColor
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
)

from .polyline_overlay import PolylineOverlay


def _pil_to_qpixmap(pil_img) -> QPixmap:
    """PIL.Image (RGB or RGBA) → QPixmap."""
    img = pil_img.convert('RGBA')
    data = img.tobytes('raw', 'RGBA')
    qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


class ImageViewer(QGraphicsView):
    polyline_changed = pyqtSignal(str, int)   # (name, vertex_count)
    polyline_finished = pyqtSignal()

    MODE_VIEW = 0
    MODE_DRAW = 1

    RESULT_ORI  = 'ori'
    RESULT_DEH  = 'deh'
    RESULT_AERO = 'aero'

    OVERLAY_NAMES = ('clear', 'hazy')

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.black)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        self._mode = self.MODE_VIEW
        self._pixmap_item = None

        # 두 개의 named overlay (다른 색)
        self._overlays = {
            'clear': PolylineOverlay(
                line_color=QColor(0, 255, 0),     # 녹색 라인
                dot_color=QColor(255, 0, 0),       # 빨강 점
            ),
            'hazy': PolylineOverlay(
                line_color=QColor(255, 60, 60),    # 빨강 라인
                dot_color=QColor(255, 220, 0),     # 노랑 점
            ),
        }
        for ov in self._overlays.values():
            self._scene.addItem(ov)
        self._active_overlay = 'clear'

        self._result_pixmaps = {}   # mode str → QPixmap
        self._current_result = None

        self.setFocusPolicy(Qt.StrongFocus)

    # ── mode ───────────────────────────────────────────────────
    def set_mode(self, mode: int):
        self._mode = mode
        if mode == self.MODE_DRAW:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.setCursor(Qt.ArrowCursor)

    def current_mode(self) -> int:
        return self._mode

    def set_active_overlay(self, name: str):
        if name not in self._overlays:
            raise ValueError(f'unknown overlay: {name!r}')
        self._active_overlay = name

    def active_overlay_name(self) -> str:
        return self._active_overlay

    # ── 입력 영상 로드 ─────────────────────────────────────────
    def load_full_image(self, pil_img):
        """원본 해상도 PIL → QPixmap. 기존 폴리라인 모두 클리어."""
        for name, ov in self._overlays.items():
            ov.clear_all()
            self.polyline_changed.emit(name, 0)
        self._result_pixmaps.clear()
        self._current_result = None

        pixmap = _pil_to_qpixmap(pil_img)
        if self._pixmap_item is not None:
            self._scene.removeItem(self._pixmap_item)
        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._pixmap_item.setZValue(0)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    # ── 결과 표시 ──────────────────────────────────────────────
    def load_result_images(self, ori, deh, aero):
        self._result_pixmaps = {
            self.RESULT_ORI:  _pil_to_qpixmap(ori)  if ori  is not None else None,
            self.RESULT_DEH:  _pil_to_qpixmap(deh)  if deh  is not None else None,
            self.RESULT_AERO: _pil_to_qpixmap(aero) if aero is not None else None,
        }
        self.show_result(self.RESULT_DEH)

    def show_result(self, key: str):
        if key not in self._result_pixmaps or self._result_pixmaps[key] is None:
            return
        if self._pixmap_item is not None:
            self._scene.removeItem(self._pixmap_item)
        self._pixmap_item = QGraphicsPixmapItem(self._result_pixmaps[key])
        self._pixmap_item.setZValue(0)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(QRectF(self._pixmap_item.pixmap().rect()))
        self._current_result = key

    # ── polyline accessor ──────────────────────────────────────
    def get_vertices(self, name: str = 'clear'):
        if name not in self._overlays:
            return []
        return self._overlays[name].vertices_int()

    def vertex_count(self, name: str = 'clear') -> int:
        if name not in self._overlays:
            return 0
        return self._overlays[name].vertex_count()

    def clear_polyline(self, name: str = 'all'):
        targets = self.OVERLAY_NAMES if name == 'all' else (name,)
        for n in targets:
            if n in self._overlays:
                self._overlays[n].clear_all()
                self.polyline_changed.emit(n, 0)

    # ── 이벤트 ─────────────────────────────────────────────────
    def _active(self) -> PolylineOverlay:
        return self._overlays[self._active_overlay]

    def mousePressEvent(self, ev):
        if self._mode == self.MODE_DRAW and self._pixmap_item is not None:
            scene_pos = self.mapToScene(ev.pos())
            x, y = scene_pos.x(), scene_pos.y()
            rect = self._scene.sceneRect()
            if not (0 <= x <= rect.width() and 0 <= y <= rect.height()):
                return  # 영상 밖 클릭 무시
            ov = self._active()
            if ev.button() == Qt.LeftButton:
                ov.add_vertex(x, y)
                self.polyline_changed.emit(self._active_overlay, ov.vertex_count())
                return
            if ev.button() == Qt.RightButton:
                if ov.vertex_count() >= 2:
                    self.polyline_finished.emit()
                return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if self._mode == self.MODE_DRAW and self._active().vertex_count() >= 2:
            self.polyline_finished.emit()
            return
        super().mouseDoubleClickEvent(ev)

    def keyPressEvent(self, ev):
        if self._mode == self.MODE_DRAW:
            ov = self._active()
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                if ov.vertex_count() >= 2:
                    self.polyline_finished.emit()
                return
            if ev.key() == Qt.Key_Backspace:
                ov.remove_last_vertex()
                self.polyline_changed.emit(self._active_overlay, ov.vertex_count())
                return
            if ev.key() == Qt.Key_Escape:
                ov.clear_all()
                self.polyline_changed.emit(self._active_overlay, 0)
                return
        super().keyPressEvent(ev)

    def wheelEvent(self, ev):
        # Ctrl+휠 = 줌, 일반 휠 = 스크롤
        if ev.modifiers() & Qt.ControlModifier:
            factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
            self.scale(factor, factor)
        else:
            super().wheelEvent(ev)

    # ── 줌 헬퍼 ────────────────────────────────────────────────
    def zoom_in(self):
        self.scale(1.25, 1.25)

    def zoom_out(self):
        self.scale(0.8, 0.8)

    def zoom_fit(self):
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def zoom_actual(self):
        self.resetTransform()
