"""전후 비교 슬라이드 창.

수직 디바이더를 좌/우로 드래그해서 왼쪽=원본, 오른쪽=Dehazing 노출 비율을 조절.
Ctrl+휠 줌 + 좌클릭 드래그 패닝 (디바이더에서 떨어진 위치).
"""
from PyQt5.QtCore import Qt, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsLineItem,
)

from .image_viewer import _pil_to_qpixmap


class _ClippedPixmapItem(QGraphicsPixmapItem):
    """clip_x 이상의 x 영역만 그리는 pixmap item."""

    def __init__(self, pixmap):
        super().__init__(pixmap)
        self.clip_x = 0.0

    def paint(self, painter, option, widget=None):
        pm = self.pixmap()
        if pm.isNull():
            return
        w = pm.width()
        h = pm.height()
        x = max(0.0, min(self.clip_x, float(w)))
        if x >= w:
            return
        painter.save()
        painter.setClipRect(QRectF(x, 0.0, w - x, h))
        super().paint(painter, option, widget)
        painter.restore()


class CompareView(QGraphicsView):
    divider_changed = pyqtSignal(float)   # 0..1 ratio
    zoom_changed    = pyqtSignal(float)   # current scale (1.0 = 100%)

    DRAG_TOL_PX = 8

    def __init__(self, before_pixmap, after_pixmap, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.black)
        self.setDragMode(QGraphicsView.NoDrag)   # 수동 패닝
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # items
        self._before_item = QGraphicsPixmapItem(before_pixmap)
        self._before_item.setZValue(0)
        self._scene.addItem(self._before_item)

        self._after_item = _ClippedPixmapItem(after_pixmap)
        self._after_item.setZValue(1)
        self._scene.addItem(self._after_item)

        w = max(before_pixmap.width(), after_pixmap.width())
        h = max(before_pixmap.height(), after_pixmap.height())
        self._scene_w = float(w)
        self._scene_h = float(h)
        self._scene.setSceneRect(QRectF(0, 0, w, h))

        pen = QPen(QColor(255, 220, 0))
        pen.setWidth(2)
        pen.setCosmetic(True)   # 줌과 무관하게 일정한 두께
        self._divider_line = QGraphicsLineItem()
        self._divider_line.setPen(pen)
        self._divider_line.setZValue(10)
        self._scene.addItem(self._divider_line)

        # state
        self._divider_x = self._scene_w / 2.0
        self._dragging_divider = False
        self._panning = False
        self._pan_anchor = None
        self._set_divider_x(self._divider_x)

        # 초기 fit
        self.fitInView(self._before_item, Qt.KeepAspectRatio)

    # ── divider ────────────────────────────────────────────────
    def _set_divider_x(self, x: float):
        x = max(0.0, min(self._scene_w, float(x)))
        self._divider_x = x
        self._after_item.clip_x = x
        self._after_item.update()
        self._divider_line.setLine(x, 0.0, x, self._scene_h)
        ratio = (x / self._scene_w) if self._scene_w > 0 else 0.0
        self.divider_changed.emit(ratio)

    def reset_divider(self):
        self._set_divider_x(self._scene_w / 2.0)

    def _near_divider(self, view_pos) -> bool:
        scene_x = self.mapToScene(view_pos).x()
        # tolerance 를 viewport(px) 기준으로 환산: scene 거리 / scale
        scale = self.transform().m11() or 1.0
        return abs(scene_x - self._divider_x) * scale <= self.DRAG_TOL_PX

    # ── 줌 ─────────────────────────────────────────────────────
    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier:
            factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
            self.scale(factor, factor)
            self.zoom_changed.emit(self.transform().m11())
        else:
            super().wheelEvent(ev)

    def zoom_fit(self):
        self.fitInView(self._before_item, Qt.KeepAspectRatio)
        self.zoom_changed.emit(self.transform().m11())

    def zoom_actual(self):
        self.resetTransform()
        self.zoom_changed.emit(self.transform().m11())

    # ── 마우스 ─────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            if self._near_divider(ev.pos()):
                self._dragging_divider = True
                self.setCursor(Qt.SizeHorCursor)
                ev.accept()
                return
            # 패닝
            self._panning = True
            self._pan_anchor = ev.pos()
            self.setCursor(Qt.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._dragging_divider:
            scene_x = self.mapToScene(ev.pos()).x()
            self._set_divider_x(scene_x)
            ev.accept()
            return
        if self._panning and self._pan_anchor is not None:
            delta = ev.pos() - self._pan_anchor
            self._pan_anchor = ev.pos()
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            vbar.setValue(vbar.value() - delta.y())
            ev.accept()
            return
        # hover: 디바이더 근처면 ↔ 커서
        if self._near_divider(ev.pos()):
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.OpenHandCursor)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging_divider = False
            self._panning = False
            self._pan_anchor = None
            self.setCursor(Qt.OpenHandCursor if not self._near_divider(ev.pos())
                           else Qt.SizeHorCursor)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # fit 유지 안 함 (사용자 줌 상태 보존). 처음 한 번만 fit 됨.


class CompareDialog(QDialog):
    def __init__(self, before_pil, after_pil, parent=None):
        super().__init__(parent)
        self.setWindowTitle('전후 비교 — 원본 / Dehazing')
        self.resize(1100, 800)

        before_pm = _pil_to_qpixmap(before_pil)
        after_pm  = _pil_to_qpixmap(after_pil)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # 상단 툴바
        bar = QHBoxLayout()
        self.btn_fit    = QPushButton('Fit')
        self.btn_actual = QPushButton('1:1')
        self.btn_center = QPushButton('디바이더 중앙')
        bar.addWidget(self.btn_fit)
        bar.addWidget(self.btn_actual)
        bar.addWidget(self.btn_center)
        bar.addStretch(1)
        root.addLayout(bar)

        # 뷰
        self.view = CompareView(before_pm, after_pm, self)
        root.addWidget(self.view, 1)

        # 하단 상태 라벨
        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet('color:#444;')
        root.addWidget(self.lbl_status)

        # 연결
        self.btn_fit.clicked.connect(self.view.zoom_fit)
        self.btn_actual.clicked.connect(self.view.zoom_actual)
        self.btn_center.clicked.connect(self.view.reset_divider)
        self.view.divider_changed.connect(self._on_divider_changed)
        self.view.zoom_changed.connect(self._on_zoom_changed)

        # 초기 상태
        self._divider_ratio = 0.5
        self._zoom = 1.0
        self._refresh_status()

    def _on_divider_changed(self, ratio: float):
        self._divider_ratio = ratio
        self._refresh_status()

    def _on_zoom_changed(self, scale: float):
        self._zoom = scale
        self._refresh_status()

    def _refresh_status(self):
        self.lbl_status.setText(
            f'왼쪽: 원본  |  오른쪽: Dehazing  '
            f'|  줌 {self._zoom*100:.0f}%  '
            f'|  디바이더 {self._divider_ratio*100:.0f}%'
        )
