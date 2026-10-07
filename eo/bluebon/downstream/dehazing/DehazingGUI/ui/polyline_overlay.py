"""QGraphicsScene에 추가되는 폴리라인 시각화/편집 그룹."""
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPen, QBrush, QColor
from PyQt5.QtWidgets import (
    QGraphicsItemGroup, QGraphicsLineItem, QGraphicsEllipseItem,
)


class PolylineOverlay(QGraphicsItemGroup):
    LINE_COLOR = QColor(0, 255, 0)
    DOT_COLOR  = QColor(255, 0, 0)
    DOT_RADIUS = 4
    LINE_WIDTH = 2

    def __init__(self, parent=None, line_color=None, dot_color=None):
        super().__init__(parent)
        self.line_color = line_color if line_color is not None else self.LINE_COLOR
        self.dot_color  = dot_color  if dot_color  is not None else self.DOT_COLOR
        self._vertices = []          # list[QPointF]
        self._dot_items = []         # list[QGraphicsEllipseItem]
        self._line_items = []        # list[QGraphicsLineItem]
        self.setZValue(100)          # 항상 위에

    # ── public API ─────────────────────────────────────────────
    def add_vertex(self, x: float, y: float):
        pt = QPointF(x, y)
        self._vertices.append(pt)

        dot = QGraphicsEllipseItem(
            x - self.DOT_RADIUS, y - self.DOT_RADIUS,
            self.DOT_RADIUS * 2, self.DOT_RADIUS * 2,
        )
        dot.setBrush(QBrush(self.dot_color))
        dot.setPen(QPen(Qt.black, 1))
        self.addToGroup(dot)
        self._dot_items.append(dot)

        if len(self._vertices) >= 2:
            p_prev = self._vertices[-2]
            line = QGraphicsLineItem(p_prev.x(), p_prev.y(), x, y)
            pen = QPen(self.line_color, self.LINE_WIDTH)
            pen.setCosmetic(True)  # 줌해도 두께 유지
            line.setPen(pen)
            self.addToGroup(line)
            self._line_items.append(line)

    def remove_last_vertex(self):
        if not self._vertices:
            return
        self._vertices.pop()
        if self._dot_items:
            self.removeFromGroup(self._dot_items[-1])
            scene = self.scene()
            if scene is not None:
                scene.removeItem(self._dot_items[-1])
            self._dot_items.pop()
        if self._line_items:
            self.removeFromGroup(self._line_items[-1])
            scene = self.scene()
            if scene is not None:
                scene.removeItem(self._line_items[-1])
            self._line_items.pop()

    def clear_all(self):
        scene = self.scene()
        for it in self._dot_items + self._line_items:
            self.removeFromGroup(it)
            if scene is not None:
                scene.removeItem(it)
        self._dot_items.clear()
        self._line_items.clear()
        self._vertices.clear()

    def vertex_count(self) -> int:
        return len(self._vertices)

    def vertices_int(self) -> list:
        """영상 정수 픽셀 좌표 (x, y)."""
        return [(int(round(p.x())), int(round(p.y()))) for p in self._vertices]
