"""Studio views for analysis modules (v1.10).

* `AnalyzeView`  — pick modules (switch them in and out), set their
  parameters, run them on the loaded recording or on every recording of a
  batch folder, and inspect the result: the frame with the tracked
  position / trajectory drawn on it, a plot (vs time or x–y trajectory),
  the data table and the summary; export the data file.
* `ModuleEditor` — write your own module in Python: templates, syntax
  highlighting, validate (load + dry run on synthetic frames), test on the
  loaded recording, save into the modules folder and reload.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from typing import Any, Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF, Qt, Signal

import opngx
import opngx.analysis as oa
from opngx.ui import scaling
from opngx.ui.frameview import FrameView, gray_to_qimage

SERIES_COLORS = ("#7fb069", "#60a5fa", "#fbbf24", "#f472b6", "#a78bfa", "#34d399")


# =========================================================================
#  plotting
# =========================================================================
def _nice_ticks(lo: float, hi: float, n: int = 6) -> list[float]:
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return [lo] if math.isfinite(lo) else []
    raw = (hi - lo) / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    first = math.ceil(lo / step) * step
    out, v = [], first
    while v <= hi + step * 1e-9 and len(out) < 50:
        out.append(round(v, 12))
        v += step
    return out


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e5 or a < 1e-3:
        return f"{v:.2e}"
    return f"{v:.4g}"


class PlotView(QtWidgets.QWidget):
    """Lightweight line / x-y plot. Decimates to the pixel width (min/max
    envelope), so 50 000-sample series draw instantly."""

    rowClicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setMinimumSize(200, 140)
        self.x = None
        self.series: list[tuple[str, np.ndarray, str]] = []
        self.xlabel = ""
        self.ylabel = ""
        self.mode = "line"  # or "xy"
        self.cursor: Optional[int] = None
        self._hover: Optional[int] = None
        self._geom = None
        self.placeholder = "run a module to see its data"

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(420, 260)

    def set_line(self, x, series, xlabel="", ylabel="") -> None:
        self.mode = "line"
        self.x = None if x is None else np.asarray(x, dtype=float)
        self.series = [(lab, np.asarray(y, dtype=float), col) for lab, y, col in series]
        self.xlabel, self.ylabel = xlabel, ylabel
        self.update()

    def set_xy(self, x, y, label="trajectory", xlabel="x [px]", ylabel="y [px]") -> None:
        self.mode = "xy"
        self.x = np.asarray(x, dtype=float)
        self.series = [(label, np.asarray(y, dtype=float), SERIES_COLORS[0])]
        self.xlabel, self.ylabel = xlabel, ylabel
        self.update()

    def clear(self) -> None:
        self.x, self.series = None, []
        self.update()

    def set_cursor(self, row: Optional[int]) -> None:
        self.cursor = row
        self.update()

    # ------------------------------------------------------------------
    @staticmethod
    def _yrange(ys):
        fin = [y for y in ys if np.isfinite(y).any()]
        if not fin:
            return 0.0, 1.0
        with np.errstate(all="ignore"):
            lo = float(min(np.nanmin(y) for y in fin))
            hi = float(max(np.nanmax(y) for y in fin))
        if hi <= lo:
            pad = abs(lo) * 0.05 or 0.5
            return lo - pad, hi + pad
        pad = (hi - lo) * 0.05
        return lo - pad, hi + pad

    def _ranges(self):
        ys = [y for _l, y, _c in self.series]
        if self.x is None or not ys:
            return None
        with np.errstate(all="ignore"):
            xlo, xhi = np.nanmin(self.x), np.nanmax(self.x)
            ylo = min(np.nanmin(y) for y in ys if np.isfinite(y).any()) if any(np.isfinite(y).any() for y in ys) else 0.0
            yhi = max(np.nanmax(y) for y in ys if np.isfinite(y).any()) if any(np.isfinite(y).any() for y in ys) else 1.0
        if not math.isfinite(xlo):
            return None
        if xhi <= xlo:
            xhi = xlo + 1
        if yhi <= ylo:
            pad = abs(ylo) * 0.05 or 0.5
            ylo, yhi = ylo - pad, yhi + pad
        else:
            pad = (yhi - ylo) * 0.05
            ylo, yhi = ylo - pad, yhi + pad
        if self.mode == "xy":
            xpad = (xhi - xlo) * 0.05 or 0.5
            xlo, xhi = xlo - xpad, xhi + xpad
        return float(xlo), float(xhi), float(ylo), float(yhi)

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#070807"))
        # two series in "vs time" mode get independent axes (left/right):
        # x ~145 px and y ~62 px on one axis are two flat lines, and the
        # sub-pixel motion that matters is invisible
        dual = self.mode == "line" and len(self.series) == 2
        pal_text = QtGui.QColor("#9ab294")
        grid = QtGui.QColor("#1b221b")
        r = self._ranges()
        fm = p.fontMetrics()
        if r is None:
            p.setPen(QtGui.QColor("#5d6b5d"))
            p.drawText(self.rect(), Qt.AlignCenter, self.placeholder)
            p.end()
            return
        xlo, xhi, ylo, yhi = r
        left = fm.horizontalAdvance("-0000.00") + 14
        bottom = fm.height() * 2 + 8
        top = fm.height() + 6
        right = (fm.horizontalAdvance("-0000.00") + 14) if dual else 12
        if dual:
            ylo, yhi = self._yrange([self.series[0][1]])
            y2lo, y2hi = self._yrange([self.series[1][1]])
        area = QRectF(left, top, max(10, self.width() - left - right), max(10, self.height() - top - bottom))
        if self.mode == "xy":
            # equal aspect: 1 px in x == 1 px in y (a trajectory must not be squashed)
            sx = area.width() / (xhi - xlo)
            sy = area.height() / (yhi - ylo)
            s = min(sx, sy)
            cxr, cyr = (xlo + xhi) / 2, (ylo + yhi) / 2
            xlo, xhi = cxr - area.width() / s / 2, cxr + area.width() / s / 2
            ylo, yhi = cyr - area.height() / s / 2, cyr + area.height() / s / 2
        self._geom = (area, xlo, xhi, ylo, yhi)

        def X(v):
            return area.left() + (v - xlo) / (xhi - xlo) * area.width()

        def Y(v):
            if self.mode == "xy":  # image convention: y grows downward
                return area.top() + (v - ylo) / (yhi - ylo) * area.height()
            return area.bottom() - (v - ylo) / (yhi - ylo) * area.height()

        def Y2(v):
            return area.bottom() - (v - y2lo) / (y2hi - y2lo) * area.height()

        p.setPen(grid)
        for t in _nice_ticks(xlo, xhi, max(2, int(area.width() / 90))):
            p.drawLine(QPointF(X(t), area.top()), QPointF(X(t), area.bottom()))
        for t in _nice_ticks(ylo, yhi, max(2, int(area.height() / 45))):
            p.drawLine(QPointF(area.left(), Y(t)), QPointF(area.right(), Y(t)))
        p.setPen(pal_text)
        for t in _nice_ticks(xlo, xhi, max(2, int(area.width() / 90))):
            s_ = _fmt(t)
            p.drawText(QPointF(X(t) - fm.horizontalAdvance(s_) / 2, area.bottom() + fm.ascent() + 4), s_)
        if dual:
            p.setPen(QtGui.QColor(self.series[0][2]))
        for t in _nice_ticks(ylo, yhi, max(2, int(area.height() / 45))):
            s_ = _fmt(t)
            p.drawText(QPointF(area.left() - fm.horizontalAdvance(s_) - 6, Y(t) + fm.ascent() / 2 - 1), s_)
        if dual:
            p.setPen(QtGui.QColor(self.series[1][2]))
            for t in _nice_ticks(y2lo, y2hi, max(2, int(area.height() / 45))):
                p.drawText(QPointF(area.right() + 6, Y2(t) + fm.ascent() / 2 - 1), _fmt(t))
            p.setPen(pal_text)
        p.drawText(
            QPointF(area.center().x() - fm.horizontalAdvance(self.xlabel) / 2, self.height() - 4), self.xlabel
        )
        if self.ylabel:
            p.save()
            p.translate(fm.ascent(), area.center().y() + fm.horizontalAdvance(self.ylabel) / 2)
            p.rotate(-90)
            p.drawText(QPointF(0, 0), self.ylabel)
            p.restore()
        p.setPen(QtGui.QPen(QtGui.QColor("#2f4a2c")))
        p.drawRect(area)

        p.setClipRect(area)
        p.setRenderHint(QtGui.QPainter.Antialiasing, self.mode == "xy")
        x = self.x
        for si, (lab, y, col) in enumerate(self.series):
            pen = QtGui.QPen(QtGui.QColor(col))
            pen.setWidthF(1.2)
            pen.setCosmetic(True)
            p.setPen(pen)
            if self.mode == "line":
                self._draw_decimated(p, x, y, X, Y2 if (dual and si == 1) else Y, area)
            else:
                poly = QtGui.QPolygonF()
                step = max(1, len(x) // 20000)
                for xi, yi in zip(x[::step], y[::step]):
                    if xi != xi or yi != yi:
                        if poly.size() > 1:
                            p.drawPolyline(poly)
                        poly = QtGui.QPolygonF()
                        continue
                    poly.append(QPointF(X(xi), Y(yi)))
                if poly.size() > 1:
                    p.drawPolyline(poly)
        # cursor / hover
        for row, color in ((self.cursor, "#ff5d8f"), (self._hover, "#e8ede8")):
            if row is None or x is None or not (0 <= row < len(x)):
                continue
            p.setPen(QtGui.QPen(QtGui.QColor(color)))
            if self.mode == "line":
                p.drawLine(QPointF(X(x[row]), area.top()), QPointF(X(x[row]), area.bottom()))
            else:
                y = self.series[0][1]
                if np.isfinite(x[row]) and np.isfinite(y[row]):
                    p.setBrush(QtGui.QColor(color))
                    p.drawEllipse(QPointF(X(x[row]), Y(y[row])), 3.5, 3.5)
        p.setClipping(False)
        # legend + hover readout
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        lx = area.left() + 6
        for lab, _y, col in self.series:
            p.setPen(QtGui.QColor(col))
            p.drawText(QPointF(lx, top - 4), lab)
            lx += fm.horizontalAdvance(lab) + 18
        if self._hover is not None and x is not None and 0 <= self._hover < len(x):
            i = self._hover
            vals = "  ".join(f"{lab}={_fmt(float(y[i]))}" for lab, y, _c in self.series if np.isfinite(y[i]))
            txt = f"{self.xlabel.split(' ')[0]}={_fmt(float(x[i]))}  {vals}  (row {i})"
            p.setPen(QtGui.QColor("#e8ede8"))
            p.drawText(QPointF(area.right() - fm.horizontalAdvance(txt) - 4, top - 4), txt)
        p.end()

    def _draw_decimated(self, p, x, y, X, Y, area) -> None:
        n = len(y)
        good = np.isfinite(x) & np.isfinite(y)
        if not good.any():
            return
        cols = int(area.width())
        if n <= cols * 2:
            poly = QtGui.QPolygonF()
            for xi, yi, ok in zip(x, y, good):
                if not ok:
                    if poly.size() > 1:
                        p.drawPolyline(poly)
                    poly = QtGui.QPolygonF()
                    continue
                poly.append(QPointF(X(xi), Y(yi)))
            if poly.size() > 1:
                p.drawPolyline(poly)
            return
        # min/max envelope per pixel column (x assumed monotonic: time/frame)
        xs, ys = x[good], y[good]
        bins = np.clip(((xs - xs[0]) / max(xs[-1] - xs[0], 1e-12) * (cols - 1)).astype(int), 0, cols - 1)
        lo = np.full(cols, np.inf)
        hi = np.full(cols, -np.inf)
        np.minimum.at(lo, bins, ys)
        np.maximum.at(hi, bins, ys)
        prev = None
        for c in range(cols):
            if not np.isfinite(lo[c]):
                prev = None
                continue
            xp = area.left() + c
            p.drawLine(QPointF(xp, Y(lo[c])), QPointF(xp, Y(hi[c])))
            if prev is not None:
                p.drawLine(QPointF(xp - 1, Y(prev)), QPointF(xp, Y((lo[c] + hi[c]) / 2)))
            prev = (lo[c] + hi[c]) / 2

    def _row_at(self, pos: QPointF) -> Optional[int]:
        if self._geom is None or self.x is None or not len(self.x):
            return None
        area, xlo, xhi, ylo, yhi = self._geom
        if not area.contains(pos):
            return None
        xv = xlo + (pos.x() - area.left()) / area.width() * (xhi - xlo)
        if self.mode == "line":
            x = self.x
            if np.all(np.diff(x[np.isfinite(x)]) >= 0):
                i = int(np.clip(np.searchsorted(x, xv), 0, len(x) - 1))
                if i > 0 and abs(x[i - 1] - xv) < abs(x[i] - xv):
                    i -= 1
                return i
            return int(np.nanargmin(np.abs(x - xv)))
        yv = ylo + (pos.y() - area.top()) / area.height() * (yhi - ylo)
        d = (self.x - xv) ** 2 + (self.series[0][1] - yv) ** 2
        if not np.isfinite(d).any():
            return None
        return int(np.nanargmin(d))

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        self._hover = self._row_at(ev.position())
        self.update()

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        row = self._row_at(ev.position())
        if row is not None and ev.button() == Qt.LeftButton:
            self.rowClicked.emit(row)


# =========================================================================
#  table + parameter form
# =========================================================================
class ResultModel(QtCore.QAbstractTableModel):
    def __init__(self, result: Optional[oa.AnalysisResult] = None) -> None:
        super().__init__()
        self.set_result(result)

    def set_result(self, result) -> None:
        self.beginResetModel()
        self.res = result
        self.keys = list(result.columns) if result is not None else []
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self.res) if self.res is not None else 0

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self.keys)

    def data(self, idx, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or self.res is None:
            return None
        v = self.res.columns[self.keys[idx.column()]][idx.row()]
        if isinstance(v, (np.floating, float)):
            return "" if not np.isfinite(v) else f"{float(v):.6g}"
        return str(v)

    def headerData(self, section, orient, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orient == Qt.Horizontal and self.res is not None:
            k = self.keys[section]
            u = self.res.units.get(k, "")
            return f"{k} [{u}]" if u else k
        return str(section)


class ParamForm(QtWidgets.QWidget):
    """Form fields generated from a module's `params`."""

    changed = Signal()

    def __init__(self, cls: type, values: Optional[dict] = None, parent=None) -> None:
        super().__init__(parent)
        self.cls = cls
        self.widgets: dict[str, QtWidgets.QWidget] = {}
        lay = QtWidgets.QFormLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        values = dict(values or {})
        for p in cls.params:
            v = values.get(p.key, p.default)
            if p.choices:
                w = QtWidgets.QComboBox()
                w.addItems([str(c) for c in p.choices])
                if str(v) in p.choices:
                    w.setCurrentText(str(v))
                w.currentIndexChanged.connect(lambda *_: self.changed.emit())
            elif p.type is bool:
                w = QtWidgets.QCheckBox()
                w.setChecked(bool(v))
                w.toggled.connect(lambda *_: self.changed.emit())
            elif p.type is int:
                w = QtWidgets.QSpinBox()
                w.setRange(int(p.min if p.min is not None else -(10**9)), int(p.max if p.max is not None else 10**9))
                w.setValue(int(v))
                w.valueChanged.connect(lambda *_: self.changed.emit())
            elif p.type is float:
                w = QtWidgets.QDoubleSpinBox()
                w.setDecimals(4)
                w.setRange(p.min if p.min is not None else -1e12, p.max if p.max is not None else 1e12)
                w.setSingleStep(0.05 if (p.max is not None and p.max <= 1) else 1.0)
                w.setValue(float(v))
                w.valueChanged.connect(lambda *_: self.changed.emit())
            else:
                w = QtWidgets.QLineEdit(str(v))
                w.textChanged.connect(lambda *_: self.changed.emit())
            w.setToolTip(p.help)
            lab = QtWidgets.QLabel(p.label or p.key)
            lab.setObjectName("fieldlabel")
            lab.setToolTip(p.help)
            lay.addRow(lab, w)
            self.widgets[p.key] = w

    def values(self) -> dict[str, Any]:
        out = {}
        for p in self.cls.params:
            w = self.widgets[p.key]
            if isinstance(w, QtWidgets.QComboBox):
                out[p.key] = w.currentText()
            elif isinstance(w, QtWidgets.QCheckBox):
                out[p.key] = w.isChecked()
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                out[p.key] = w.value()
            else:
                out[p.key] = w.text()
        return out

    def reset(self) -> None:
        for p in self.cls.params:
            w = self.widgets[p.key]
            if isinstance(w, QtWidgets.QComboBox):
                w.setCurrentText(str(p.default))
            elif isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(bool(p.default))
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                w.setValue(p.default)
            else:
                w.setText(str(p.default))


# =========================================================================
#  Analyze view
# =========================================================================
class _Signals(QtCore.QObject):
    progress = Signal(int, int, str)
    done = Signal(object)  # list[(bin_path, AnalysisRun)]
    error = Signal(str)
    log = Signal(str)


class AnalyzeView(QtWidgets.QWidget):
    """The Modules tab."""

    def __init__(self, studio, parent=None) -> None:
        super().__init__(parent)
        self.studio = studio
        self.qs = QtCore.QSettings("opngx", "opngx-studio")
        self.infos: list[oa.ModuleInfo] = []
        self.forms: dict[str, ParamForm] = {}
        self.results: dict[tuple[str, str], oa.AnalysisResult] = {}  # (bin, module)
        self.current: Optional[tuple[str, str]] = None
        self._readers: dict[str, Any] = {}
        self._cancel = False
        self._running = False
        self.sig = _Signals()
        self.sig.progress.connect(self._on_progress)
        self.sig.done.connect(self._on_done)
        self.sig.error.connect(self._on_error)
        self.sig.log.connect(self._log)
        self._build()
        self.reload_modules()

    # ---------------------------------------------------------------- ui --
    def _build(self) -> None:
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QtWidgets.QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        outer.addWidget(split)

        # ---- left: modules, params, run options
        left = QtWidgets.QWidget()
        left.setObjectName("leftcol")
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 6, 0)
        card = QtWidgets.QFrame()
        card.setObjectName("card")
        cv = QtWidgets.QVBoxLayout(card)
        t = QtWidgets.QLabel("ANALYSIS MODULES")
        t.setObjectName("cardtitle")
        cv.addWidget(t)
        hint = QtWidgets.QLabel(
            "Tick a module to switch it in (Run all runs every ticked module in one "
            "pass); select one to set its parameters. Write your own in the "
            "Module editor tab."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        cv.addWidget(hint)
        self.mod_list = QtWidgets.QListWidget()
        self.mod_list.setMinimumHeight(120)
        self.mod_list.currentRowChanged.connect(self._on_select_module)
        self.mod_list.itemChanged.connect(self._on_toggle_module)
        cv.addWidget(self.mod_list)
        row = QtWidgets.QHBoxLayout()
        self.btn_reload = QtWidgets.QPushButton("Reload modules")
        self.btn_reload.clicked.connect(self.reload_modules)
        self.btn_edit = QtWidgets.QPushButton("Edit / new…")
        self.btn_edit.clicked.connect(self._open_editor)
        row.addWidget(self.btn_reload)
        row.addWidget(self.btn_edit)
        cv.addLayout(row)
        self.mod_desc = QtWidgets.QLabel("")
        self.mod_desc.setObjectName("hint")
        self.mod_desc.setWordWrap(True)
        cv.addWidget(self.mod_desc)
        lv.addWidget(card)

        pcard = QtWidgets.QFrame()
        pcard.setObjectName("card")
        pv = QtWidgets.QVBoxLayout(pcard)
        t = QtWidgets.QLabel("PARAMETERS")
        t.setObjectName("cardtitle")
        pv.addWidget(t)
        self.form_host = QtWidgets.QStackedWidget()
        pv.addWidget(self.form_host)
        self.btn_defaults = QtWidgets.QPushButton("Reset to defaults")
        self.btn_defaults.clicked.connect(self._reset_params)
        pv.addWidget(self.btn_defaults)
        lv.addWidget(pcard)

        rcard = QtWidgets.QFrame()
        rcard.setObjectName("card")
        rv = QtWidgets.QVBoxLayout(rcard)
        t = QtWidgets.QLabel("RUN")
        t.setObjectName("cardtitle")
        rv.addWidget(t)
        self.rb_current = QtWidgets.QRadioButton("the loaded recording")
        self.rb_batch = QtWidgets.QRadioButton("every recording in the batch folder")
        self.rb_current.setChecked(True)
        rv.addWidget(self.rb_current)
        rv.addWidget(self.rb_batch)
        grid = QtWidgets.QGridLayout()
        self.sp_start = QtWidgets.QSpinBox()
        self.sp_start.setRange(0, 10**9)
        self.sp_count = QtWidgets.QSpinBox()
        self.sp_count.setRange(0, 10**9)
        self.sp_count.setSpecialValueText("all")
        self.sp_stride = QtWidgets.QSpinBox()
        self.sp_stride.setRange(1, 100000)
        for r_, (lab, w) in enumerate((("start frame", self.sp_start), ("frames", self.sp_count), ("every Nth", self.sp_stride))):
            lb = QtWidgets.QLabel(lab)
            lb.setObjectName("fieldlabel")
            grid.addWidget(lb, r_, 0)
            grid.addWidget(w, r_, 1)
        rv.addLayout(grid)
        self.cb_crop = QtWidgets.QCheckBox("restrict to the crop (region of interest)")
        self.cb_crop.setToolTip("Analyse only the studio's crop rectangle; positions stay in full-frame pixels.")
        rv.addWidget(self.cb_crop)
        self.cmb_source = QtWidgets.QComboBox()
        self.cmb_source.addItems(["raw sensor values", "display curve (B/C/G)"])
        self.cmb_source.setToolTip(
            "Raw = the camera's bytes, the right input for measurement.\n"
            "Display = after the Extract tab's brightness/contrast/gamma."
        )
        rv.addWidget(self.cmb_source)
        self.cb_save = QtWidgets.QCheckBox("also write data files to <output>/<recording>/ANALYSIS/")
        self.cb_save.setChecked(True)
        rv.addWidget(self.cb_save)
        self.cmb_fmt = QtWidgets.QComboBox()
        self.cmb_fmt.addItems(["csv", "json", "npz", "tsv"])
        rv.addWidget(self.cmb_fmt)
        self.run_bar = QtWidgets.QFrame()
        self.run_bar.setObjectName("card")
        rb_lay = QtWidgets.QVBoxLayout(self.run_bar)
        b1 = QtWidgets.QHBoxLayout()
        self.btn_run = QtWidgets.QPushButton("▶  Run selected")
        self.btn_run.setObjectName("accent")
        self.btn_run.clicked.connect(lambda: self.run(only_selected=True))
        self.btn_run_all = QtWidgets.QPushButton("▶▶ Run all ticked")
        self.btn_run_all.clicked.connect(lambda: self.run(only_selected=False))
        self.btn_cancel = QtWidgets.QPushButton("■  Cancel")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        b1.addWidget(self.btn_run)
        b1.addWidget(self.btn_run_all)
        b1.addWidget(self.btn_cancel)
        rb_lay.addLayout(b1)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1000)
        scaling.fix(self.bar, "setFixedHeight", 14)
        rb_lay.addWidget(self.bar)
        self.status = QtWidgets.QLabel("idle")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        rb_lay.addWidget(self.status)
        lv.addWidget(rcard)
        lv.addStretch(1)
        lscroll = QtWidgets.QScrollArea()
        lscroll.setWidget(left)
        lscroll.setWidgetResizable(True)
        lscroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        lscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left.setAutoFillBackground(False)
        lscroll.viewport().setAutoFillBackground(False)
        scaling.fix(lscroll, "setMinimumWidth", 330)
        # the run controls stay pinned under the scrolling settings: at every
        # resolution they are visible without scrolling
        lcol = QtWidgets.QWidget()
        lcl = QtWidgets.QVBoxLayout(lcol)
        lcl.setContentsMargins(0, 0, 6, 0)
        lcl.setSpacing(8)
        lcl.addWidget(lscroll, 1)
        lcl.addWidget(self.run_bar)
        split.addWidget(lcol)

        # ---- right: results
        right = QtWidgets.QWidget()
        rlay = QtWidgets.QVBoxLayout(right)
        rlay.setContentsMargins(6, 0, 0, 0)
        top = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel("result")
        lab.setObjectName("fieldlabel")
        top.addWidget(lab)
        self.cmb_result = QtWidgets.QComboBox()
        self.cmb_result.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.cmb_result.currentIndexChanged.connect(self._on_pick_result)
        top.addWidget(self.cmb_result, 1)
        self.btn_export = QtWidgets.QPushButton("⤓  Export data file…")
        self.btn_export.setObjectName("accent")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_current)
        self.btn_export_all = QtWidgets.QPushButton("Export all…")
        self.btn_export_all.setEnabled(False)
        self.btn_export_all.clicked.connect(self.export_all)
        top.addWidget(self.btn_export)
        top.addWidget(self.btn_export_all)
        rlay.addLayout(top)

        vsplit = QtWidgets.QSplitter(Qt.Vertical)
        hsplit = QtWidgets.QSplitter(Qt.Horizontal)
        pw = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        self.preview = FrameView(pw, placeholder="the analysed frame appears here")
        pl.addWidget(self.preview, 1)
        srow = QtWidgets.QHBoxLayout()
        self.row_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.row_slider.setRange(0, 0)
        self.row_slider.valueChanged.connect(self._on_row)
        self.row_lbl = QtWidgets.QLabel("—")
        self.row_lbl.setObjectName("hint")
        self.cb_path = QtWidgets.QCheckBox("trajectory")
        self.cb_path.setChecked(True)
        self.cb_path.toggled.connect(lambda *_: self._on_row(self.row_slider.value()))
        srow.addWidget(self.row_slider, 1)
        srow.addWidget(self.cb_path)
        pl.addLayout(srow)
        self.row_lbl.setWordWrap(True)
        pl.addWidget(self.row_lbl)
        hsplit.addWidget(pw)

        plot_host = QtWidgets.QWidget()
        pv2 = QtWidgets.QVBoxLayout(plot_host)
        pv2.setContentsMargins(0, 0, 0, 0)
        prow = QtWidgets.QHBoxLayout()
        self.cmb_plot = QtWidgets.QComboBox()
        self.cmb_plot.addItems(["vs time", "trajectory (x–y)"])
        self.cmb_plot.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.cmb_plot.currentIndexChanged.connect(lambda *_: self._refresh_plot())
        self.cmb_y1 = QtWidgets.QComboBox()
        self.cmb_y2 = QtWidgets.QComboBox()
        for c in (self.cmb_y1, self.cmb_y2):
            c.currentIndexChanged.connect(lambda *_: self._refresh_plot())
        prow.addWidget(self.cmb_plot)
        for lab_, c in (("y", self.cmb_y1), ("y2", self.cmb_y2)):
            lb = QtWidgets.QLabel(lab_)
            lb.setObjectName("fieldlabel")
            prow.addWidget(lb)
            prow.addWidget(c, 1)
        pv2.addLayout(prow)
        self.plot = PlotView()
        self.plot.rowClicked.connect(lambda r_: self.row_slider.setValue(r_))
        pv2.addWidget(self.plot, 1)
        hsplit.addWidget(plot_host)
        hsplit.setStretchFactor(0, 1)
        hsplit.setStretchFactor(1, 1)
        vsplit.addWidget(hsplit)

        self.tabs = QtWidgets.QTabWidget()
        self.table = QtWidgets.QTableView()
        self.model = ResultModel()
        self.table.setModel(self.model)
        self.table.verticalHeader().setDefaultSectionSize(scaling.px(20))
        self.table.horizontalHeader().setResizeContentsPrecision(200)  # sample rows: 50k stays fast
        self.table.clicked.connect(lambda idx: self.row_slider.setValue(idx.row()))
        self.tabs.addTab(self.table, "Data")
        self.summary = QtWidgets.QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.tabs.addTab(self.summary, "Summary")
        self.logv = QtWidgets.QPlainTextEdit()
        self.logv.setReadOnly(True)
        self.logv.setMaximumBlockCount(4000)
        self.tabs.addTab(self.logv, "Log")
        vsplit.addWidget(self.tabs)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        rlay.addWidget(vsplit, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

    # ----------------------------------------------------------- modules --
    def _disabled(self) -> set[str]:
        v = self.qs.value("analysis/disabled", [])
        if isinstance(v, str):
            v = [v] if v else []
        return set(v or [])

    def reload_modules(self) -> None:
        keep = self.selected_name()
        self.infos = oa.discover()
        disabled = self._disabled()
        self.mod_list.blockSignals(True)
        self.mod_list.clear()
        while self.form_host.count():
            w = self.form_host.widget(0)
            self.form_host.removeWidget(w)
            w.deleteLater()
        self.forms.clear()
        for info in self.infos:
            label = f"{info.title}   [{info.name}]" + ("" if info.origin == "builtin" else "  · user")
            it = QtWidgets.QListWidgetItem(label)
            it.setData(Qt.UserRole, info.name)
            if info.ok:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked if info.name in disabled else Qt.Checked)
                it.setToolTip(info.cls.description)
                saved = self._saved_params(info.name)
                try:
                    form = ParamForm(info.cls, saved)
                except Exception:  # noqa: BLE001 — stale saved value
                    form = ParamForm(info.cls)
                form.changed.connect(lambda n=info.name: self._save_params(n))
            else:
                it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
                it.setForeground(QtGui.QColor("#f87171"))
                it.setText(label + "  — BROKEN")
                it.setToolTip(info.error)
                form = QtWidgets.QLabel("This module failed to load:\n\n" + info.error)
                form.setWordWrap(True)
                form.setObjectName("hint")
            self.forms[info.name] = form
            self.form_host.addWidget(form)
            self.mod_list.addItem(it)
        self.mod_list.blockSignals(False)
        names = [i.name for i in self.infos]
        self.mod_list.setCurrentRow(names.index(keep) if keep in names else 0)
        self._log(f"modules: {', '.join(i.name + ('' if i.ok else ' (broken)') for i in self.infos)}")

    def selected_name(self) -> Optional[str]:
        it = self.mod_list.currentItem() if hasattr(self, "mod_list") else None
        return it.data(Qt.UserRole) if it is not None else None

    def enabled_names(self) -> list[str]:
        out = []
        for i in range(self.mod_list.count()):
            it = self.mod_list.item(i)
            if it.flags() & Qt.ItemIsUserCheckable and it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _info(self, name: str) -> Optional[oa.ModuleInfo]:
        return next((i for i in self.infos if i.name == name), None)

    def _on_select_module(self, row: int) -> None:
        if row < 0 or row >= len(self.infos):
            return
        info = self.infos[row]
        self.form_host.setCurrentWidget(self.forms[info.name])
        if info.ok:
            self.mod_desc.setText(
                f"<b>{info.title}</b> v{info.cls.version} · {info.origin}<br>{info.cls.description}"
            )
        else:
            self.mod_desc.setText(f"<b>{info.name}</b> — cannot be loaded (see parameters pane)")
        self.btn_defaults.setEnabled(info.ok)

    def _on_toggle_module(self, item) -> None:
        dis = self._disabled()
        name = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            dis.discard(name)
        else:
            dis.add(name)
        self.qs.setValue("analysis/disabled", sorted(dis))

    def _saved_params(self, name: str) -> dict:
        try:
            return json.loads(self.qs.value(f"analysis/params/{name}", "{}") or "{}")
        except (TypeError, ValueError):
            return {}

    def _save_params(self, name: str) -> None:
        f = self.forms.get(name)
        if isinstance(f, ParamForm):
            self.qs.setValue(f"analysis/params/{name}", json.dumps(f.values()))

    def _reset_params(self) -> None:
        f = self.forms.get(self.selected_name() or "")
        if isinstance(f, ParamForm):
            f.reset()

    def _open_editor(self) -> None:
        ed = getattr(self.studio, "module_editor", None)
        if ed is None:
            return
        name = self.selected_name()
        info = self._info(name) if name else None
        if info is not None and info.path:
            ed.open_path(info.path)
        self.studio.tabs.setCurrentWidget(ed)

    # --------------------------------------------------------------- run --
    def _targets(self) -> list[tuple[str, Any]]:
        """[(bin_path, meta or None)] for the chosen scope."""
        st = self.studio
        if self.rb_batch.isChecked():
            root = st.bin_edit.text().strip()
            if not os.path.isdir(root):
                root = os.path.dirname(root)
            from opngx.ui.batch import scan_batch

            return [(b, None) for b in scan_batch(root)], root
        if st.meta is None:
            return [], ""
        return [(st.meta.bin_path, st.meta)], ""

    def run(self, only_selected: bool = True) -> None:
        if self._running:
            return
        names = [self.selected_name()] if only_selected else self.enabled_names()
        names = [n for n in names if n and self._info(n) is not None and self._info(n).ok]
        if not names:
            QtWidgets.QMessageBox.warning(
                self, "opngx", "Select (or tick) a module that loads without errors."
            )
            return
        (targets, root) = self._targets()
        if not targets:
            QtWidgets.QMessageBox.warning(
                self,
                "opngx",
                "Load a recording in the Extract tab first (or choose a batch folder "
                "and pick 'every recording in the batch folder').",
            )
            return
        params = {}
        for n in names:
            f = self.forms[n]
            try:
                params[n] = self._info(n).cls.resolve_params(f.values())
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "opngx", str(exc))
                return
        crop = self.studio._crop if self.cb_crop.isChecked() else None
        source = "display" if self.cmb_source.currentIndex() == 1 else "raw"
        opts = self.studio._collect_opts()
        transform = dict(
            mode=opts["mode"], brightness=opts["brightness"], contrast=opts["contrast"], gamma=opts["gamma"]
        )
        start, count, stride = self.sp_start.value(), (self.sp_count.value() or None), self.sp_stride.value()
        out_root = self.studio.out_edit.text().strip()
        save = self.cb_save.isChecked() and bool(out_root)
        fmt = self.cmb_fmt.currentText()
        self._cancel = False
        self._set_running(True)
        self._log(
            f"run {', '.join(names)} on {len(targets)} recording(s) · frames {start}+"
            f"{count or 'all'} every {stride} · source={source}" + (f" · crop={crop}" if crop else "")
        )

        def work() -> None:
            done: list = []
            try:
                for bi, (b, meta) in enumerate(targets):
                    if self._cancel:
                        break
                    tag = f"{bi + 1}/{len(targets)} {os.path.basename(b)}"
                    try:
                        if meta is None:
                            meta = opngx.probe(b)
                        c = crop
                        if c is not None:
                            try:
                                opngx.normalize_crop(c, meta.width, meta.height)
                            except ValueError:
                                self.sig.log.emit(f"{tag}: crop does not fit {meta.width}x{meta.height} — full frame")
                                c = None
                        run = oa.analyze(
                            b, names, params=params, meta=meta, start=start, count=count,
                            stride=stride, crop=c, source=source, transform=transform,
                            progress=lambda d, t_, tag=tag: self.sig.progress.emit(d, t_, tag),
                            should_cancel=lambda: self._cancel,
                            log=lambda s, tag=tag: self.sig.log.emit(f"{tag}: {s}"),
                        )
                    except Exception as exc:  # noqa: BLE001
                        self.sig.log.emit(f"{tag}: FAILED — {exc}")
                        continue
                    for n, err in run.errors.items():
                        self.sig.log.emit(f"{tag}: {err}\n{err.tb}")
                    if save:
                        from opngx.layout import recording_key, safe_name

                        key = recording_key(root, b) if root else safe_name(os.path.splitext(os.path.basename(b))[0])
                        for n, res in run.results.items():
                            path = os.path.join(out_root, key, "ANALYSIS", f"{n}.{fmt}")
                            try:
                                res.save(path)
                                self.sig.log.emit(f"{tag}: wrote {path}")
                            except OSError as exc:
                                self.sig.log.emit(f"{tag}: cannot write {path}: {exc}")
                    self.sig.log.emit(
                        f"{tag}: {run.frames:,} frames in {run.seconds:.2f}s "
                        f"({run.frames / max(run.seconds, 1e-9):,.0f} frames/s)"
                        + (" — CANCELLED" if run.cancelled else "")
                    )
                    done.append((b, run))
            except Exception as exc:  # noqa: BLE001
                self.sig.error.emit(str(exc))
            self.sig.done.emit(done)

        threading.Thread(target=work, name="opngx-analyze", daemon=True).start()

    def cancel(self) -> None:
        self._cancel = True
        self.status.setText("cancel requested…")

    def _set_running(self, on: bool) -> None:
        self._running = on
        for w in (self.btn_run, self.btn_run_all, self.btn_reload):
            w.setEnabled(not on)
        self.btn_cancel.setEnabled(on)

    def _on_progress(self, d: int, t: int, tag: str) -> None:
        self.bar.setValue(int(1000 * d / max(t, 1)))
        self.status.setText(f"{tag}: {d:,}/{t:,} frames")

    def _on_error(self, msg: str) -> None:
        self._log(f"ERROR: {msg}")
        QtWidgets.QMessageBox.critical(self, "opngx analysis", msg)

    def _on_done(self, done: list) -> None:
        self._set_running(False)
        n_before = self.cmb_result.count()
        for b, run in done:
            for n, res in run.results.items():
                self.results[(b, n)] = res
        self._refill_results()
        errs = sum(len(r.errors) for _b, r in done)
        self.status.setText(
            f"done: {sum(len(r.results) for _b, r in done)} result(s) from {len(done)} recording(s)"
            + (f", {errs} module error(s) — see Log" if errs else "")
        )
        if errs:
            self.tabs.setCurrentWidget(self.logv)
        if done and done[-1][1].results:
            b, run = done[-1]
            key = (b, next(iter(run.results)))
            self._select_result(key)
        elif self.cmb_result.count() == n_before == 0:
            self.bar.setValue(0)

    def _log(self, msg: str) -> None:
        if hasattr(self, "logv"):
            self.logv.appendPlainText(time.strftime("[%H:%M:%S] ") + msg)

    # ----------------------------------------------------------- results --
    def _refill_results(self) -> None:
        self.cmb_result.blockSignals(True)
        cur = self.current
        self.cmb_result.clear()
        for key in self.results:
            b, n = key
            self.cmb_result.addItem(f"{os.path.basename(os.path.dirname(b)) or os.path.basename(b)} · {n}", key)
        self.cmb_result.blockSignals(False)
        if cur in self.results:
            self._select_result(cur)
        has = bool(self.results)
        self.btn_export.setEnabled(has)
        self.btn_export_all.setEnabled(has)

    def _select_result(self, key) -> None:
        for i in range(self.cmb_result.count()):
            if self.cmb_result.itemData(i) == key:
                self.cmb_result.setCurrentIndex(i)
                self._on_pick_result(i)
                return

    def result(self) -> Optional[oa.AnalysisResult]:
        return self.results.get(self.current) if self.current else None

    def _on_pick_result(self, i: int) -> None:
        key = self.cmb_result.itemData(i)
        if key is None:
            return
        self.current = key
        res = self.results[key]
        self.model.set_result(res)
        self.table.resizeColumnsToContents()
        numeric = [k for k in res.columns if k not in ("frame", "timestamp_raw", "time_s")]
        for c in (self.cmb_y1, self.cmb_y2):
            c.blockSignals(True)
            c.clear()
        self.cmb_y2.addItem("—")
        for k in numeric:
            self.cmb_y1.addItem(k)
            self.cmb_y2.addItem(k)
        want = list(res.plot) or numeric[:1]
        if want:
            self.cmb_y1.setCurrentText(want[0])
        if len(want) > 1:
            self.cmb_y2.setCurrentText(want[1])
        for c in (self.cmb_y1, self.cmb_y2):
            c.blockSignals(False)
        self.cmb_plot.blockSignals(True)
        self.cmb_plot.setCurrentIndex(1 if res.trajectory else 0)
        self.cmb_plot.blockSignals(False)
        s = dict(res.summary)
        txt = [f"{res.module_title}  (module {res.module} v{res.module_version})", ""]
        txt += [f"{k}: {v:.6g}" if isinstance(v, float) else f"{k}: {v}" for k, v in s.items()]
        txt += ["", "run: " + json.dumps(res.run), "params: " + json.dumps(res.params),
                "recording: " + str(res.recording.get("bin_path", ""))]
        self.summary.setPlainText("\n".join(txt))
        self.row_slider.blockSignals(True)
        self.row_slider.setRange(0, max(0, len(res) - 1))
        self.row_slider.setValue(0)
        self.row_slider.blockSignals(False)
        self._refresh_plot()
        self._on_row(0)

    def _refresh_plot(self) -> None:
        res = self.result()
        if res is None:
            self.plot.clear()
            return
        ov = res.overlay
        if self.cmb_plot.currentIndex() == 1 and "x" in ov and "y" in ov:
            self.plot.set_xy(res.columns[ov["x"]], res.columns[ov["y"]], label="trajectory",
                             xlabel=f"{ov['x']} [px]", ylabel=f"{ov['y']} [px]")
        else:
            series = []
            for i, c in enumerate((self.cmb_y1, self.cmb_y2)):
                k = c.currentText()
                if k and k != "—" and k in res.columns:
                    u = res.units.get(k, "")
                    series.append((f"{k} [{u}]" if u else k, res.columns[k], SERIES_COLORS[i]))
            self.plot.set_line(res.columns["time_s"], series, xlabel="time [s]")
        self.plot.set_cursor(self.row_slider.value())

    def _reader_for(self, bin_path: str):
        r = self._readers.get(bin_path)
        if r is None:
            st = self.studio
            meta = st.meta if (st.meta is not None and st.meta.bin_path == bin_path) else opngx.probe(bin_path)
            r = opngx.FrameReader(meta)
            self._readers = {bin_path: r}  # keep one mapping open
        return r

    def _on_row(self, row: int) -> None:
        res = self.result()
        if res is None or not len(res):
            return
        row = max(0, min(row, len(res) - 1))
        frame = int(res.columns["frame"][row])
        try:
            r = self._reader_for(self.current[0])
            arr = r.gray(frame, **self.studio._current_lut_kwargs())
            self.preview.setImage(gray_to_qimage(arr))
        except Exception as exc:  # noqa: BLE001
            self.preview.setImage(None)
            self.preview.setPlaceholder(str(exc))
        ov = res.overlay
        crop = res.run.get("crop")
        self.preview.setSelection(tuple(crop) if crop and (crop[2], crop[3]) != (res.recording.get("width"), res.recording.get("height")) else None)
        if "x" in ov and "y" in ov:
            x, y = res.columns[ov["x"]], res.columns[ov["y"]]
            rr = res.columns.get(ov.get("r", ""), None)
            path = np.c_[x, y] if self.cb_path.isChecked() else None
            circle = (x[row], y[row], rr[row]) if rr is not None else None
            self.preview.setMarkers(path=path, point=(x[row], y[row]), circle=circle)
        else:
            self.preview.clearMarkers()
        self.plot.set_cursor(row)
        t = float(res.columns["time_s"][row])
        vals = []
        for k in (ov.get("x"), ov.get("y"), *(res.plot or ())):
            if k and k in res.columns and k not in [v.split("=")[0] for v in vals]:
                v = res.columns[k][row]
                vals.append(f"{k}={float(v):.3f}" if np.isfinite(v) else f"{k}=—")
        self.row_lbl.setText(f"frame {frame:,} · t={t:.4f}s · " + " ".join(vals))
        self.table.selectRow(row)

    # ------------------------------------------------------------ export --
    def export_current(self) -> Optional[str]:
        res = self.result()
        if res is None:
            return None
        b, n = self.current
        stem = os.path.splitext(os.path.basename(b))[0]
        fmt = self.cmb_fmt.currentText()
        start = os.path.join(self.studio.out_edit.text().strip() or os.path.dirname(b), f"{stem}_{n}.{fmt}")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export analysis data", start,
            "CSV (*.csv);;JSON (*.json);;NumPy (*.npz);;TSV (*.tsv);;All files (*)",
        )
        if not path:
            return None
        try:
            res.save(path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "opngx", f"Cannot write {path}:\n{exc}")
            return None
        self._log(f"exported {res.describe()} -> {path}")
        self.status.setText(f"saved {path}")
        return path

    def export_all(self) -> Optional[str]:
        if not self.results:
            return None
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Export every result into…", self.studio.out_edit.text().strip() or ""
        )
        if not d:
            return None
        from opngx.layout import safe_name

        fmt = self.cmb_fmt.currentText()
        n = 0
        for (b, name), res in self.results.items():
            key = safe_name(os.path.basename(os.path.dirname(b)) or os.path.splitext(os.path.basename(b))[0])
            res.save(os.path.join(d, key, "ANALYSIS", f"{name}.{fmt}"))
            n += 1
        self._log(f"exported {n} result(s) into {d}/<recording>/ANALYSIS/")
        self.status.setText(f"exported {n} file(s) into {d}")
        return d


# =========================================================================
#  code editor
# =========================================================================
class PythonHighlighter(QtGui.QSyntaxHighlighter):
    KEYWORDS = (
        "and as assert async await break class continue def del elif else except False finally for "
        "from global if import in is lambda None nonlocal not or pass raise return True try while with yield"
    ).split()

    def __init__(self, doc) -> None:
        super().__init__(doc)
        import re

        def fmt(color, bold=False, italic=False):
            f = QtGui.QTextCharFormat()
            f.setForeground(QtGui.QColor(color))
            if bold:
                f.setFontWeight(QtGui.QFont.Bold)
            f.setFontItalic(italic)
            return f

        # (pattern, format, capture group to colour: 0 = whole match)
        self.rules = [
            (re.compile(r"\b(?:" + "|".join(self.KEYWORDS) + r")\b"), fmt("#c792ea", True), 0),
            (re.compile(r"\b(?:self|ctx|np)\b"), fmt("#f78c6c"), 0),
            (re.compile(r"\b(?:Module|Param|Column|Context)\b"), fmt("#82aaff", True), 0),
            (re.compile(r"@\w+"), fmt("#ffcb6b"), 0),
            (re.compile(r"\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\b"), fmt("#f78c6c"), 0),
            (re.compile(r"\b(?:def|class)\s+(\w+)"), fmt("#82aaff"), 1),
            (re.compile(r"\"[^\"\n]*\"|'[^'\n]*'"), fmt("#c3e88d"), 0),
            (re.compile(r"#[^\n]*"), fmt("#5f7e5f", italic=True), 0),
        ]
        self.tri = fmt("#c3e88d")

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for rx, f, grp in self.rules:
            for m in rx.finditer(text):
                s, e = m.span(grp)
                self.setFormat(s, e - s, f)
        # triple-quoted strings spanning lines: block state 1 = still inside
        self.setCurrentBlockState(0)
        i = 0
        if self.previousBlockState() == 1:
            end = self._find_tq(text, 0)
            if end < 0:
                self.setFormat(0, len(text), self.tri)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 3, self.tri)
            i = end + 3
        while True:
            s = self._find_tq(text, i)
            if s < 0:
                return
            e = self._find_tq(text, s + 3)
            if e < 0:
                self.setFormat(s, len(text) - s, self.tri)
                self.setCurrentBlockState(1)
                return
            self.setFormat(s, e + 3 - s, self.tri)
            i = e + 3

    @staticmethod
    def _find_tq(text: str, frm: int) -> int:
        a, b = text.find('"""', frm), text.find("'''", frm)
        c = [i for i in (a, b) if i >= 0]
        return min(c) if c else -1


class _LineNumbers(QtWidgets.QWidget):
    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.ed = editor

    def sizeHint(self):  # noqa: N802
        return QtCore.QSize(self.ed.gutter_width(), 0)

    def paintEvent(self, ev):  # noqa: N802
        self.ed.paint_gutter(ev)


class CodeEditor(QtWidgets.QPlainTextEdit):
    """Plain-text Python editor: line numbers, highlighting, 4-space tabs,
    auto-indent, current-line and error-line highlight."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        f.setPointSizeF(max(8.0, QtWidgets.QApplication.font().pointSizeF()))
        self.setFont(f)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.gutter = _LineNumbers(self)
        self.blockCountChanged.connect(lambda *_: self._update_margins())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._highlight_line)
        self.hl = PythonHighlighter(self.document())
        self.error_line: Optional[int] = None
        self._update_margins()
        self._highlight_line()

    def gutter_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * max(3, digits)

    def _update_margins(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        cr = self.contentsRect()
        self.gutter.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, ev) -> None:
        p = QtGui.QPainter(self.gutter)
        p.fillRect(ev.rect(), QtGui.QColor("#0a0c0a"))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= ev.rect().bottom():
            if block.isVisible() and bottom >= ev.rect().top():
                p.setPen(QtGui.QColor("#f87171" if (num + 1) == self.error_line else "#4a554a"))
                p.drawText(0, top, self.gutter.width() - 6, self.fontMetrics().height(),
                           Qt.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1
        p.end()

    def _highlight_line(self) -> None:
        sels = []
        cur = QtWidgets.QTextEdit.ExtraSelection()
        cur.format.setBackground(QtGui.QColor("#101610"))
        cur.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        cur.cursor = self.textCursor()
        cur.cursor.clearSelection()
        sels.append(cur)
        if self.error_line:
            blk = self.document().findBlockByNumber(self.error_line - 1)
            if blk.isValid():
                e = QtWidgets.QTextEdit.ExtraSelection()
                e.format.setBackground(QtGui.QColor("#3a1414"))
                e.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
                e.cursor = QtGui.QTextCursor(blk)
                sels.append(e)
        self.setExtraSelections(sels)

    def set_error_line(self, line: Optional[int]) -> None:
        self.error_line = line
        self._highlight_line()
        self.gutter.update()
        if line:
            blk = self.document().findBlockByNumber(line - 1)
            if blk.isValid():
                c = QtGui.QTextCursor(blk)
                self.setTextCursor(c)
                self.centerCursor()

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() == Qt.Key_Tab and not ev.modifiers():
            self.insertPlainText("    ")
            return
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            line = self.textCursor().block().text()
            indent = line[: len(line) - len(line.lstrip(" "))]
            if line.rstrip().endswith(":"):
                indent += "    "
            super().keyPressEvent(ev)
            self.insertPlainText(indent)
            return
        if ev.key() == Qt.Key_Backtab:
            c = self.textCursor()
            line = c.block().text()
            n = min(4, len(line) - len(line.lstrip(" ")))
            if n:
                c.movePosition(QtGui.QTextCursor.StartOfBlock)
                for _ in range(n):
                    c.deleteChar()
            return
        super().keyPressEvent(ev)


class ModuleEditor(QtWidgets.QWidget):
    """The Module editor tab."""

    modulesChanged = Signal()

    def __init__(self, studio, parent=None) -> None:
        super().__init__(parent)
        self.studio = studio
        self.path: Optional[str] = None
        self.read_only = False
        self._build()
        self.refresh_files()

    def _build(self) -> None:
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QtWidgets.QSplitter(Qt.Horizontal)
        outer.addWidget(split)

        left = QtWidgets.QFrame()
        left.setObjectName("card")
        lv = QtWidgets.QVBoxLayout(left)
        t = QtWidgets.QLabel("MODULE FILES")
        t.setObjectName("cardtitle")
        lv.addWidget(t)
        self.files = QtWidgets.QListWidget()
        self.files.itemActivated.connect(lambda it: self.open_path(it.data(Qt.UserRole)))
        self.files.itemClicked.connect(lambda it: self.open_path(it.data(Qt.UserRole)))
        lv.addWidget(self.files, 1)
        self.dir_lbl = QtWidgets.QLabel("")
        self.dir_lbl.setObjectName("hint")
        self.dir_lbl.setWordWrap(True)
        self.dir_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lv.addWidget(self.dir_lbl)
        for text, fn in (
            ("New module…", self.new_module),
            ("Duplicate as my module", self.duplicate),
            ("Open file…", self.open_dialog),
            ("Open modules folder", self.open_folder),
            ("Delete my module…", self.delete_current),
        ):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            lv.addWidget(b)
            setattr(self, "btn_" + text.split()[0].lower(), b)
        scaling.fix(left, "setMinimumWidth", 230)
        split.addWidget(left)

        mid = QtWidgets.QWidget()
        mv = QtWidgets.QVBoxLayout(mid)
        mv.setContentsMargins(6, 0, 0, 0)
        bar = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel("no file")
        self.title.setObjectName("cardtitle")
        bar.addWidget(self.title, 1)
        self.btn_save = QtWidgets.QPushButton("Save  (Ctrl+S)")
        self.btn_save.clicked.connect(self.save)
        self.btn_validate = QtWidgets.QPushButton("Validate  (F5)")
        self.btn_validate.clicked.connect(self.validate)
        self.btn_test = QtWidgets.QPushButton("Test on recording  (F6)")
        self.btn_test.clicked.connect(self.test_run)
        self.btn_apply = QtWidgets.QPushButton("Save && use")
        self.btn_apply.setObjectName("accent")
        self.btn_apply.clicked.connect(self.save_and_reload)
        self.btn_api = QtWidgets.QPushButton("API help")
        self.btn_api.clicked.connect(self.show_api)
        for b in (self.btn_save, self.btn_validate, self.btn_test, self.btn_apply, self.btn_api):
            bar.addWidget(b)
        mv.addLayout(bar)
        vs = QtWidgets.QSplitter(Qt.Vertical)
        self.editor = CodeEditor()
        self.editor.document().modificationChanged.connect(lambda *_: self._update_title())
        vs.addWidget(self.editor)
        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.console.setFont(f)
        vs.addWidget(self.console)
        vs.setStretchFactor(0, 4)
        vs.setStretchFactor(1, 1)
        mv.addWidget(vs, 1)
        split.addWidget(mid)
        split.setStretchFactor(1, 1)
        for seq, fn in (("Ctrl+S", self.save), ("F5", self.validate), ("F6", self.test_run)):
            sc = QtGui.QShortcut(QtGui.QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ------------------------------------------------------------ files ---
    def refresh_files(self) -> None:
        d = oa.user_modules_dir()
        self.dir_lbl.setText(f"your modules folder:\n{d}")
        self.files.clear()
        infos = oa.discover()
        seen = set()
        for info in infos:
            if not info.path or info.path in seen:
                continue
            seen.add(info.path)
            label = os.path.basename(info.path) + ("   (built-in, read-only)" if info.origin == "builtin" else "")
            if not info.ok:
                label += "   ✗"
            it = QtWidgets.QListWidgetItem(label)
            it.setData(Qt.UserRole, info.path)
            if info.origin == "builtin":
                it.setForeground(QtGui.QColor("#8a948a"))
            elif not info.ok:
                it.setForeground(QtGui.QColor("#f87171"))
                it.setToolTip(info.error)
            self.files.addItem(it)

    def _is_builtin(self, path: str) -> bool:
        import opngx.analysis.builtin as bi

        return os.path.abspath(os.path.dirname(path)) == os.path.abspath(os.path.dirname(bi.__file__))

    def open_path(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        if not self._confirm_discard():
            return
        with open(path, encoding="utf-8") as fh:
            self.editor.setPlainText(fh.read())
        self.path = path
        self.read_only = self._is_builtin(path)
        self.editor.setReadOnly(self.read_only)
        self.editor.document().setModified(False)
        self.editor.set_error_line(None)
        self._update_title()
        self.console.appendPlainText(
            f"opened {path}" + ("  — built-in modules are read-only; use 'Duplicate as my module'" if self.read_only else "")
        )

    def _update_title(self) -> None:
        name = os.path.basename(self.path) if self.path else "untitled"
        mod = " •" if self.editor.document().isModified() else ""
        ro = "  (read-only)" if self.read_only else ""
        self.title.setText(f"{name}{mod}{ro}")
        self.btn_save.setEnabled(not self.read_only)
        self.btn_apply.setEnabled(not self.read_only)

    def _confirm_discard(self) -> bool:
        if not self.editor.document().isModified() or self.read_only:
            return True
        r = QtWidgets.QMessageBox.question(
            self, "opngx", "Discard unsaved changes?",
            QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
        )
        return r == QtWidgets.QMessageBox.Discard

    def new_module(self, name: Optional[str] = None) -> Optional[str]:
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "New analysis module", "module name (lowercase, digits, _):", text="my_module"
            )
            if not ok:
                return None
        name = "".join(ch for ch in name.strip().lower().replace(" ", "_") if ch.isalnum() or ch == "_")
        if not name or not name[0].isalpha():
            QtWidgets.QMessageBox.warning(self, "opngx", "A module name must start with a letter.")
            return None
        path = os.path.join(oa.user_modules_dir(create=True), f"{name}.py")
        if os.path.exists(path):
            QtWidgets.QMessageBox.warning(self, "opngx", f"{path} already exists.")
            return None
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(oa.template(name, name.replace("_", " ").capitalize()))
        self.refresh_files()
        self.editor.document().setModified(False)
        self.open_path(path)
        self.console.appendPlainText(f"created {path} from the template")
        return path

    def duplicate(self) -> Optional[str]:
        if not self.path:
            return None
        src = self.editor.toPlainText()
        base = os.path.splitext(os.path.basename(self.path))[0]
        name = f"my_{base}" if not base.startswith("my_") else f"{base}_copy"
        path = os.path.join(oa.user_modules_dir(create=True), f"{name}.py")
        i = 2
        while os.path.exists(path):
            path = os.path.join(oa.user_modules_dir(), f"{name}{i}.py")
            i += 1
        stem = os.path.splitext(os.path.basename(path))[0]
        import re

        # rename the module id so it does not clash with the original
        src = re.sub(r'(^\s*name\s*=\s*)["\'][^"\']*["\']', lambda m: f'{m.group(1)}"{stem}"', src, count=1, flags=re.M)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        self.refresh_files()
        self.editor.document().setModified(False)
        self.open_path(path)
        self.console.appendPlainText(f"duplicated as {path} (module name '{stem}')")
        return path

    def open_dialog(self) -> None:
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open module", oa.user_modules_dir(create=True), "Python (*.py)")
        if p:
            self.open_path(p)

    def open_folder(self) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(oa.user_modules_dir(create=True)))

    def delete_current(self) -> None:
        if not self.path or self.read_only:
            return
        r = QtWidgets.QMessageBox.question(self, "opngx", f"Delete {self.path}?")
        if r != QtWidgets.QMessageBox.Yes:
            return
        os.remove(self.path)
        self.console.appendPlainText(f"deleted {self.path}")
        self.path = None
        self.editor.clear()
        self.editor.document().setModified(False)
        self._update_title()
        self.refresh_files()
        self.modulesChanged.emit()

    # -------------------------------------------------------------- actions
    def save(self) -> bool:
        if self.read_only:
            self.console.appendPlainText("built-in modules are read-only — use 'Duplicate as my module'")
            return False
        if not self.path:
            name, ok = QtWidgets.QInputDialog.getText(self, "Save module", "file name:", text="my_module.py")
            if not ok or not name:
                return False
            if not name.endswith(".py"):
                name += ".py"
            self.path = os.path.join(oa.user_modules_dir(create=True), name)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(self.editor.toPlainText())
        self.editor.document().setModified(False)
        self._update_title()
        self.console.appendPlainText(f"saved {self.path}")
        self.refresh_files()
        return True

    def _source_file(self) -> str:
        """The current text as a file to load (a temp copy when it differs
        from the saved file). Compare TEXT, not the modified flag: a
        programmatic setPlainText() clears that flag, and validation then
        silently checked the old file instead of what is on screen."""
        text = self.editor.toPlainText()
        if self.path and os.path.isfile(self.path):
            with open(self.path, encoding="utf-8") as fh:
                if fh.read() == text:
                    return self.path
        fd, tmp = tempfile.mkstemp(suffix=".py", prefix="opngx_mod_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        return tmp

    def validate(self) -> bool:
        path = self._source_file()
        self.console.appendPlainText(f"— validate {os.path.basename(self.path or 'untitled')} —")
        v = oa.validate_file(path)
        self.console.appendPlainText("\n".join(v.messages))
        self.console.appendPlainText("VALID ✓" if v.ok else "NOT VALID ✗")
        self._mark_error("\n".join(v.messages), path)
        if path != self.path:
            os.unlink(path)
        return v.ok

    def _mark_error(self, text: str, path: str) -> None:
        import re

        line = None
        for m in re.finditer(r'File "([^"]+)", line (\d+)', text):
            if os.path.abspath(m.group(1)) == os.path.abspath(path):
                line = int(m.group(2))
        if line is None:
            m = re.search(r"line (\d+)", text)
            line = int(m.group(1)) if (m and "SyntaxError" in text) else None
        self.editor.set_error_line(line)

    def test_run(self, frames: int = 500) -> Optional[oa.AnalysisRun]:
        meta = getattr(self.studio, "meta", None)
        if meta is None:
            self.console.appendPlainText("load a recording in the Extract tab to test on real frames")
            return None
        path = self._source_file()
        infos = oa.load_file(path)
        bad = [i for i in infos if not i.ok]
        if bad or not infos:
            self.console.appendPlainText("\n".join(f"✗ {i.name}: {i.error}" for i in bad))
            self._mark_error("\n".join(i.error for i in bad), path)
            if path != self.path:
                os.unlink(path)
            return None
        if path != self.path:
            os.unlink(path)
        self.console.appendPlainText(f"— test {', '.join(i.name for i in infos)} on {os.path.basename(meta.bin_path)}, first {frames} frames —")
        try:
            run = oa.analyze(meta.bin_path, [i.cls for i in infos], meta=meta, count=frames,
                             log=lambda s: self.console.appendPlainText("  " + s))
        except Exception as exc:  # noqa: BLE001
            self.console.appendPlainText(f"✗ {exc}")
            return None
        for n, err in run.errors.items():
            self.console.appendPlainText(f"✗ {err}\n{err.tb}")
            self._mark_error(err.tb, self.path or "")
        for n, res in run.results.items():
            cols = [c for c in res.columns if c not in ("frame", "timestamp_raw", "time_s")]
            self.console.appendPlainText(
                f"✓ {n}: {len(res)} rows in {run.seconds:.2f}s → {cols}"
            )
            for k in cols[:6]:
                a = res.columns[k].astype(float)
                if np.isfinite(a).any():
                    self.console.appendPlainText(
                        f"    {k}: min {np.nanmin(a):.4g}  mean {np.nanmean(a):.4g}  max {np.nanmax(a):.4g}"
                    )
            if res.summary:
                self.console.appendPlainText(f"    summary: {json.dumps(res.metadata()['summary'])[:400]}")
        if not run.errors:
            self.editor.set_error_line(None)
        return run

    def save_and_reload(self) -> None:
        if not self.save():
            return
        if self.validate():
            self.modulesChanged.emit()
            self.console.appendPlainText("module list reloaded — it is ready in the Analyze tab")

    def show_api(self) -> None:
        from opngx.analysis import base

        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Analysis module API")
        scaling.fit_to_screen(d, 760, 620)
        v = QtWidgets.QVBoxLayout(d)
        tb = QtWidgets.QPlainTextEdit(base.__doc__ or "")
        tb.setReadOnly(True)
        tb.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        v.addWidget(tb)
        d.show()
        self._api_dialog = d
