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
    from opngx.ui.frameview import FrameView

    def _spin(lo: int, hi: int, val: int) -> "QtWidgets.QSpinBox":
        s = QtWidgets.QSpinBox()
        s.setRange(int(lo), max(int(hi), int(lo)))
        s.setValue(int(val))
        s.setKeyboardTracking(False)
        return s

    class CropEditor(QtWidgets.QDialog):
        """Drag, move or resize a rectangle over a real frame to pick a
        region of interest.

        The selection is clamped to the frame, always whole pixels, and the
        preview is drawn from the image the caller passes — the studio
        passes the frame through the CURRENT quality transform, so the user
        sees the pixels the encoder will write.
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
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle("Crop — region of interest")
            self.resize(820, 680)
            self._fw, self._fh = int(frame_size[0]), int(frame_size[1])
            self._img = image
            if transform is not None:
                try:
                    self._img = transform(image)
                except Exception:  # noqa: BLE001
                    self._img = image
            self._initial = current

            root = QtWidgets.QVBoxLayout(self)
            hint = QtWidgets.QLabel(
                "Drag to draw a region · drag inside it to move · drag an edge "
                "or corner to resize. Pixels are selected, never resampled."
            )
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            root.addWidget(hint)

            split = QtWidgets.QSplitter(Qt.Vertical)
            self.view = FrameView(self, editable=True)
            self.view.setImage(self._img)
            self.view.selectionChanged.connect(self._on_canvas_sel)
            self.view.hovered.connect(self._on_hover)
            split.addWidget(self.view)
            self.preview = FrameView(self, placeholder="preview")
            self.preview.setMinimumHeight(110)
            split.addWidget(self.preview)
            split.setStretchFactor(0, 4)
            split.setStretchFactor(1, 1)
            root.addWidget(split, 1)

            row = QtWidgets.QHBoxLayout()
            self.x_spin = _spin(0, max(self._fw - 1, 0), 0)
            self.y_spin = _spin(0, max(self._fh - 1, 0), 0)
            self.w_spin = _spin(1, max(self._fw, 1), self._fw)
            self.h_spin = _spin(1, max(self._fh, 1), self._fh)
            for lbl, w in (
                ("x", self.x_spin),
                ("y", self.y_spin),
                ("w", self.w_spin),
                ("h", self.h_spin),
            ):
                lab = QtWidgets.QLabel(lbl)
                lab.setObjectName("fieldlabel")
                row.addWidget(lab)
                row.addWidget(w)
                w.valueChanged.connect(self._on_spin)
            row.addStretch(1)
            self.full_btn = QtWidgets.QPushButton("Full frame")
            self.full_btn.clicked.connect(self._full)
            row.addWidget(self.full_btn)
            self.ctr_btn = QtWidgets.QPushButton("Centre 50%")
            self.ctr_btn.clicked.connect(self._center)
            row.addWidget(self.ctr_btn)
            self.reset_btn = QtWidgets.QPushButton("Reset")
            self.reset_btn.setToolTip("Back to the crop this dialog opened with")
            self.reset_btn.clicked.connect(self._reset)
            row.addWidget(self.reset_btn)
            root.addLayout(row)

            self.info = QtWidgets.QLabel()
            self.info.setObjectName("hint")
            root.addWidget(self.info)

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

            self._sel: tuple[int, int, int, int] = (0, 0, self._fw, self._fh)
            self._reset()

        # ---------------------------------------------------------------
        def _clamp(self, sel) -> tuple[int, int, int, int]:
            x, y, w, h = (int(v) for v in sel)
            x = max(0, min(x, self._fw - 1))
            y = max(0, min(y, self._fh - 1))
            w = max(1, min(w if w > 0 else self._fw - x, self._fw - x))
            h = max(1, min(h if h > 0 else self._fh - y, self._fh - y))
            return (x, y, w, h)

        def _set_sel(self, sel: tuple[int, int, int, int], *, from_canvas=False) -> None:
            self._sel = self._clamp(sel)
            x, y, w, h = self._sel
            for spin, val in (
                (self.x_spin, x),
                (self.y_spin, y),
                (self.w_spin, w),
                (self.h_spin, h),
            ):
                spin.blockSignals(True)
                spin.setValue(int(val))
                spin.blockSignals(False)
            if not from_canvas:
                self.view.setSelection(self._sel)
            self._render_preview()

        def _on_canvas_sel(self, sel) -> None:
            self._set_sel(tuple(int(v) for v in sel), from_canvas=True)

        def _on_spin(self) -> None:
            self._set_sel(
                (
                    self.x_spin.value(),
                    self.y_spin.value(),
                    self.w_spin.value(),
                    self.h_spin.value(),
                )
            )

        def _on_hover(self, x: int, y: int) -> None:
            if x < 0 or self._img is None:
                self._render_info()
                return
            v = QtGui.qGray(self._img.pixel(x, y))
            self._render_info(f"   ·   cursor {x},{y} = {v}")

        def _full(self) -> None:
            self._set_sel((0, 0, self._fw, self._fh))

        def _center(self) -> None:
            w = max(1, self._fw // 2)
            h = max(1, self._fh // 2)
            self._set_sel(((self._fw - w) // 2, (self._fh - h) // 2, w, h))

        def _reset(self) -> None:
            self._set_sel(self._initial or (0, 0, self._fw, self._fh))

        def _render_info(self, tail: str = "") -> None:
            x, y, w, h = self._sel
            odd = (
                "   ·   odd size: an MP4 render pads one black row/column"
                if (w % 2 or h % 2)
                else ""
            )
            self.info.setText(
                f"output {w} × {h} px  ·  columns {x}–{x + w - 1}, rows {y}–{y + h - 1}"
                f"{odd}{tail}"
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
        previewRequested = Signal(object)  # BatchItem

        def __init__(self, item: BatchItem) -> None:
            super().__init__()
            self.setObjectName("card")
            self.item = item
            v = QtWidgets.QVBoxLayout(self)
            v.setContentsMargins(10, 8, 10, 10)
            v.setSpacing(6)

            self.thumb = FrameView(self, placeholder="no preview")
            self.thumb.setFixedHeight(150)
            self.thumb.setImage(item.thumb)
            self.thumb.setSelection(item.crop)
            v.addWidget(self.thumb)

            title = QtWidgets.QLabel(item.name)
            title.setObjectName("cardtitle")
            title.setToolTip(item.bin_path)
            v.addWidget(title)

            self.facts = QtWidgets.QLabel()
            self.facts.setObjectName("hint")
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
            self.bar.setFixedHeight(12)
            self.bar.setRange(0, 100)
            v.addWidget(self.bar)

            row = QtWidgets.QHBoxLayout()
            self.crop_btn = QtWidgets.QPushButton("Crop…")
            self.crop_btn.clicked.connect(lambda: self.cropRequested.emit(self.item))
            self.prev_btn = QtWidgets.QPushButton("Preview")
            self.prev_btn.clicked.connect(lambda: self.previewRequested.emit(self.item))
            row.addWidget(self.crop_btn)
            row.addWidget(self.prev_btn)
            v.addLayout(row)
            self.refresh()

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
                "queued": "#8a948a",
                "running": "#60a5fa",
                "done": "#34d399",
                "failed": "#f87171",
                "cancelled": "#fbbf24",
            }
            txt = it.status
            if it.status == "done":
                txt = f"done · {it.frames_done:,} frames in {it.seconds:.2f}s"
            elif it.status == "failed" and it.error:
                txt = f"failed · {it.error[:120]}"
            elif it.status == "running" and it.frames_total:
                txt = f"running · {it.frames_done:,}/{it.frames_total:,}"
            self.status_lbl.setText(txt)
            self.status_lbl.setStyleSheet(f"color: {colors.get(it.status, '#8a948a')}")
            if it.frames_total:
                self.bar.setValue(int(100 * it.frames_done / it.frames_total))
            else:
                self.bar.setValue(0)

    class BatchWindow(QtWidgets.QDialog):
        """The dedicated batch surface the user asked for.

        One card per recording with a real decoded frame, the settings that
        will be used, the crop in force, live per-card progress, and its own
        Extract/Cancel buttons. Settings come LIVE from the studio
        (`settings_fn`) so what the main window shows is what the batch
        applies — the v1.7.0 window froze them at open time.
        """

        progress = Signal(object)  # BatchItem
        finished = Signal(object)  # list[BatchItem]
        failed = Signal(str)

        def __init__(
            self,
            parent: Optional[QtWidgets.QWidget],
            root: str,
            out_root: str,
            settings: dict[str, Any],
            settings_fn: Optional[Callable[[], dict[str, Any]]] = None,
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle(
                f"opngx batch — {os.path.basename(root.rstrip('/')) or root}"
            )
            self.resize(1180, 780)
            self.root = root
            self.out_root = out_root
            self.settings = dict(settings)
            self.settings_fn = settings_fn
            self.items: list[BatchItem] = []
            self.cards: dict[str, BatchCard] = {}
            self._running = False
            self._cancel = False
            self._t0 = 0.0

            root_lay = QtWidgets.QVBoxLayout(self)
            top = QtWidgets.QHBoxLayout()
            self.summary = QtWidgets.QLabel()
            self.summary.setObjectName("subtitle")
            self.summary.setWordWrap(True)
            top.addWidget(self.summary, 1)
            self.rescan = QtWidgets.QPushButton("Rescan")
            self.rescan.clicked.connect(lambda: self.load(self.root))
            top.addWidget(self.rescan)
            root_lay.addLayout(top)

            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.grid_host = QtWidgets.QWidget()
            self.grid_host.setObjectName("gridhost")
            self.grid = QtWidgets.QGridLayout(self.grid_host)
            self.grid.setSpacing(10)
            self.scroll.setWidget(self.grid_host)
            # QScrollArea.setWidget() forces autoFillBackground on, which
            # painted the platform window colour (white) behind the cards
            self.grid_host.setAutoFillBackground(False)
            self.scroll.viewport().setAutoFillBackground(False)
            self.grid_host.setStyleSheet("QWidget#gridhost { background: transparent; }")
            root_lay.addWidget(self.scroll, 1)

            bar = QtWidgets.QHBoxLayout()
            self.go = QtWidgets.QPushButton("▶  Extract all")
            self.go.setObjectName("accent")
            self.go.clicked.connect(self.start)
            self.stop = QtWidgets.QPushButton("■  Cancel")
            self.stop.setObjectName("danger")
            self.stop.setEnabled(False)
            self.stop.clicked.connect(self.cancel)
            self.close_all = QtWidgets.QPushButton("Clear crops")
            self.close_all.clicked.connect(self.clear_crops)
            bar.addWidget(self.go)
            bar.addWidget(self.stop)
            bar.addWidget(self.close_all)
            bar.addStretch(1)
            self.status = QtWidgets.QLabel("idle")
            self.status.setObjectName("hint")
            bar.addWidget(self.status)
            root_lay.addLayout(bar)

            self.progress.connect(self._on_item)
            self.finished.connect(self._on_done)
            self.failed.connect(self._on_failed)
            self.load(root)

        # -----------------------------------------------------------------
        def current_settings(self) -> dict[str, Any]:
            if self.settings_fn is not None:
                try:
                    self.settings = dict(self.settings_fn())
                except Exception:  # noqa: BLE001  (studio closed etc.)
                    pass
            return self.settings

        def update_settings(self, settings: Optional[dict[str, Any]] = None) -> None:
            """Re-render every card for new settings (called by the studio
            whenever a quality control changes)."""
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

        def _update_summary(self) -> None:
            self.summary.setText(
                f"{len(self.items)} recording(s) · output {self.out_root} · "
                f"settings: {self._settings_line()}"
            )

        def load(self, root: str) -> None:
            """(Re)build the cards for a mother folder."""
            self.root = root
            while self.grid.count():
                it = self.grid.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self.cards.clear()
            self.items = []
            bins = scan_batch(root)
            if not bins:
                self.summary.setText(f"no .bin found under {root}")
                return
            s = self.current_settings()
            self.items = make_items(bins, s)
            for n, it in enumerate(self.items):
                it.out_dir = batch_out_dir(self.out_root, root, it.bin_path, s["fmt"])
                card = BatchCard(it)
                card.set_transform(s)
                card.cropRequested.connect(self.open_crop_editor)
                card.previewRequested.connect(self.preview_item)
                self.cards[it.bin_path] = card
                self.grid.addWidget(card, n // 3, n % 3)
            self.grid.setRowStretch(self.grid.rowCount(), 1)
            self._update_summary()

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
            return skipped

        def open_crop_editor(self, item: BatchItem) -> None:
            if self._running:
                return
            if item.thumb is None or not item.width or not item.height:
                QtWidgets.QMessageBox.warning(
                    self, "opngx", f"No frame could be decoded from {item.name}."
                )
                return
            dlg = CropEditor(
                self,
                item.thumb,
                item.crop,
                (item.width, item.height),
                apply_all_default=False,
                show_apply_all=len(self.items) > 1,
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

        def clear_crops(self) -> None:
            for it in self.items:
                it.crop = None
                self.cards[it.bin_path].refresh()
            self.status.setText("all crops cleared")

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
                self.status.setText(
                    f"{item.name}: {item.out_size}, {item.frames:,} frames"
                )

        # ------------------------------------------------------- extract ----
        def _set_running(self, running: bool) -> None:
            self._running = running
            self.go.setEnabled(not running)
            self.stop.setEnabled(running)
            self.close_all.setEnabled(not running)
            self.rescan.setEnabled(not running)
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
            threading.Thread(target=self._work, name="opngx-batch", daemon=True).start()

        def cancel(self) -> None:
            self._cancel = True
            self.status.setText("cancel requested…")

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
                except Exception as exc:  # noqa: BLE001
                    it.status = "failed"
                    it.error = str(exc)
                    self.progress.emit(it)
            self.finished.emit(self.items)

        # ---------------------------------------------------------- slots ----
        def _on_item(self, item: BatchItem) -> None:
            card = self.cards.get(item.bin_path)
            if card is not None:
                card.refresh()
            done = sum(1 for i in self.items if i.done)
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
            if failed and self.isVisible():
                QtWidgets.QMessageBox.warning(
                    self,
                    "batch finished with errors",
                    "<br>".join(f"{i.name}: {i.error[:200]}" for i in failed[:8]),
                )

        def _on_failed(self, msg: str) -> None:
            self._set_running(False)
            self.status.setText(f"error: {msg}")
