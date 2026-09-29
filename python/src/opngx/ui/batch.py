"""Batch studio window + ROI crop editor.

The user field report was twofold:
  1. batch runs did not honour gamma/contrast (fixed in the engine, v1.7.0)
  2. during a batch there was no way to SEE what each folder produced — the
     single frame viewer only ever showed one recording at a time, and the
     info table showed just a count of .bin files.

`BatchWindow` gives every recording its own card: a real decoded frame
rendered through the transform that recording will actually get, its crop
drawn in context, geometry, frame count, fps, the B/C/G in force, a
per-recording status line and a per-recording progress bar.

`CropEditor` is the interactive region-of-interest picker: drag, move or
resize a rectangle over a real decoded frame (or type x/y/w/h), and apply
it to this recording only or to every recording it fits.

cycle 23 (v1.8.0) fixes, all reproduced first:
  * the batch window copied the studio's settings once, when it opened, so
    a gamma/contrast change made afterwards never reached "Extract all";
    it now asks the studio for the live settings at start;
  * reference mode now means "each recording's own .footage B/C/G" — one
    recording's (or the hard-coded 49/18/1) values were forced on all;
  * Cancel in the crop editor still applied the crop (to EVERY recording,
    since "apply to all" defaulted on);
  * the w/h spin boxes were locked to the full frame (`_spin` arguments in
    the wrong order), the drag rectangle ignored the image's scale and
    offset, and the "selection" was dimmed like everything else;
  * apply-to-all pushed a crop onto recordings it did not fit, which then
    failed at extraction time.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from opngx.layout import batch_out_dir, run_out_dir  # noqa: F401  (re-export)

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal

    _QT = True
except Exception:  # pragma: no cover
    _QT = False


def transform_label(meta, settings: dict[str, Any]) -> str:
    """Human description of the B/C/G a recording will be extracted with."""
    from opngx.video import resolve_transform

    mode = settings.get("mode", "reference")
    if meta is None:
        return f"{mode}"
    try:
        b, c, g = resolve_transform(
            meta,
            mode,
            settings.get("brightness"),
            settings.get("contrast"),
            settings.get("gamma"),
        )
    except Exception:  # noqa: BLE001
        return f"{mode}"
    src = {
        "reference": "from .footage",
        "raw": "identity",
        "custom": "custom",
    }.get(mode, mode)
    if mode == "reference" and settings.get("brightness") is not None:
        src = "reference, overridden"
    return f"B {b:g} · C {c:g} · γ {g:g}  ({src})"


@dataclass
class BatchItem:
    """One recording in the batch, with everything its card needs."""

    bin_path: str
    footage_path: Optional[str] = None
    name: str = ""
    width: int = 0
    height: int = 0
    frames: int = 0
    framerate: float = 0.0
    b_from_sidecar: float = 0.0
    c_from_sidecar: float = 0.0
    g_from_sidecar: float = 1.0
    crop: Optional[tuple[int, int, int, int]] = None
    out_dir: str = ""
    status: str = "queued"
    frames_done: int = 0
    frames_total: int = 0
    seconds: float = 0.0
    error: str = ""
    thumb: Optional["QtGui.QImage"] = None
    thumb_raw: Any = None  # (h, w) uint8 sensor bytes of the preview frame
    meta: Any = None
    extras: dict = field(default_factory=dict)

    @property
    def out_size(self) -> str:
        """Encoded size after the crop is applied (what the files will be)."""
        if self.crop and self.width and self.height:
            x, y, w, h = self.crop
            return f"{self.width} × {self.height} → {w} × {h} px"
        if self.width and self.height:
            return f"{self.width} × {self.height} px"
        return "? × ? px"

    @property
    def crop_label(self) -> str:
        if not self.crop:
            return "full frame"
        x, y, w, h = self.crop
        return f"crop {x},{y} {w}×{h}"

    @property
    def done(self) -> bool:
        return self.status in ("done", "cancelled", "failed")

    def crop_fits(self, crop: Optional[tuple[int, int, int, int]]) -> bool:
        from opngx.extractor import normalize_crop

        if crop is None:
            return True
        try:
            normalize_crop(crop, self.width, self.height)
            return True
        except ValueError:
            return False


def scan_batch(root: str) -> list[str]:
    """Every .bin under `root`: one level of nesting plus loose files.

    Identical discovery order to the studio's Batch scope and the engine's
    `batch` subcommand, so all three agree on what a batch contains.
    """
    import glob

    bins = sorted(glob.glob(os.path.join(root, "*", "*.bin")))
    bins += sorted(glob.glob(os.path.join(root, "*.bin")))
    return bins


def render_thumb(item: BatchItem, settings: Optional[dict[str, Any]] = None):
    """The preview frame through the transform this recording will get."""
    if item.thumb_raw is None or item.meta is None:
        return item.thumb
    import numpy as np

    from opngx.quality import build_lut
    from opngx.video import resolve_transform

    s = settings or {"mode": "raw"}
    b, c, g = resolve_transform(
        item.meta, s.get("mode", "raw"), s.get("brightness"), s.get("contrast"), s.get("gamma")
    )
    lut = np.asarray(build_lut(b, c, g), dtype=np.uint8)
    out = np.ascontiguousarray(np.take(lut, item.thumb_raw))
    h, w = out.shape
    return QtGui.QImage(out.data, w, h, w, QtGui.QImage.Format_Grayscale8).copy()


def make_item(bin_path: str, settings: Optional[dict[str, Any]] = None) -> BatchItem:
    """Probe one recording into a BatchItem (thumbnail included)."""
    import numpy as np

    import opngx

    item = BatchItem(bin_path=bin_path, name=os.path.basename(bin_path))
    sidecar = os.path.splitext(bin_path)[0] + ".footage"
    try:
        m = opngx.probe(bin_path, sidecar if os.path.exists(sidecar) else None)
    except Exception as exc:  # noqa: BLE001
        item.status = "failed"
        item.error = str(exc)
        return item
    item.meta = m
    item.footage_path = m.footage_path
    item.width = int(m.width or 0)
    item.height = int(m.height or 0)
    item.frames = int(m.capacity_frames or 0)
    item.framerate = float(getattr(m, "effective_fps_us", 0) or m.framerate or 0)
    item.b_from_sidecar = float(m.brightness)
    item.c_from_sidecar = float(m.contrast)
    item.g_from_sidecar = float(m.gamma)
    # a real decoded frame, not a placeholder: the user asked to SEE the
    # images each folder produces, so the card shows an actual frame.
    if item.frames > 0 and item.width > 0 and item.height > 0:
        try:
            mid = item.frames // 2
            buf = opngx.read_frame_gray(bin_path, m, mid, mode="raw")
            item.thumb_raw = np.frombuffer(buf, dtype=np.uint8).reshape(
                item.height, item.width
            )
            item.extras["thumb_frame"] = mid
            if _QT:
                item.thumb = render_thumb(item, settings)
        except Exception as exc:  # noqa: BLE001
            item.extras["thumb_error"] = str(exc)
    return item


def make_items(bins: list[str], settings: Optional[dict[str, Any]] = None) -> list[BatchItem]:
    """Probe every recording concurrently (probing is I/O-bound: one XML
    parse plus two seeks per file), keeping discovery order."""
    if len(bins) <= 1:
        return [make_item(b, settings) for b in bins]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(8, len(bins))) as ex:
        return list(ex.map(lambda b: make_item(b, settings), bins))


if not _QT:  # pragma: no cover
    BatchWindow = None  # type: ignore[assignment]
    CropEditor = None  # type: ignore[assignment]
else:
    from opngx.ui import scaling, themes
    from opngx.ui.frameview import FrameView, gray_to_qimage

    def _spin(lo: int, hi: int, val: int) -> "QtWidgets.QSpinBox":
        s = QtWidgets.QSpinBox()
        s.setRange(int(lo), max(int(hi), int(lo)))
        s.setValue(int(val))
        s.setKeyboardTracking(False)
        return s

    ASPECTS = {"free": None, "1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "16:9": 16 / 9, "3:2": 3 / 2}

    class CropEditor(QtWidgets.QDialog):
        """The region-of-interest editor (v2.0).

        Drag to draw · drag inside to move · drag an edge/corner to resize ·
        wheel to zoom · right/middle-drag to pan · arrows nudge 1 px (Shift
        10 px, Alt resizes) · Ctrl+Z / Ctrl+Y undo/redo. Optional: scrub
        through the recording (`frame_fn`), auto-crop around the bright
        spot or the tracked path (`track_fn`), aspect locks, size snapping,
        auto levels, named presets. Pixels are selected, never resampled.
        """

        cropChanged = Signal(object)

        def __init__(
            self,
            parent: Optional[QtWidgets.QWidget],
            image: "QtGui.QImage",
            current: Optional[tuple[int, int, int, int]],
            frame_size: tuple[int, int],
            transform: Optional[Callable[["QtGui.QImage"], "QtGui.QImage"]] = None,
            *,
            apply_all_default: bool = False,
            show_apply_all: bool = True,
            apply_all_text: str = "Apply this crop to every recording in the batch it fits",
            frame_fn: Optional[Callable[[int], "QtGui.QImage"]] = None,
            n_frames: int = 0,
            frame_index: int = 0,
            track_fn: Optional[Callable[[], Optional[tuple]]] = None,
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle("Crop editor — region of interest")
            scaling.fit_to_screen(self, 1040, 760)
            self._fw, self._fh = int(frame_size[0]), int(frame_size[1])
            self._transform = transform
            self._frame_fn = frame_fn
            self._track_fn = track_fn
            self._initial = current
            self._undo: list = []
            self._redo: list = []
            self._raw_img = image
            self._img = self._display(image)
            self._qs = QtCore.QSettings("opngx", "opngx-studio")

            root = QtWidgets.QVBoxLayout(self)
            # ---- toolbar row 1: view
            tb = QtWidgets.QHBoxLayout()
            def tool(text, tip, fn, name="compact"):
                b = QtWidgets.QPushButton(text)
                b.setObjectName(name)
                b.setToolTip(tip)
                b.clicked.connect(fn)
                tb.addWidget(b)
                return b
            tool("Fit", "zoom to fit (middle/right double-click)", lambda: self.view.reset_view())
            tool("1:1", "one screen pixel per sensor pixel", self._zoom_1)
            tool("4×", "4× zoom on the selection", lambda: self._zoom_sel(4))
            self.zoom_lbl = QtWidgets.QLabel("")
            self.zoom_lbl.setObjectName("hint")
            tb.addWidget(self.zoom_lbl)
            tb.addSpacing(12)
            self.cb_levels = QtWidgets.QCheckBox("auto levels")
            self.cb_levels.setToolTip("stretch the display contrast (display only — never changes the crop)")
            self.cb_levels.toggled.connect(self._refresh_image)
            tb.addWidget(self.cb_levels)
            tb.addStretch(1)
            self.b_undo = tool("↶", "undo (Ctrl+Z)", self.undo, "icon")
            self.b_redo = tool("↷", "redo (Ctrl+Y)", self.redo, "icon")
            root.addLayout(tb)

            split = QtWidgets.QSplitter(Qt.Horizontal)
            left = QtWidgets.QWidget()
            lv = QtWidgets.QVBoxLayout(left)
            lv.setContentsMargins(0, 0, 0, 0)
            self.view = FrameView(self, editable=True)
            self.view.setImage(self._img)
            self.view.selectionChanged.connect(self._on_canvas_sel)
            self.view.selectionFinished.connect(lambda s_: self._push_undo())
            self.view.hovered.connect(self._on_hover)
            self.view.zoomChanged.connect(lambda z: self.zoom_lbl.setText(f"{z:.2g} px/px"))
            lv.addWidget(self.view, 1)
            self.frame_row = QtWidgets.QHBoxLayout()
            self.frame_slider = QtWidgets.QSlider(Qt.Horizontal)
            self.frame_slider.setRange(0, max(0, int(n_frames) - 1))
            self.frame_slider.setValue(int(frame_index))
            self.frame_slider.valueChanged.connect(self._on_frame)
            self.frame_lbl = QtWidgets.QLabel(f"frame {frame_index:,}")
            self.frame_lbl.setObjectName("hint")
            self.frame_row.addWidget(QtWidgets.QLabel("frame"))
            self.frame_row.addWidget(self.frame_slider, 1)
            self.frame_row.addWidget(self.frame_lbl)
            lv.addLayout(self.frame_row)
            for i in range(self.frame_row.count()):
                w_ = self.frame_row.itemAt(i).widget()
                if w_ is not None:
                    w_.setVisible(frame_fn is not None and n_frames > 1)
            split.addWidget(left)

            # ---- side panel
            side = QtWidgets.QWidget()
            sv = QtWidgets.QVBoxLayout(side)
            sv.setContentsMargins(6, 0, 0, 0)
            form = QtWidgets.QGridLayout()
            self.x_spin = _spin(0, max(self._fw - 1, 0), 0)
            self.y_spin = _spin(0, max(self._fh - 1, 0), 0)
            self.w_spin = _spin(1, max(self._fw, 1), self._fw)
            self.h_spin = _spin(1, max(self._fh, 1), self._fh)
            for r_, (lbl, w_) in enumerate((("x", self.x_spin), ("y", self.y_spin), ("w", self.w_spin), ("h", self.h_spin))):
                lab = QtWidgets.QLabel(lbl)
                lab.setObjectName("fieldlabel")
                form.addWidget(lab, r_, 0)
                form.addWidget(w_, r_, 1)
                w_.valueChanged.connect(self._on_spin)
            sv.addLayout(form)
            g2 = QtWidgets.QGridLayout()
            lab = QtWidgets.QLabel("aspect")
            lab.setObjectName("fieldlabel")
            self.cmb_aspect = QtWidgets.QComboBox()
            self.cmb_aspect.addItems(list(ASPECTS))
            self.cmb_aspect.setToolTip("lock the width:height ratio while drawing and typing")
            self.cmb_aspect.currentIndexChanged.connect(lambda *_: self._set_sel(self._sel, push=True))
            g2.addWidget(lab, 0, 0)
            g2.addWidget(self.cmb_aspect, 0, 1)
            lab = QtWidgets.QLabel("snap")
            lab.setObjectName("fieldlabel")
            self.cmb_snap = QtWidgets.QComboBox()
            self.cmb_snap.addItems(["1 px", "2 px (even: MP4-friendly)", "4 px", "8 px", "16 px", "32 px"])
            self.cmb_snap.setToolTip("round the size (and origin) to a multiple of N pixels")
            self.cmb_snap.currentIndexChanged.connect(lambda *_: self._set_sel(self._sel, push=True))
            g2.addWidget(lab, 1, 0)
            g2.addWidget(self.cmb_snap, 1, 1)
            lab = QtWidgets.QLabel("margin")
            lab.setObjectName("fieldlabel")
            self.sp_margin = _spin(0, 2048, 16)
            self.sp_margin.setToolTip("padding around the spot / path for the auto-crop buttons")
            g2.addWidget(lab, 2, 0)
            g2.addWidget(self.sp_margin, 2, 1)
            sv.addLayout(g2)
            for text, tip, fn in (
                ("Full frame", "no crop", self._full),
                ("Centre 50%", "the middle half of the frame", self._center),
                ("Around bright spot", "centre on the brightest feature of this frame", self._around_spot),
                ("Around tracked path", "bounding box of the tracked trajectory + margin", self._around_path),
                ("Reset", "back to the crop this editor opened with", self._reset),
            ):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("compact")
                b.setToolTip(tip)
                b.clicked.connect(fn)
                sv.addWidget(b)
                if text == "Around tracked path":
                    self.btn_path = b
                    b.setEnabled(track_fn is not None)
            pres = QtWidgets.QHBoxLayout()
            self.cmb_preset = QtWidgets.QComboBox()
            self.cmb_preset.setToolTip("saved crops")
            self.cmb_preset.activated.connect(self._apply_preset)
            bsave = QtWidgets.QPushButton("Save…")
            bsave.setObjectName("compact")
            bsave.clicked.connect(self._save_preset)
            bdel = QtWidgets.QPushButton("✕")
            bdel.setObjectName("icon")
            bdel.setToolTip("delete this preset")
            bdel.clicked.connect(self._del_preset)
            pres.addWidget(self.cmb_preset, 1)
            pres.addWidget(bsave)
            pres.addWidget(bdel)
            lab = QtWidgets.QLabel("presets")
            lab.setObjectName("fieldlabel")
            sv.addWidget(lab)
            sv.addLayout(pres)
            self.info = QtWidgets.QLabel()
            self.info.setObjectName("hint")
            self.info.setWordWrap(True)
            sv.addWidget(self.info)
            self.preview = FrameView(self, placeholder="preview")
            scaling.fix(self.preview, "setMinimumHeight", 110)
            sv.addWidget(self.preview, 1)
            scaling.fix(side, "setMinimumWidth", 250)
            split.addWidget(side)
            split.setStretchFactor(0, 3)
            split.setStretchFactor(1, 1)
            root.addWidget(split, 1)

            hint = QtWidgets.QLabel(
                "Drag to draw · drag inside to move · drag an edge or corner to resize · wheel zooms · "
                "right-drag pans · arrows nudge (Shift ×10, Alt resizes). Pixels are selected, never resampled."
            )
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            root.addWidget(hint)
            self.apply_all = QtWidgets.QCheckBox(apply_all_text)
            self.apply_all.setChecked(bool(apply_all_default))
            self.apply_all.setVisible(show_apply_all)
            root.addWidget(self.apply_all)
            btns = QtWidgets.QHBoxLayout()
            btns.addStretch(1)
            cancel = QtWidgets.QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            ok = QtWidgets.QPushButton("Use this crop")
            ok.setObjectName("accent")
            ok.setDefault(True)
            ok.clicked.connect(self._accept)
            btns.addWidget(cancel)
            btns.addWidget(ok)
            root.addLayout(btns)

            for seq, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo)):
                sc = QtGui.QShortcut(QtGui.QKeySequence(seq), self)
                sc.activated.connect(fn)
            self._sel: tuple[int, int, int, int] = (0, 0, self._fw, self._fh)
            self._load_presets()
            self._reset()
            self._undo.clear()
            self._update_undo()

        # ---------------------------------------------------------- image --
        def _display(self, img):
            if img is None:
                return None
            if self._transform is not None:
                try:
                    img = self._transform(img)
                except Exception:  # noqa: BLE001
                    pass
            return img

        def _refresh_image(self) -> None:
            img = self._display(self._raw_img)
            if img is not None and self.cb_levels.isChecked():
                import numpy as np

                w, h = img.width(), img.height()
                g = img.convertToFormat(QtGui.QImage.Format_Grayscale8)
                a = np.frombuffer(g.constBits(), np.uint8, count=g.bytesPerLine() * h).reshape(h, g.bytesPerLine())[:, :w]
                lo, hi = np.percentile(a, (1, 99.5))
                if hi > lo:
                    s_ = np.clip((a.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
                    img = gray_to_qimage(s_)
            self._img = img
            self.view.setImage(img)
            self._render_preview()

        def _on_frame(self, i: int) -> None:
            if self._frame_fn is None:
                return
            try:
                self._raw_img = self._frame_fn(int(i))
            except Exception as exc:  # noqa: BLE001
                self.info.setText(f"cannot decode frame {i}: {exc}")
                return
            self.frame_lbl.setText(f"frame {i:,}")
            self._refresh_image()

        def _zoom_1(self) -> None:
            t_, s_ = self.view._target()
            if s_ > 0:
                self.view.set_zoom(self.view._zoom / s_)

        def _zoom_sel(self, z: float) -> None:
            x, y, w, h = self._sel
            self.view.reset_view()
            t_, s_ = self.view._target()
            if s_ > 0:
                self.view.set_zoom(z / s_)
            self.view.center_on(x + w / 2, y + h / 2)

        # ---------------------------------------------------- constraints --
        def _snap(self) -> int:
            return (1, 2, 4, 8, 16, 32)[max(0, self.cmb_snap.currentIndex())]

        def _constrain(self, sel, anchor: str = "tl") -> tuple[int, int, int, int]:
            x, y, w, h = (int(v) for v in sel)
            fw, fh = self._fw, self._fh
            x = max(0, min(x, fw - 1))
            y = max(0, min(y, fh - 1))
            w = max(1, min(w if w > 0 else fw - x, fw - x))
            h = max(1, min(h if h > 0 else fh - y, fh - y))
            ar = ASPECTS.get(self.cmb_aspect.currentText())
            if ar:
                # keep the larger dimension the user gave, shrink the other
                if w / h > ar:
                    w = max(1, round(h * ar))
                else:
                    h = max(1, round(w / ar))
            n = self._snap()
            if n > 1:
                w = max(n, w // n * n) if fw >= n else w
                h = max(n, h // n * n) if fh >= n else h
                w = min(w, (fw - x) // n * n or w)
                h = min(h, (fh - y) // n * n or h)
            if x + w > fw:
                x = max(0, fw - w)
            if y + h > fh:
                y = max(0, fh - h)
            return (x, y, max(1, min(w, fw)), max(1, min(h, fh)))

        # ------------------------------------------------------ selection --
        def _set_sel(self, sel, *, from_canvas=False, push=False) -> None:
            if push:
                self._push_undo()
            self._sel = self._constrain(sel)
            x, y, w, h = self._sel
            for spin, val in ((self.x_spin, x), (self.y_spin, y), (self.w_spin, w), (self.h_spin, h)):
                spin.blockSignals(True)
                spin.setValue(int(val))
                spin.blockSignals(False)
            if not from_canvas or self._sel != tuple(int(v) for v in sel):
                self.view.setSelection(self._sel)
            self._render_preview()

        def _push_undo(self) -> None:
            if not self._undo or self._undo[-1] != self._sel:
                self._undo.append(self._sel)
                self._redo.clear()
                del self._undo[:-200]
            self._update_undo()

        def _update_undo(self) -> None:
            self.b_undo.setEnabled(bool(self._undo))
            self.b_redo.setEnabled(bool(self._redo))

        def undo(self) -> None:
            if self._undo:
                self._redo.append(self._sel)
                self._set_sel(self._undo.pop())
            self._update_undo()

        def redo(self) -> None:
            if self._redo:
                self._undo.append(self._sel)
                self._set_sel(self._redo.pop())
            self._update_undo()

        def _on_canvas_sel(self, sel) -> None:
            self._set_sel(tuple(int(v) for v in sel), from_canvas=True)

        def _on_spin(self) -> None:
            self._set_sel(
                (self.x_spin.value(), self.y_spin.value(), self.w_spin.value(), self.h_spin.value()),
                push=True,
            )

        def _on_hover(self, x: int, y: int) -> None:
            if x < 0 or self._img is None:
                self._render_info()
                return
            v = QtGui.qGray(self._img.pixel(x, y))
            self._render_info(f"\ncursor ({x}, {y}) = {v}")

        def _full(self) -> None:
            self._set_sel((0, 0, self._fw, self._fh), push=True)

        def _center(self) -> None:
            w = max(1, self._fw // 2)
            h = max(1, self._fh // 2)
            self._set_sel(((self._fw - w) // 2, (self._fh - h) // 2, w, h), push=True)

        def _reset(self) -> None:
            self._set_sel(self._initial or (0, 0, self._fw, self._fh), push=bool(self._undo))

        def _around_spot(self) -> None:
            import numpy as np

            from opngx.analysis.builtin.motion_tracking import MotionTracking

            img = self._raw_img
            if img is None:
                return
            g = img.convertToFormat(QtGui.QImage.Format_Grayscale8)
            w, h = g.width(), g.height()
            a = np.ascontiguousarray(
                np.frombuffer(g.constBits(), np.uint8, count=g.bytesPerLine() * h).reshape(h, g.bytesPerLine())[:, :w]
            )[None]
            # the real tracker, not just the brightest block: for a ring the
            # brightest block sits on the rim, not at the centre
            mt = MotionTracking()
            p = MotionTracking.resolve_params({})
            method = "circle" if mt._looks_like_ring(a, p) else "centroid"
            cx, cy, r, _n, good = mt._measure(a, p, method)[:5]
            if not good[0]:
                self.info.setText("no bright feature found in this frame")
                return
            m = self.sp_margin.value()
            rad = float(r[0]) if method == "circle" and np.isfinite(r[0]) else 8.0
            x, y, sw, sh = self._sel
            if (sw, sh) == (self._fw, self._fh):
                sw = sh = int(2 * (rad + m)) + 1
            self._set_sel((int(round(cx[0] - sw / 2)), int(round(cy[0] - sh / 2)), sw, sh), push=True)

        def _around_path(self) -> None:
            if self._track_fn is None:
                return
            bb = self._track_fn()
            if not bb:
                self.info.setText("no tracked path yet — run motion tracking in the Analyze tab")
                return
            x0, y0, x1, y1 = bb
            m = self.sp_margin.value()
            import math as _m

            self._set_sel((_m.floor(x0) - m, _m.floor(y0) - m, _m.ceil(x1 - x0) + 2 * m + 1, _m.ceil(y1 - y0) + 2 * m + 1), push=True)

        # --------------------------------------------------------- presets --
        def _presets(self) -> dict:
            import json

            try:
                return json.loads(self._qs.value("crop/presets", "{}") or "{}")
            except (TypeError, ValueError):
                return {}

        def _load_presets(self) -> None:
            self.cmb_preset.clear()
            pr = self._presets()
            self.cmb_preset.addItem("— choose —")
            for name, v in sorted(pr.items()):
                self.cmb_preset.addItem(f"{name}  ({v[0]},{v[1]} {v[2]}×{v[3]})", name)

        def _apply_preset(self, i: int) -> None:
            name = self.cmb_preset.itemData(i)
            v = self._presets().get(name)
            if v:
                self._set_sel(tuple(v), push=True)

        def _save_preset(self) -> None:
            import json

            name, ok = QtWidgets.QInputDialog.getText(self, "Save crop", "preset name:", text="roi")
            if not ok or not name.strip():
                return
            pr = self._presets()
            pr[name.strip()] = list(self._sel)
            self._qs.setValue("crop/presets", json.dumps(pr))
            self._load_presets()

        def _del_preset(self) -> None:
            import json

            name = self.cmb_preset.currentData()
            if not name:
                return
            pr = self._presets()
            pr.pop(name, None)
            self._qs.setValue("crop/presets", json.dumps(pr))
            self._load_presets()

        # ------------------------------------------------------------ misc --
        def keyPressEvent(self, ev) -> None:  # noqa: N802
            k = ev.key()
            d = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(k)
            if d and not isinstance(self.focusWidget(), (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
                step = 10 if ev.modifiers() & Qt.ShiftModifier else 1
                x, y, w, h = self._sel
                if ev.modifiers() & Qt.AltModifier:
                    w, h = w + d[0] * step, h + d[1] * step
                else:
                    x, y = x + d[0] * step, y + d[1] * step
                self._set_sel((x, y, w, h), push=True)
                return
            super().keyPressEvent(ev)

        def _render_info(self, tail: str = "") -> None:
            x, y, w, h = self._sel
            stats = ""
            if self._raw_img is not None:
                try:
                    sub = self._raw_img.copy(x, y, w, h).convertToFormat(QtGui.QImage.Format_Grayscale8)
                    import numpy as np

                    a = np.frombuffer(sub.constBits(), np.uint8, count=sub.bytesPerLine() * h).reshape(h, sub.bytesPerLine())[:, :w]
                    stats = f"\nregion: mean {a.mean():.1f} · min {a.min()} · max {a.max()}"
                except Exception:  # noqa: BLE001
                    stats = ""
            odd = "\nodd size: an MP4 render pads one black row/column" if (w % 2 or h % 2) else ""
            self.info.setText(
                f"output {w} × {h} px ({w * h:,} px, {100.0 * w * h / max(1, self._fw * self._fh):.1f}% of the frame)"
                f"\ncolumns {x}–{x + w - 1}, rows {y}–{y + h - 1}{stats}{odd}{tail}"
            )

        def _render_preview(self) -> None:
            x, y, w, h = self._sel
            self.preview.setImage(self._img.copy(x, y, w, h) if self._img else None)
            self._render_info()

        def _accept(self) -> None:
            self.cropChanged.emit(self.selection())
            self.accept()

        def selection(self) -> Optional[tuple[int, int, int, int]]:
            if self._sel == (0, 0, self._fw, self._fh):
                return None
            return self._sel

    class BatchCard(QtWidgets.QFrame):
        """One recording: frame (crop drawn in context), facts, transform,
        crop state, status, progress."""

        cropRequested = Signal(object)  # BatchItem
        previewRequested = Signal(object)  # BatchItem -> open in the studio
        selected = Signal(object)  # BatchItem -> show in the Preview pane

        def __init__(self, item: BatchItem) -> None:
            super().__init__()
            self.setObjectName("card")
            self.item = item
            v = QtWidgets.QVBoxLayout(self)
            scaling.fix(v, "setContentsMargins", 10, 8, 10, 10)
            scaling.fix(v, "setSpacing", 6)

            self.thumb = FrameView(self, placeholder="no preview")
            scaling.fix(self.thumb, "setFixedHeight", 150)
            scaling.fix(self, "setMinimumWidth", 260)
            self.thumb.setCursor(Qt.PointingHandCursor)
            self.thumb.setImage(item.thumb)
            self.thumb.setSelection(item.crop)
            v.addWidget(self.thumb)

            title = QtWidgets.QLabel(item.name)
            title.setObjectName("cardtitle")
            title.setToolTip(item.bin_path)
            v.addWidget(title)

            self.facts = QtWidgets.QLabel()
            self.facts.setObjectName("hint")
            self.facts.setWordWrap(True)  # "256 × 300 → … · fps" was clipped
            v.addWidget(self.facts)

            self.xform_lbl = QtWidgets.QLabel()
            self.xform_lbl.setObjectName("hint")
            v.addWidget(self.xform_lbl)

            self.crop_lbl = QtWidgets.QLabel()
            self.crop_lbl.setObjectName("hint")
            v.addWidget(self.crop_lbl)

            self.status_lbl = QtWidgets.QLabel()
            self.status_lbl.setObjectName("hint")
            self.status_lbl.setWordWrap(True)
            v.addWidget(self.status_lbl)

            self.bar = QtWidgets.QProgressBar()
            scaling.fix(self.bar, "setFixedHeight", 12)
            self.bar.setRange(0, 100)
            v.addWidget(self.bar)

            row = QtWidgets.QHBoxLayout()
            self.crop_btn = QtWidgets.QPushButton("Crop…")
            self.crop_btn.clicked.connect(lambda: self.cropRequested.emit(self.item))
            self.prev_btn = QtWidgets.QPushButton("Open in studio")
            self.prev_btn.setToolTip("Load this recording into the main window's viewer")
            self.prev_btn.clicked.connect(lambda: self.previewRequested.emit(self.item))
            row.addWidget(self.crop_btn)
            row.addWidget(self.prev_btn)
            v.addLayout(row)
            self.refresh()

        def mousePressEvent(self, ev) -> None:  # noqa: N802
            if ev.button() == Qt.LeftButton:
                self.selected.emit(self.item)
            super().mousePressEvent(ev)

        def set_selected(self, on: bool) -> None:
            self.setProperty("selected", bool(on))
            self.setStyleSheet(
                f"QFrame#card {{ border: 2px solid {themes.hexc('accent_fg')}; }}" if on else ""
            )

        def set_transform(self, settings: dict[str, Any]) -> None:
            self.item.thumb = render_thumb(self.item, settings)
            self.thumb.setImage(self.item.thumb)
            self.xform_lbl.setText(transform_label(self.item.meta, settings))

        def refresh(self) -> None:
            it = self.item
            self.facts.setText(
                f"{it.out_size} · {it.frames:,} frames"
                + (f" · {it.framerate:,.0f} fps" if it.framerate else "")
            )
            self.crop_lbl.setText(it.crop_label)
            self.thumb.setSelection(it.crop)
            colors = {
                "queued": themes.hexc("text_dim"),
                "running": themes.hexc("heading"),
                "done": themes.hexc("ok"),
                "failed": themes.hexc("err"),
                "cancelled": themes.hexc("warn"),
            }
            txt = it.status
            if it.status == "done":
                txt = f"done · {it.frames_done:,} frames in {it.seconds:.2f}s"
            elif it.status == "failed" and it.error:
                txt = f"failed · {it.error[:120]}"
            elif it.status == "running" and it.frames_total:
                txt = f"running · {it.frames_done:,}/{it.frames_total:,}"
            self.status_lbl.setText(txt)
            self.status_lbl.setStyleSheet(f"color: {colors.get(it.status, themes.hexc('text_dim'))}")
            if it.frames_total:
                self.bar.setValue(int(100 * it.frames_done / it.frames_total))
            else:
                self.bar.setValue(0)

    class Pane(QtWidgets.QDockWidget):
        """A dock pane with its own title bar: collapse, pop out into a
        separate window, full screen, hide (cycle 24)."""

        def __init__(self, title: str, name: str, parent=None) -> None:
            super().__init__(title, parent)
            self.setObjectName(name)
            self.setFeatures(
                QtWidgets.QDockWidget.DockWidgetClosable
                | QtWidgets.QDockWidget.DockWidgetMovable
                | QtWidgets.QDockWidget.DockWidgetFloatable
            )
            self._collapsed = False
            self._fs_prev_floating: Optional[bool] = None
            bar = QtWidgets.QFrame()
            bar.setObjectName("panebar")
            h = QtWidgets.QHBoxLayout(bar)
            h.setContentsMargins(8, 2, 4, 2)
            h.setSpacing(2)
            self.title_lbl = QtWidgets.QLabel(title.upper())
            self.title_lbl.setObjectName("cardtitle")
            h.addWidget(self.title_lbl, 1)

            def tool(txt, tip, fn):
                b = QtWidgets.QToolButton()
                b.setText(txt)
                b.setToolTip(tip)
                b.setAutoRaise(True)
                b.clicked.connect(fn)
                h.addWidget(b)
                return b

            self.btn_collapse = tool("▾", "Collapse / expand this pane", self.toggle_collapsed)
            self.btn_float = tool("⧉", "Pop out into its own window / dock back", self.toggle_floating)
            self.btn_full = tool("⛶", "Full screen (Esc to return)", self.toggle_fullscreen)
            tool("✕", "Hide (bring back from the View menu)", self.close)
            self.setTitleBarWidget(bar)
            esc = QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Escape), self)
            esc.setContext(Qt.WidgetWithChildrenShortcut)
            esc.activated.connect(self.leave_fullscreen)

        # ---------------------------------------------------------------
        def is_collapsed(self) -> bool:
            return self._collapsed

        def toggle_collapsed(self) -> None:
            self.set_collapsed(not self._collapsed)

        def set_collapsed(self, on: bool) -> None:
            w = self.widget()
            if w is None or on == self._collapsed:
                return
            self._collapsed = on
            w.setVisible(not on)
            self.btn_collapse.setText("▸" if on else "▾")
            if not on:
                self.visibilityChanged.emit(True)
            if on:
                self.setMaximumHeight(self.titleBarWidget().sizeHint().height() + 6)
            else:
                self.setMaximumHeight(16777215)

        def toggle_floating(self) -> None:
            self.leave_fullscreen()
            self.setFloating(not self.isFloating())
            if self.isFloating():
                self.set_collapsed(False)
                scaling.fit_to_screen(self, 900, 640)

        def toggle_fullscreen(self) -> None:
            if self.isFullScreen():
                self.leave_fullscreen()
                return
            self.set_collapsed(False)
            self._fs_prev_floating = self.isFloating()
            self.setFloating(True)
            self.showFullScreen()
            self.btn_full.setText("🗗")

        def leave_fullscreen(self) -> None:
            if not self.isFullScreen():
                return
            self.showNormal()
            self.btn_full.setText("⛶")
            if self._fs_prev_floating is False:
                self.setFloating(False)
            self._fs_prev_floating = None

    class _FlowGrid(QtWidgets.QWidget):
        """Cards in as many columns as fit (v1.8.0 hard-coded 3, which was
        cramped at 720p and left most of a 4K screen empty)."""

        def __init__(self, parent=None, min_col: int = 280) -> None:
            super().__init__(parent)
            self.setObjectName("gridhost")
            self.setStyleSheet("QWidget#gridhost { background: transparent; }")
            self.grid = QtWidgets.QGridLayout(self)
            self.grid.setSpacing(10)
            self._items: list[QtWidgets.QWidget] = []
            self._min_col = min_col
            self._cols = 0

        def set_widgets(self, widgets) -> None:
            while self.grid.count():
                self.grid.takeAt(0)
            self._items = list(widgets)
            self._cols = 0
            self._reflow()

        def resizeEvent(self, ev) -> None:  # noqa: N802
            super().resizeEvent(ev)
            self._reflow()

        def _reflow(self) -> None:
            cols = max(1, self.width() // max(1, scaling.px(self._min_col)))
            if self._items:
                cols = min(cols, len(self._items))
            if cols == self._cols:
                return
            self._cols = cols
            while self.grid.count():
                self.grid.takeAt(0)
            for n, w in enumerate(self._items):
                self.grid.addWidget(w, n // cols, n % cols, Qt.AlignTop)
            for c in range(cols):
                self.grid.setColumnStretch(c, 1)
            self.grid.setRowStretch(len(self._items) // cols + 1, 1)

    class BatchWindow(QtWidgets.QMainWindow):
        """The dedicated batch surface.

        cycle 24: a multi-pane window instead of a single scrolling grid.
        Recordings (centre) · Preview (the selected recording, large, with
        its own scrubber) · Compare (every recording side by side at the
        same point of its timeline) · Progress & log. Every pane can be
        collapsed, popped out into its own window, made full screen, hidden
        and brought back from the View menu; the arrangement is remembered.

        Settings come LIVE from the studio (`settings_fn`) so what the main
        window shows is what the batch applies.
        """

        progress = Signal(object)  # BatchItem
        finished = Signal(object)  # list[BatchItem]
        failed = Signal(str)
        log = Signal(str)

        def __init__(
            self,
            parent: Optional[QtWidgets.QWidget],
            root: str,
            out_root: str,
            settings: dict[str, Any],
            settings_fn: Optional[Callable[[], dict[str, Any]]] = None,
        ) -> None:
            super().__init__(parent)
            self.setWindowFlag(Qt.Window, True)
            self.setWindowTitle(
                f"opngx batch — {os.path.basename(root.rstrip('/')) or root}"
            )
            self.setDockOptions(
                QtWidgets.QMainWindow.AnimatedDocks
                | QtWidgets.QMainWindow.AllowNestedDocks
                | QtWidgets.QMainWindow.AllowTabbedDocks
            )
            self.root = root
            self.out_root = out_root
            self.settings = dict(settings)
            self.settings_fn = settings_fn
            self.items: list[BatchItem] = []
            self.cards: dict[str, BatchCard] = {}
            self.current: Optional[BatchItem] = None
            self._readers: dict[str, Any] = {}
            self._compare_views: dict[str, FrameView] = {}
            self._running = False
            self._cancel = False
            self._t0 = 0.0

            # ---------------- centre: recordings ----------------
            central = QtWidgets.QWidget()
            root_lay = QtWidgets.QVBoxLayout(central)
            root_lay.setContentsMargins(8, 8, 8, 4)
            top = QtWidgets.QHBoxLayout()
            self.summary = QtWidgets.QLabel()
            self.summary.setObjectName("subtitle")
            self.summary.setWordWrap(True)
            top.addWidget(self.summary, 1)
            root_lay.addLayout(top)
            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.grid_host = _FlowGrid()
            self.grid = self.grid_host.grid
            self.scroll.setWidget(self.grid_host)
            # QScrollArea.setWidget() forces autoFillBackground on, which
            # painted the platform window colour (white) behind the cards
            self.grid_host.setAutoFillBackground(False)
            self.scroll.viewport().setAutoFillBackground(False)
            root_lay.addWidget(self.scroll, 1)
            self.setCentralWidget(central)

            # ---------------- toolbar ----------------
            tb = QtWidgets.QToolBar("Batch")
            tb.setObjectName("batchtoolbar")
            tb.setMovable(False)
            self.addToolBar(Qt.TopToolBarArea, tb)
            self.go = QtWidgets.QPushButton("▶  Extract all")
            self.go.setObjectName("accent")
            self.go.clicked.connect(self.start)
            self.stop = QtWidgets.QPushButton("■  Cancel")
            self.stop.setObjectName("danger")
            self.stop.setEnabled(False)
            self.stop.clicked.connect(self.cancel)
            self.close_all = QtWidgets.QPushButton("Clear crops")
            self.close_all.clicked.connect(self.clear_crops)
            self.rescan = QtWidgets.QPushButton("Rescan")
            self.rescan.clicked.connect(lambda: self.load(self.root))
            for w in (self.go, self.stop, self.close_all, self.rescan):
                tb.addWidget(w)
            spacer = QtWidgets.QWidget()
            spacer.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
            )
            tb.addWidget(spacer)
            self.status = QtWidgets.QLabel("idle")
            self.status.setObjectName("hint")
            tb.addWidget(self.status)

            # ---------------- panes ----------------
            self._build_preview_pane()
            self._build_compare_pane()
            self._build_progress_pane()
            self.addDockWidget(Qt.RightDockWidgetArea, self.pane_preview)
            self.addDockWidget(Qt.BottomDockWidgetArea, self.pane_compare)
            self.addDockWidget(Qt.BottomDockWidgetArea, self.pane_progress)
            self.tabifyDockWidget(self.pane_compare, self.pane_progress)
            self.pane_compare.raise_()
            self._default_state = self.saveState()
            self._build_menu()

            self.progress.connect(self._on_item)
            self.finished.connect(self._on_done)
            self.failed.connect(self._on_failed)
            self.log.connect(self._append_log)
            self._render_timer = QtCore.QTimer(self)
            self._render_timer.setSingleShot(True)
            self._render_timer.setInterval(0)
            self._render_timer.timeout.connect(self._render_now)
            self._compare_timer = QtCore.QTimer(self)
            self._compare_timer.setSingleShot(True)
            self._compare_timer.setInterval(15)
            self._compare_timer.timeout.connect(self._render_compare)

            # a pane that becomes visible (shown, un-tabbed, expanded) renders
            # itself — the first render happens before the window is shown
            self.pane_compare.visibilityChanged.connect(
                lambda vis: vis and self._compare_timer.start()
            )
            self.pane_preview.visibilityChanged.connect(
                lambda vis: vis and self._render_timer.start()
            )
            self._sized = False
            self._qs = QtCore.QSettings("opngx", "opngx-studio")
            self.load(root)
            scaling.fit_to_screen(self, 1440, 900)
            self._had_state = self._restore_state()

        # ------------------------------------------------------ panes ----
        def _build_preview_pane(self) -> None:
            self.pane_preview = Pane("Preview", "pane_preview", self)
            host = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(host)
            v.setContentsMargins(8, 4, 8, 8)
            nav = QtWidgets.QHBoxLayout()
            self.pv_prev_rec = QtWidgets.QToolButton()
            self.pv_prev_rec.setText("◀")
            self.pv_prev_rec.setToolTip("Previous recording")
            self.pv_prev_rec.clicked.connect(lambda: self._step_recording(-1))
            self.pv_next_rec = QtWidgets.QToolButton()
            self.pv_next_rec.setText("▶")
            self.pv_next_rec.setToolTip("Next recording")
            self.pv_next_rec.clicked.connect(lambda: self._step_recording(+1))
            self.pv_title = QtWidgets.QLabel("select a recording")
            self.pv_title.setObjectName("cardtitle")
            nav.addWidget(self.pv_prev_rec)
            nav.addWidget(self.pv_title, 1)
            nav.addWidget(self.pv_next_rec)
            v.addLayout(nav)
            self.pv_view = FrameView(host, placeholder="click a recording card")
            self.pv_view.hovered.connect(self._on_preview_hover)
            v.addWidget(self.pv_view, 1)
            row = QtWidgets.QHBoxLayout()
            self.pv_slider = QtWidgets.QSlider(Qt.Horizontal)
            self.pv_slider.setRange(0, 0)
            self.pv_slider.valueChanged.connect(lambda _: self._render_timer.start())
            self.pv_frame = QtWidgets.QLabel("frame —")
            self.pv_frame.setObjectName("hint")
            row.addWidget(self.pv_slider, 1)
            row.addWidget(self.pv_frame)
            v.addLayout(row)
            row2 = QtWidgets.QHBoxLayout()
            self.pv_output_only = QtWidgets.QCheckBox("output only")
            self.pv_output_only.setToolTip(
                "On: exactly the cropped pixels that will be written.\n"
                "Off: the full frame with the crop outlined."
            )
            self.pv_output_only.toggled.connect(lambda _: self._render_timer.start())
            row2.addWidget(self.pv_output_only)
            self.pv_crop = QtWidgets.QPushButton("Crop…")
            self.pv_crop.clicked.connect(
                lambda: self.current is not None and self.open_crop_editor(self.current)
            )
            row2.addWidget(self.pv_crop)
            row2.addStretch(1)
            self.pv_info = QtWidgets.QLabel("")
            self.pv_info.setObjectName("hint")
            row2.addWidget(self.pv_info)
            v.addLayout(row2)
            self.pv_xform = QtWidgets.QLabel("")
            self.pv_xform.setObjectName("hint")
            self.pv_xform.setWordWrap(True)
            v.addWidget(self.pv_xform)
            self.pane_preview.setWidget(host)

        def _build_compare_pane(self) -> None:
            self.pane_compare = Pane("Compare", "pane_compare", self)
            host = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(host)
            v.setContentsMargins(8, 4, 8, 8)
            row = QtWidgets.QHBoxLayout()
            lab = QtWidgets.QLabel("position in each recording")
            lab.setObjectName("fieldlabel")
            row.addWidget(lab)
            self.cmp_slider = QtWidgets.QSlider(Qt.Horizontal)
            self.cmp_slider.setRange(0, 1000)
            self.cmp_slider.setValue(500)
            self.cmp_slider.valueChanged.connect(lambda _: self._compare_timer.start())
            row.addWidget(self.cmp_slider, 1)
            self.cmp_lbl = QtWidgets.QLabel("50.0 %")
            self.cmp_lbl.setObjectName("hint")
            row.addWidget(self.cmp_lbl)
            v.addLayout(row)
            sc = QtWidgets.QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.cmp_grid = _FlowGrid(min_col=220)
            sc.setWidget(self.cmp_grid)
            self.cmp_grid.setAutoFillBackground(False)
            sc.viewport().setAutoFillBackground(False)
            v.addWidget(sc, 1)
            self.pane_compare.setWidget(host)

        def _build_progress_pane(self) -> None:
            self.pane_progress = Pane("Progress & log", "pane_progress", self)
            host = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(host)
            v.setContentsMargins(8, 4, 8, 8)
            self.total_bar = QtWidgets.QProgressBar()
            self.total_bar.setRange(0, 1000)
            scaling.fix(self.total_bar, "setFixedHeight", 14)
            v.addWidget(self.total_bar)
            split = QtWidgets.QSplitter(Qt.Horizontal)
            self.table = QtWidgets.QTableWidget(0, 6)
            self.table.setHorizontalHeaderLabels(
                ["recording", "status", "frames", "fps", "time", "output"]
            )
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.cellClicked.connect(
                lambda r, _c: 0 <= r < len(self.items) and self.select(self.items[r])
            )
            split.addWidget(self.table)
            self.log_view = QtWidgets.QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setMaximumBlockCount(3000)
            split.addWidget(self.log_view)
            split.setStretchFactor(0, 3)
            split.setStretchFactor(1, 2)
            v.addWidget(split, 1)
            self.pane_progress.setWidget(host)

        def _build_menu(self) -> None:
            m = self.menuBar().addMenu("&View")
            for pane in (self.pane_preview, self.pane_compare, self.pane_progress):
                m.addAction(pane.toggleViewAction())
            m.addSeparator()
            collapse = QtGui.QAction("Collapse all panes", self)
            collapse.triggered.connect(lambda: [p.set_collapsed(True) for p in self.panes()])
            expand = QtGui.QAction("Expand all panes", self)
            expand.triggered.connect(lambda: [p.set_collapsed(False) for p in self.panes()])
            m.addAction(collapse)
            m.addAction(expand)
            m.addSeparator()
            self.act_full = QtGui.QAction("Full screen", self)
            self.act_full.setShortcut("F11")
            self.act_full.setCheckable(True)
            self.act_full.toggled.connect(
                lambda on: self.showFullScreen() if on else self.showNormal()
            )
            m.addAction(self.act_full)
            prev_full = QtGui.QAction("Preview pane full screen", self)
            prev_full.setShortcut("F10")
            prev_full.triggered.connect(self.pane_preview.toggle_fullscreen)
            m.addAction(prev_full)
            reset = QtGui.QAction("Reset layout", self)
            reset.triggered.connect(self.reset_layout)
            m.addAction(reset)

        def panes(self) -> list["Pane"]:
            return [self.pane_preview, self.pane_compare, self.pane_progress]

        def reset_layout(self) -> None:
            for p_ in self.panes():
                p_.leave_fullscreen()
                p_.set_collapsed(False)
            self.restoreState(self._default_state)
            for p_ in self.panes():
                p_.show()
            self._default_sizes()

        def _restore_state(self) -> bool:
            try:
                geo = self._qs.value("batch/geometry")
                st = self._qs.value("batch/state")
                if geo is not None and self.restoreGeometry(geo):
                    scaling.ensure_on_screen(self)
                if st is not None:
                    return bool(self.restoreState(st))
            except Exception:  # noqa: BLE001
                pass
            return False

        def _default_sizes(self) -> None:
            """Proportional pane sizes — docks otherwise open at their
            minimum size hint, which on a 4K screen is a sliver."""
            self.resizeDocks([self.pane_preview], [int(self.width() * 0.38)], Qt.Horizontal)
            self.resizeDocks(
                [self.pane_compare, self.pane_progress],
                [int(self.height() * 0.32)] * 2,
                Qt.Vertical,
            )

        def showEvent(self, ev) -> None:  # noqa: N802
            super().showEvent(ev)
            if not self._sized:
                self._sized = True
                if not self._had_state:
                    self._default_sizes()
                self._render_timer.start()
                self._compare_timer.start()

        def closeEvent(self, ev) -> None:  # noqa: N802
            for p_ in self.panes():
                p_.leave_fullscreen()
            try:
                self._qs.setValue("batch/geometry", self.saveGeometry())
                self._qs.setValue("batch/state", self.saveState())
            except Exception:  # noqa: BLE001
                pass
            super().closeEvent(ev)

        # ------------------------------------------------------ settings --
        def current_settings(self) -> dict[str, Any]:
            if self.settings_fn is not None:
                try:
                    self.settings = dict(self.settings_fn())
                except Exception:  # noqa: BLE001  (studio closed etc.)
                    pass
            return self.settings

        def update_settings(self, settings: Optional[dict[str, Any]] = None) -> None:
            """Re-render every card and pane for new settings (called by the
            studio whenever a quality control changes)."""
            if self._running:
                return  # a running batch keeps the settings it started with
            self.settings = dict(settings) if settings is not None else self.current_settings()
            self._update_summary()
            for it in self.items:
                card = self.cards.get(it.bin_path)
                if card is not None:
                    card.set_transform(self.settings)
                    it.out_dir = batch_out_dir(
                        self.out_root, self.root, it.bin_path, self.settings["fmt"]
                    )
            self._render_timer.start()
            self._compare_timer.start()

        def _update_summary(self) -> None:
            self.summary.setText(
                f"{len(self.items)} recording(s) · output {self.out_root} · "
                f"settings: {self._settings_line()}"
            )

        def _settings_line(self) -> str:
            s = self.settings
            mode = s.get("mode")
            bits = [f"mode={mode}"]
            if mode == "reference" and s.get("brightness") is None:
                bits.append("B/C/G from each recording's .footage")
            elif mode in ("custom", "reference"):
                b, c, g = s.get("brightness"), s.get("contrast"), s.get("gamma")
                bits.append(
                    f"B={b if b is not None else 0:g} C={c if c is not None else 0:g} "
                    f"γ={g if g is not None else 1:g}"
                )
            bits += [
                f"fmt={s.get('fmt')}",
                f"depth={s.get('bit_depth')}",
                f"ch={s.get('channels')}",
                f"jobs={s.get('jobs')}",
                f"level={s.get('level')}",
            ]
            return " · ".join(bits)

        # ---------------------------------------------------------- load --
        def load(self, root: str) -> None:
            """(Re)build the cards and panes for a mother folder."""
            self.root = root
            for card in self.cards.values():
                card.deleteLater()
            for v_ in self._compare_views.values():
                v_.parentWidget().deleteLater()
            self.cards.clear()
            self._compare_views.clear()
            self._readers.clear()
            self.items = []
            self.current = None
            bins = scan_batch(root)
            if not bins:
                self.summary.setText(f"no .bin found under {root}")
                self.grid_host.set_widgets([])
                self.cmp_grid.set_widgets([])
                self.table.setRowCount(0)
                return
            s = self.current_settings()
            self.items = make_items(bins, s)
            cards, cmp_cells = [], []
            for it in self.items:
                it.out_dir = batch_out_dir(self.out_root, root, it.bin_path, s["fmt"])
                card = BatchCard(it)
                card.set_transform(s)
                card.cropRequested.connect(self.open_crop_editor)
                card.previewRequested.connect(self.preview_item)
                card.selected.connect(self.select)
                self.cards[it.bin_path] = card
                cards.append(card)
                cell = QtWidgets.QFrame()
                cell.setObjectName("card")
                cv = QtWidgets.QVBoxLayout(cell)
                cv.setContentsMargins(6, 4, 6, 6)
                name = QtWidgets.QLabel(it.name)
                name.setObjectName("cardtitle")
                name.setToolTip(it.bin_path)
                cv.addWidget(name)
                view = FrameView(cell, placeholder="no frames")
                scaling.fix(view, "setMinimumHeight", 150)
                cv.addWidget(view, 1)
                self._compare_views[it.bin_path] = view
                cmp_cells.append(cell)
            self.grid_host.set_widgets(cards)
            self.cmp_grid.set_widgets(cmp_cells)
            self._fill_table()
            self._update_summary()
            self.select(self.items[0])
            self._compare_timer.start()

        def _fill_table(self) -> None:
            self.table.setRowCount(len(self.items))
            for r, it in enumerate(self.items):
                self._table_row(r, it)
            self.table.resizeColumnsToContents()

        def _table_row(self, r: int, it: BatchItem) -> None:
            fps = (
                f"{it.frames_done / it.seconds:,.0f}"
                if it.seconds > 0 and it.frames_done
                else ""
            )
            vals = [
                it.name,
                it.status if it.status != "failed" else f"failed: {it.error[:60]}",
                f"{it.frames_done:,}/{it.frames_total or it.frames:,}",
                fps,
                f"{it.seconds:.2f}s" if it.seconds else "",
                it.out_dir,
            ]
            for c, v_ in enumerate(vals):
                cell = self.table.item(r, c)
                if cell is None:
                    cell = QtWidgets.QTableWidgetItem()
                    self.table.setItem(r, c, cell)
                cell.setText(str(v_))

        # ------------------------------------------------------- preview --
        def _reader(self, it: BatchItem):
            r = self._readers.get(it.bin_path)
            if r is None and it.meta is not None and it.frames > 0:
                import opngx

                try:
                    r = opngx.FrameReader(it.meta)
                except Exception as exc:  # noqa: BLE001
                    self.log.emit(f"{it.name}: cannot map for preview: {exc}")
                    return None
                self._readers[it.bin_path] = r
            return r

        def _xform(self) -> dict[str, Any]:
            s = self.settings
            return dict(
                mode=s.get("mode", "reference"),
                brightness=s.get("brightness"),
                contrast=s.get("contrast"),
                gamma=s.get("gamma"),
            )

        def select(self, item: BatchItem) -> None:
            """Show one recording in the Preview pane."""
            if item not in self.items:
                return
            self.current = item
            for it in self.items:
                self.cards[it.bin_path].set_selected(it is item)
            self.pv_title.setText(item.name)
            self.pv_title.setToolTip(item.bin_path)
            self.pv_slider.blockSignals(True)
            self.pv_slider.setRange(0, max(0, item.frames - 1))
            self.pv_slider.setValue(int(item.extras.get("thumb_frame", item.frames // 2)))
            self.pv_slider.blockSignals(False)
            self.pv_crop.setEnabled(not self._running and item.meta is not None)
            row = self.items.index(item)
            self.table.selectRow(row)
            self._render_now()

        def _step_recording(self, d: int) -> None:
            if not self.items:
                return
            i = self.items.index(self.current) if self.current in self.items else 0
            self.select(self.items[(i + d) % len(self.items)])

        def _render_now(self) -> None:
            it = self.current
            if it is None:
                return
            r = self._reader(it)
            if r is None:
                self.pv_view.setImage(None)
                self.pv_view.setPlaceholder(it.error or "no decodable frames")
                return
            idx = int(self.pv_slider.value())
            try:
                arr = r.gray(idx, **self._xform())
            except Exception as exc:  # noqa: BLE001
                self.pv_view.setImage(None)
                self.pv_view.setPlaceholder(str(exc))
                return
            crop = it.crop
            if crop and self.pv_output_only.isChecked():
                x, y, w, h = crop
                arr = arr[y : y + h, x : x + w]
                self.pv_view.setSelection(None)
                self._pv_origin = (x, y)
            else:
                self.pv_view.setSelection(crop)
                self._pv_origin = (0, 0)
            self._pv_arr = arr
            self.pv_view.setImage(gray_to_qimage(arr))
            self.pv_frame.setText(f"frame {idx:,} / {max(it.frames - 1, 0):,}")
            self.pv_xform.setText(
                f"{transform_label(it.meta, self.settings)} · {it.out_size} · {it.crop_label}"
            )

        def _on_preview_hover(self, x: int, y: int) -> None:
            arr = getattr(self, "_pv_arr", None)
            it = self.current
            if x < 0 or arr is None or it is None or y >= arr.shape[0] or x >= arr.shape[1]:
                self.pv_info.setText("")
                return
            ox, oy = getattr(self, "_pv_origin", (0, 0))
            raw = ""
            r = self._readers.get(it.bin_path)
            if r is not None:
                try:
                    raw = f"raw {int(r.raw(int(self.pv_slider.value()))[oy + y, ox + x])} → "
                except Exception:  # noqa: BLE001
                    raw = ""
            self.pv_info.setText(f"({ox + x}, {oy + y})  {raw}out {int(arr[y, x])}")

        def _render_compare(self) -> None:
            if not self.pane_compare.isVisible() or self.pane_compare.is_collapsed():
                return
            pos = self.cmp_slider.value() / 1000.0
            self.cmp_lbl.setText(f"{pos * 100:.1f} %")
            xf = self._xform()
            for it in self.items:
                view = self._compare_views.get(it.bin_path)
                r = self._reader(it)
                if view is None or r is None:
                    continue
                idx = int(round(pos * max(it.frames - 1, 0)))
                try:
                    view.setImage(gray_to_qimage(r.gray(idx, **xf)))
                    view.setSelection(it.crop)
                    view.setToolTip(f"{it.name} · frame {idx:,}")
                except Exception as exc:  # noqa: BLE001
                    view.setImage(None)
                    view.setPlaceholder(str(exc))

        # --------------------------------------------------------- crop ----
        def apply_crop(
            self, sel: Optional[tuple[int, int, int, int]], items: list[BatchItem]
        ) -> list[BatchItem]:
            """Set `sel` on every item it fits; returns the items skipped."""
            skipped = []
            for it in items:
                if it.crop_fits(sel):
                    it.crop = sel
                else:
                    skipped.append(it)
                card = self.cards.get(it.bin_path)
                if card is not None:
                    card.refresh()
            self._render_timer.start()
            self._compare_timer.start()
            return skipped

        def open_crop_editor(self, item: BatchItem) -> None:
            if self._running:
                return
            if item.thumb is None or not item.width or not item.height:
                QtWidgets.QMessageBox.warning(
                    self, "opngx", f"No frame could be decoded from {item.name}."
                )
                return
            img = item.thumb
            r = self._reader(item)
            if r is not None and item is self.current:
                try:  # crop over the frame the preview is showing
                    img = gray_to_qimage(r.gray(int(self.pv_slider.value()), **self._xform()))
                except Exception:  # noqa: BLE001
                    img = item.thumb
            def frame_fn(i: int, _item=item):
                rd = self._reader(_item)
                return gray_to_qimage(rd.gray(int(i), **self._xform())) if rd is not None else _item.thumb

            dlg = CropEditor(
                self,
                img,
                item.crop,
                (item.width, item.height),
                apply_all_default=False,
                show_apply_all=len(self.items) > 1,
                frame_fn=frame_fn,
                n_frames=item.frames,
                frame_index=int(self.pv_slider.value()) if item is self.current else int(item.extras.get("thumb_frame", 0)),
            )
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                self.status.setText("crop unchanged")
                return
            sel = dlg.selection()
            if dlg.apply_all.isChecked():
                skipped = self.apply_crop(sel, self.items)
                msg = (
                    "crop applied to every recording"
                    if sel
                    else "crop cleared for every recording"
                )
                if skipped:
                    msg += (
                        f" — skipped {len(skipped)} it does not fit: "
                        + ", ".join(i.name for i in skipped[:4])
                    )
                self.status.setText(msg)
            else:
                self.apply_crop(sel, [item])
                self.status.setText(
                    f"crop applied to {item.name}" if sel else f"crop cleared for {item.name}"
                )
            self.log.emit(self.status.text())

        def clear_crops(self) -> None:
            for it in self.items:
                it.crop = None
                self.cards[it.bin_path].refresh()
            self.status.setText("all crops cleared")
            self._render_timer.start()
            self._compare_timer.start()

        def preview_item(self, item: BatchItem) -> None:
            """Hand one recording to the main window's single viewer."""
            if item.meta is None:
                QtWidgets.QMessageBox.warning(
                    self, "opngx", f"{item.name} could not be probed."
                )
                return
            parent = self.parent()
            if parent is not None and hasattr(parent, "load_batch_item"):
                parent.load_batch_item(item)
                self.status.setText(f"{item.name} loaded in the main viewer")
            else:
                self.select(item)

        # ------------------------------------------------------- extract ----
        def _set_running(self, running: bool) -> None:
            self._running = running
            self.go.setEnabled(not running)
            self.stop.setEnabled(running)
            self.close_all.setEnabled(not running)
            self.rescan.setEnabled(not running)
            self.pv_crop.setEnabled(not running)
            for card in self.cards.values():
                card.crop_btn.setEnabled(not running)

        def start(self) -> None:
            if self._running:
                return
            if not self.out_root:
                QtWidgets.QMessageBox.warning(self, "opngx", "Choose an output folder.")
                return
            # the LIVE studio settings, not the ones from when we opened
            self.update_settings(self.current_settings())
            self._cancel = False
            self._t0 = time.perf_counter()
            self._set_running(True)
            for it in self.items:
                it.status = "queued"
                it.error = ""
                it.frames_done = 0
                it.frames_total = it.frames
                it.seconds = 0.0
                self.cards[it.bin_path].refresh()
            self._fill_table()
            self.total_bar.setValue(0)
            self.log.emit(f"batch start: {len(self.items)} recording(s) · {self._settings_line()}")
            threading.Thread(target=self._work, name="opngx-batch", daemon=True).start()

        def cancel(self) -> None:
            self._cancel = True
            self.status.setText("cancel requested…")
            self.log.emit("cancel requested")

        def _work(self) -> None:
            import opngx

            s = dict(self.settings)
            for it in self.items:
                if self._cancel:
                    it.status = "cancelled"
                    self.progress.emit(it)
                    continue
                if it.meta is None:
                    it.status = "failed"
                    it.error = it.error or "could not be probed"
                    self.progress.emit(it)
                    continue
                it.status = "running"
                self.progress.emit(it)
                last_emit = [0.0]

                def cb(done: int, total: int, _it=it) -> None:
                    _it.frames_done = int(done)
                    _it.frames_total = int(total or _it.frames)
                    now = time.perf_counter()
                    # throttle cross-thread repaints to ~20/s per card
                    if now - last_emit[0] >= 0.05 or done >= total:
                        last_emit[0] = now
                        self.progress.emit(_it)

                try:
                    st = opngx.Extractor(it.bin_path, it.footage_path).extract(
                        it.out_dir,
                        mode=s["mode"],
                        brightness=s.get("brightness"),
                        contrast=s.get("contrast"),
                        gamma=s.get("gamma"),
                        bit_depth=s["bit_depth"],
                        channels=s["channels"],
                        fmt=s["fmt"],
                        jpeg_quality=s.get("jpeg_quality", 90),
                        crop=it.crop,
                        jobs=s["jobs"],
                        level=s["level"],
                        prefix=s["prefix"],
                        ext=s["ext"],
                        start=s.get("start", 0) or 0,
                        frames=s.get("frames"),
                        export_timestamps=s.get("export_timestamps", False),
                        export_metadata=s.get("export_metadata", False),
                        progress=cb,
                        should_cancel=lambda: self._cancel,
                    )
                    it.seconds = float(st.seconds)
                    it.frames_done = int(st.frames_written)
                    it.status = (
                        "cancelled"
                        if st.cancelled or st.frames_written < st.frames_total
                        else "done"
                    )
                    self.progress.emit(it)
                    self.log.emit(
                        f"{it.name}: {it.status} · {st.frames_written:,} frames in "
                        f"{st.seconds:.2f}s → {it.out_dir}"
                    )
                except Exception as exc:  # noqa: BLE001
                    it.status = "failed"
                    it.error = str(exc)
                    self.progress.emit(it)
                    self.log.emit(f"{it.name}: FAILED — {exc}")
            self.finished.emit(self.items)

        # ---------------------------------------------------------- slots ----
        def _append_log(self, msg: str) -> None:
            self.log_view.appendPlainText(time.strftime("[%H:%M:%S] ") + msg)

        def _on_item(self, item: BatchItem) -> None:
            card = self.cards.get(item.bin_path)
            if card is not None:
                card.refresh()
            if item in self.items:
                self._table_row(self.items.index(item), item)
            done = sum(1 for i in self.items if i.done)
            tot = sum(max(i.frames_total or i.frames, 1) for i in self.items)
            got = sum(
                (i.frames_total or i.frames) if i.done else i.frames_done
                for i in self.items
            )
            self.total_bar.setValue(int(1000 * got / max(tot, 1)))
            self.status.setText(
                f"{done}/{len(self.items)} recordings • "
                f"{time.perf_counter() - self._t0:,.1f}s elapsed"
            )

        def _on_done(self, items: list[BatchItem]) -> None:
            self._set_running(False)
            failed = [i for i in items if i.status == "failed"]
            ok = sum(1 for i in items if i.status == "done")
            self.status.setText(
                f"finished: {ok} done, {len(failed)} failed, "
                f"{len(items)} total • {time.perf_counter() - self._t0:,.1f}s"
            )
            self.log.emit(self.status.text())
            if failed and self.isVisible():
                QtWidgets.QMessageBox.warning(
                    self,
                    "batch finished with errors",
                    "<br>".join(f"{i.name}: {i.error[:200]}" for i in failed[:8]),
                )

        def _on_failed(self, msg: str) -> None:
            self._set_running(False)
            self.status.setText(f"error: {msg}")
            self.log.emit(f"error: {msg}")
