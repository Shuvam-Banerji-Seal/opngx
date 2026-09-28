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
        if editable:
            self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------ public ---
    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(360, 260)

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(120, 90)

    def setImage(self, img: Optional["QtGui.QImage"]) -> None:  # noqa: N802
        self._img = img if (img is not None and not img.isNull()) else None
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
        s = min(aw / iw, ah / ih)
        dpr = max(1.0, float(self.devicePixelRatioF()))
        if s * dpr >= 1.0:
            s = math.floor(s * dpr) / dpr
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h), s

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
        p.drawImage(t, self._img)
        r = self._sel_rect()
        if r is not None:
            # dim OUTSIDE the selection. v1.7.0 filled the whole frame and
            # then "cleared" the hole with a transparent fill — a no-op
            # under SourceOver, so the selection was dimmed like the rest.
            shade = QtGui.QPainterPath()
            shade.addRect(t)
            hole = QtGui.QPainterPath()
            hole.addRect(r)
            p.fillPath(shade.subtracted(hole), QtGui.QColor(0, 0, 0, 140))
            pen = QtGui.QPen(QtGui.QColor("#7fb069"))
            pen.setWidthF(1.5)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            if self._editable:
                p.setBrush(QtGui.QColor("#7fb069"))
                for cx, cy in (
                    (r.left(), r.top()),
                    (r.right(), r.top()),
                    (r.left(), r.bottom()),
                    (r.right(), r.bottom()),
                ):
                    p.drawRect(QRectF(cx - 3, cy - 3, 6, 6))
        p.end()

    # ------------------------------------------------------------ mouse ----
    def mousePressEvent(self, ev) -> None:  # noqa: N802
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

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position()
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
        if self._drag is not None:
            self._drag = None
            if self._sel is not None:
                self.selectionFinished.emit(self._sel)
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self.hovered.emit(-1, -1)
        super().leaveEvent(ev)
