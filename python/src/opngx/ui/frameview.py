"""Pixel-exact frame view for the Qt studio (cycle 23).

v1.7.0 rendered frames by pre-scaling a QPixmap into a QLabel. That had
four user-visible defects, all fixed here:

* the pixmap was scaled once, at the label's size of the moment, so a
  window/splitter resize left a stale, wrongly-sized image until the next
  scrub step;
* a QLabel's size hint is its pixmap, so a large frame propped the layout
  open and the panes could not be shrunk back;
* SmoothTransformation blurred small sensor frames (256x300 upscaled 3x
  became mush) — measurement data must show real pixels;
* devicePixelRatio was ignored, so HiDPI screens got a blurry half-res
  image.

`FrameView` paints the image itself on every paint event: fitted, centred,
integer-scaled with nearest-neighbour when enlarging (every sensor pixel
is an exact square), smooth only when shrinking, and HiDPI-aware. The one
`_target()` rect drives painting AND mouse mapping, so a click lands on
the pixel it visually hits — the v1.7.0 crop canvas mapped mouse positions
as if the image were drawn unscaled at the widget origin.

With ``editable=True`` it is also the crop canvas: drag to draw a
rectangle, drag inside it to move it, drag an edge or corner to resize.
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF, Qt, Signal

from opngx.ui import themes

Rect = tuple[int, int, int, int]


def gray_to_qimage(arr) -> "QtGui.QImage":
    """(h, w) uint8 numpy array -> owned QImage (Grayscale8)."""
    import numpy as np

    a = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = a.shape
    return QtGui.QImage(a.data, w, h, w, QtGui.QImage.Format_Grayscale8).copy()


class FrameView(QtWidgets.QWidget):
    """Fitted, pixel-exact image view with an optional crop overlay."""

    hovered = Signal(int, int)  # image pixel under the cursor, (-1,-1) outside
    zoomChanged = Signal(float)  # effective pixels per image pixel
    selectionChanged = Signal(object)  # live while dragging: (x, y, w, h)
    selectionFinished = Signal(object)  # on release

    _EDGE_TOL = 7.0  # logical px within which an edge/corner is grabbed

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        editable: bool = False,
        placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("viewer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.setMouseTracking(True)
        self._img: Optional[QtGui.QImage] = None
        self._sel: Optional[Rect] = None
        self._editable = editable
        self._placeholder = placeholder
        self._drag: Optional[dict] = None
        self._smooth_down = True
        # analysis overlay (v1.10), image coordinates:
        #   path   — [(x, y), ...] polyline (e.g. a trajectory)
        #   point  — (x, y) marker, circle — (x, y, r)
        self._path = None
        self._point = None
        self._circle = None
        # v2.0 zoom/pan: zoom 1 = fit; the pan offset is in widget pixels
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._panning: Optional[QPointF] = None
        self.grid_enabled = True  # pixel grid when zoomed in far enough
        if editable:
            self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------ public ---
    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(360, 260)

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(120, 90)

    def setImage(self, img: Optional["QtGui.QImage"]) -> None:  # noqa: N802
        img = img if (img is not None and not img.isNull()) else None
        if img is None or self._img is None or img.size() != self._img.size():
            self._zoom, self._pan = 1.0, QPointF(0, 0)  # new geometry: fit
        self._img = img
        self.update()

    def image(self) -> Optional["QtGui.QImage"]:
        return self._img

    def setPlaceholder(self, text: str) -> None:  # noqa: N802
        self._placeholder = text
        self.update()

    def setSelection(self, sel: Optional[Rect]) -> None:  # noqa: N802
        self._sel = tuple(int(v) for v in sel) if sel else None  # type: ignore[assignment]
        self.update()

    def selection(self) -> Optional[Rect]:
        return self._sel

    def setMarkers(self, *, path=None, point=None, circle=None) -> None:  # noqa: N802
        """Overlay in IMAGE pixel coordinates (pixel centres at integers).
        `path` may be an (n, 2) array; NaN rows break the line."""
        self._path = None if path is None else path
        self._point = point
        self._circle = circle
        self.update()

    def clearMarkers(self) -> None:  # noqa: N802
        self.setMarkers()

    # ---------------------------------------------------------- geometry ---
    def _target(self) -> tuple[QRectF, float]:
        """Where the image is drawn (logical px) and its scale factor.

        Enlarging snaps to an integer number of DEVICE pixels per sensor
        pixel so no pixel is drawn wider than its neighbour."""
        if self._img is None:
            return QRectF(), 1.0
        iw, ih = self._img.width(), self._img.height()
        aw = max(1.0, self.width() - 8.0)
        ah = max(1.0, self.height() - 8.0)
        s = min(aw / iw, ah / ih) * self._zoom
        dpr = max(1.0, float(self.devicePixelRatioF()))
        if s * dpr >= 1.0:
            s = math.floor(s * dpr) / dpr
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2.0 + self._pan.x(), (self.height() - h) / 2.0 + self._pan.y(), w, h), s

    # ------------------------------------------------------------ zoom ----
    def zoom_factor(self) -> float:
        return self._target()[1] if self._img is not None else 1.0

    def set_zoom(self, zoom: float, anchor: Optional[QPointF] = None) -> None:
        """Zoom (1 = fit) keeping the image point under `anchor` fixed."""
        if self._img is None:
            return
        zoom = max(1.0, min(64.0, float(zoom)))
        anchor = anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
        t0, s0 = self._target()
        ix = (anchor.x() - t0.x()) / s0
        iy = (anchor.y() - t0.y()) / s0
        self._zoom = zoom
        if zoom == 1.0:
            self._pan = QPointF(0, 0)
        else:
            t1, s1 = self._target()
            self._pan += QPointF(anchor.x() - (t1.x() + ix * s1), anchor.y() - (t1.y() + iy * s1))
        self.update()
        self.zoomChanged.emit(self.zoom_factor())

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self.update()
        self.zoomChanged.emit(self.zoom_factor())

    def center_on(self, x: float, y: float) -> None:
        """Pan so image pixel (x, y) is at the widget centre."""
        if self._img is None:
            return
        t, s = self._target()
        cx, cy = t.x() + (x + 0.5) * s, t.y() + (y + 0.5) * s
        self._pan += QPointF(self.width() / 2 - cx, self.height() / 2 - cy)
        self.update()

    def wheelEvent(self, ev) -> None:  # noqa: N802
        if self._img is None:
            return super().wheelEvent(ev)
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        self.set_zoom(self._zoom * (1.25 ** steps), ev.position())
        ev.accept()

    def _to_image(self, pos: QPointF, clamp: bool = True) -> tuple[int, int]:
        t, s = self._target()
        if self._img is None or s <= 0:
            return (-1, -1)
        x = math.floor((pos.x() - t.x()) / s)
        y = math.floor((pos.y() - t.y()) / s)
        if clamp:
            x = max(0, min(x, self._img.width() - 1))
            y = max(0, min(y, self._img.height() - 1))
        return (x, y)

    def _sel_rect(self) -> Optional[QRectF]:
        if self._sel is None:
            return None
        t, s = self._target()
        x, y, w, h = self._sel
        return QRectF(t.x() + x * s, t.y() + y * s, w * s, h * s)

    def _hit(self, pos: QPointF) -> str:
        """'' outside the selection, 'move' inside, else edges like 'lt'."""
        r = self._sel_rect()
        if r is None:
            return ""
        tol = self._EDGE_TOL
        near_l = abs(pos.x() - r.left()) <= tol
        near_r = abs(pos.x() - r.right()) <= tol
        near_t = abs(pos.y() - r.top()) <= tol
        near_b = abs(pos.y() - r.bottom()) <= tol
        in_x = r.left() - tol <= pos.x() <= r.right() + tol
        in_y = r.top() - tol <= pos.y() <= r.bottom() + tol
        edges = ""
        if in_y and near_l:
            edges += "l"
        elif in_y and near_r:
            edges += "r"
        if in_x and near_t:
            edges += "t"
        elif in_x and near_b:
            edges += "b"
        if edges:
            return edges
        if self._img is not None and self._sel == (
            0,
            0,
            self._img.width(),
            self._img.height(),
        ):
            # a full-frame selection cannot move anywhere; treating a press
            # inside it as "move" made it impossible to draw a new region
            # on a fresh editor (the default selection IS the full frame)
            return ""
        return "move" if r.contains(pos) else ""

    # ------------------------------------------------------------ paint ----
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        opt = QtWidgets.QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QtWidgets.QStyle.PE_Widget, opt, p, self)
        if self._img is None:
            if self._placeholder:
                p.setPen(self.palette().color(QtGui.QPalette.PlaceholderText))
                p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self._placeholder)
            p.end()
            return
        t, s = self._target()
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, s < 1.0 and self._smooth_down)
        p.save()
        p.setClipRect(self.rect().adjusted(1, 1, -1, -1))
        p.drawImage(t, self._img)
        if self.grid_enabled and s >= 6:
            # pixel grid when a sensor pixel is >= 6 screen pixels
            pen = QtGui.QPen(QtGui.QColor(128, 128, 128, 70))
            pen.setCosmetic(True)
            p.setPen(pen)
            vis = t.intersected(QRectF(self.rect()))
            x0 = max(0, int((vis.left() - t.left()) / s))
            x1 = min(self._img.width(), int((vis.right() - t.left()) / s) + 1)
            y0 = max(0, int((vis.top() - t.top()) / s))
            y1 = min(self._img.height(), int((vis.bottom() - t.top()) / s) + 1)
            for gx in range(x0, x1 + 1):
                X = t.left() + gx * s
                p.drawLine(QPointF(X, t.top() + y0 * s), QPointF(X, t.top() + y1 * s))
            for gy in range(y0, y1 + 1):
                Y = t.top() + gy * s
                p.drawLine(QPointF(t.left() + x0 * s, Y), QPointF(t.left() + x1 * s, Y))
        self._paint_markers(p, t, s)
        r = self._sel_rect()
        if r is not None:
            # dim OUTSIDE the selection. v1.7.0 filled the whole frame and
            # then "cleared" the hole with a transparent fill — a no-op
            # under SourceOver, so the selection was dimmed like the rest.
            shade = QtGui.QPainterPath()
            shade.addRect(t)
            hole = QtGui.QPainterPath()
            hole.addRect(r)
            p.fillPath(shade.subtracted(hole), QtGui.QColor(0, 0, 0, 140 if themes.is_dark() else 90))
            pen = QtGui.QPen(themes.qcolor("accent_fg"))
            pen.setWidthF(1.5)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            if self._editable:
                p.setBrush(themes.qcolor("accent_fg"))
                for cx, cy in (
                    (r.left(), r.top()),
                    (r.right(), r.top()),
                    (r.left(), r.bottom()),
                    (r.right(), r.bottom()),
                ):
                    p.drawRect(QRectF(cx - 3, cy - 3, 6, 6))
        p.restore()  # the clip set before drawImage
        p.end()

    def _paint_markers(self, p, t, s) -> None:
        if self._path is None and self._point is None and self._circle is None:
            return
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        def m(x, y):  # pixel CENTRE -> widget position
            return QPointF(t.x() + (x + 0.5) * s, t.y() + (y + 0.5) * s)

        if self._path is not None and len(self._path) > 1:
            import numpy as np

            pts = np.asarray(self._path, dtype=float)
            pen = QtGui.QPen(themes.qcolor("trace", 200))
            pen.setWidthF(1.2)
            pen.setCosmetic(True)
            p.setPen(pen)
            poly = QtGui.QPolygonF()
            for x, y in pts:
                if x != x or y != y:  # NaN: lost frame, break the line
                    if poly.size() > 1:
                        p.drawPolyline(poly)
                    poly = QtGui.QPolygonF()
                    continue
                poly.append(m(x, y))
            if poly.size() > 1:
                p.drawPolyline(poly)
        if self._circle is not None:
            x, y, r = self._circle
            if r == r and r > 0 and x == x:
                pen = QtGui.QPen(themes.qcolor("marker"))
                pen.setWidthF(1.5)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(m(x, y), r * s, r * s)
        if self._point is not None:
            x, y = self._point
            if x == x and y == y:
                c = m(x, y)
                pen = QtGui.QPen(themes.qcolor("marker"))
                pen.setWidthF(1.5)
                pen.setCosmetic(True)
                p.setPen(pen)
                arm = max(6.0, 3 * s)
                p.drawLine(QPointF(c.x() - arm, c.y()), QPointF(c.x() + arm, c.y()))
                p.drawLine(QPointF(c.x(), c.y() - arm), QPointF(c.x(), c.y() + arm))
        p.restore()

    # ------------------------------------------------------------ mouse ----
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if self._img is not None and ev.button() in (Qt.MiddleButton, Qt.RightButton):
            self._panning = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if not self._editable or self._img is None or ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)
        pos = ev.position()
        hit = self._hit(pos)
        px = self._to_image(pos)
        self._drag = {"mode": hit or "new", "from": px, "orig": self._sel}
        if not hit:
            self._sel = (px[0], px[1], 1, 1)
            self.selectionChanged.emit(self._sel)
            self.update()

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        if ev.button() in (Qt.MiddleButton, Qt.RightButton):
            self.reset_view()
            return
        super().mouseDoubleClickEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position()
        if self._panning is not None:
            self._pan += pos - self._panning
            self._panning = pos
            self.update()
            return
        hx, hy = self._to_image(pos, clamp=False)
        if self._img is not None and 0 <= hx < self._img.width() and 0 <= hy < self._img.height():
            self.hovered.emit(hx, hy)
        else:
            self.hovered.emit(-1, -1)
        if not self._editable or self._img is None:
            return
        if self._drag is None:
            hit = self._hit(pos)
            shapes = {
                "move": Qt.SizeAllCursor,
                "l": Qt.SizeHorCursor,
                "r": Qt.SizeHorCursor,
                "t": Qt.SizeVerCursor,
                "b": Qt.SizeVerCursor,
                "lt": Qt.SizeFDiagCursor,
                "rb": Qt.SizeFDiagCursor,
                "rt": Qt.SizeBDiagCursor,
                "lb": Qt.SizeBDiagCursor,
            }
            self.setCursor(shapes.get(hit, Qt.CrossCursor))
            return
        W, H = self._img.width(), self._img.height()
        cx, cy = self._to_image(pos)
        d = self._drag
        fx, fy = d["from"]
        mode = d["mode"]
        if mode == "new":
            x0, x1 = sorted((fx, cx))
            y0, y1 = sorted((fy, cy))
            sel = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        elif mode == "move":
            ox, oy, ow, oh = d["orig"]
            nx = max(0, min(ox + cx - fx, W - ow))
            ny = max(0, min(oy + cy - fy, H - oh))
            sel = (nx, ny, ow, oh)
        else:
            ox, oy, ow, oh = d["orig"]
            l, t_, r, b = ox, oy, ox + ow - 1, oy + oh - 1
            if "l" in mode:
                l = min(cx, r)
            if "r" in mode:
                r = max(cx, l)
            if "t" in mode:
                t_ = min(cy, b)
            if "b" in mode:
                b = max(cy, t_)
            sel = (l, t_, r - l + 1, b - t_ + 1)
        if sel != self._sel:
            self._sel = sel
            self.selectionChanged.emit(sel)
            self.update()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if self._panning is not None and ev.button() in (Qt.MiddleButton, Qt.RightButton):
            self._panning = None
            self.setCursor(Qt.CrossCursor if self._editable else Qt.ArrowCursor)
            return
        if self._drag is not None:
            self._drag = None
            if self._sel is not None:
                self.selectionFinished.emit(self._sel)
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self.hovered.emit(-1, -1)
        super().leaveEvent(ev)
