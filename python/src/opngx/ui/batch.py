"""Batch studio window (cycle 22) + ROI crop editor.

The user field report was twofold:
  1. batch runs did not honour gamma/contrast (fixed in the engine, v1.7.0)
  2. during a batch there was no way to SEE what each folder produced — the
     single frame viewer only ever showed one recording at a time, and the
     info table showed just a count of .bin files.

`BatchWindow` gives every recording its own card: a real decoded thumbnail,
geometry, frame count, fps, crop state, a per-recording status line and a
per-recording progress bar, so a 40-recording batch is legible at a glance.

`CropEditor` is the interactive region-of-interest picker: drag a rectangle
over a real decoded frame, snap to integers, and apply it to this recording
only or to every recording in the batch.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from opngx.layout import batch_out_dir, run_out_dir

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal

    _QT = True
except Exception:  # pragma: no cover
    _QT = False


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
    meta: Any = None
    extras: dict = field(default_factory=dict)

    @property
    def out_size(self) -> str:
        """Encoded size after the crop is applied (what the files will be)."""
        if self.crop and self.width and self.height:
            x, y, w, h = self.crop
            return f"{w} × {h} px"
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


def scan_batch(root: str) -> list[str]:
    """Every .bin under `root`: one level of nesting plus loose files.

    Identical discovery order to the studio's Batch scope and the engine's
    `batch` subcommand, so all three agree on what a batch contains.
    """
    import glob

    bins = sorted(glob.glob(os.path.join(root, "*", "*.bin")))
    bins += sorted(glob.glob(os.path.join(root, "*.bin")))
    return bins


def make_item(bin_path: str) -> BatchItem:
    """Probe one recording into a BatchItem (thumbnail included)."""
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
            img = QtGui.QImage(
                buf,
                item.width,
                item.height,
                item.width,
                QtGui.QImage.Format_Grayscale8,
            ).copy()
            item.thumb = img
            item.extras["thumb_frame"] = mid
        except Exception as exc:  # noqa: BLE001
            item.extras["thumb_error"] = str(exc)
    return item


if not _QT:  # pragma: no cover
    BatchWindow = None  # type: ignore[assignment]
    CropEditor = None  # type: ignore[assignment]
else:

    class CropEditor(QtWidgets.QDialog):
        """Drag a rectangle over a real frame to pick a region of interest.

        The selection is clamped to the frame, snapped to whole pixels, and
        previewed live through the *current* quality transform so the user
        sees the same pixels the encoder will write.
        """

        cropChanged = Signal(object)

        def __init__(
            self,
            parent: QtWidgets.QWidget,
            image: "QtGui.QImage",
            current: Optional[tuple[int, int, int, int]],
            frame_size: tuple[int, int],
            transform: Optional[Callable[["QtGui.QImage"], "QtGui.QImage"]] = None,
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle("Crop — region of interest")
            self.resize(760, 620)
            self._img = image
            self._fw, self._fh = frame_size
            self._transform = transform
            self._drag_from: Optional[QtCore.QPoint] = None
            self._sel: Optional[tuple[int, int, int, int]] = current

            root = QtWidgets.QVBoxLayout(self)
            self.view = _CropCanvas(self)
            self.view.setImage(image)
            self.view.selectionChanged.connect(self._on_canvas_sel)
            root.addWidget(self.view, 1)

            row = QtWidgets.QHBoxLayout()
            self.x_spin = _spin(0, 0, max(self._fw - 1, 0))
            self.y_spin = _spin(0, 0, max(self._fh - 1, 0))
            self.w_spin = _spin(self._fw, 1, max(self._fw, 1))
            self.h_spin = _spin(self._fh, 1, max(self._fh, 1))
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
            root.addLayout(row)

            self.apply_all = QtWidgets.QCheckBox(
                "Apply this crop to every recording in the batch"
            )
            self.apply_all.setChecked(True)
            root.addWidget(self.apply_all)

            self.preview = QtWidgets.QLabel()
            self.preview.setObjectName("viewer")
            self.preview.setAlignment(Qt.AlignCenter)
            self.preview.setMinimumHeight(120)
            root.addWidget(self.preview)

            btns = QtWidgets.QHBoxLayout()
            btns.addStretch(1)
            cancel = QtWidgets.QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            ok = QtWidgets.QPushButton("Use this crop")
            ok.setObjectName("accent")
            ok.clicked.connect(self._accept)
            btns.addWidget(cancel)
            btns.addWidget(ok)
            root.addLayout(btns)

            if current:
                self._set_sel(current)
            else:
                self._set_sel((0, 0, self._fw, self._fh))

        # ---------------------------------------------------------------
        def _set_sel(self, sel: tuple[int, int, int, int]) -> None:
            x, y, w, h = sel
            self._sel = (x, y, w, h)
            for spin, val in (
                (self.x_spin, x),
                (self.y_spin, y),
                (self.w_spin, w),
                (self.h_spin, h),
            ):
                spin.blockSignals(True)
                spin.setValue(int(val))
                spin.blockSignals(False)
            self.view.setSelection(*self._sel)
            self._render_preview()

        def _on_canvas_sel(self, sel) -> None:
            x, y, w, h = (int(v) for v in sel)
            self._set_sel((x, y, w, h))

        def _on_spin(self) -> None:
            x = min(int(self.x_spin.value()), max(self._fw - 1, 0))
            y = min(int(self.y_spin.value()), max(self._fh - 1, 0))
            w = max(1, min(int(self.w_spin.value()), self._fw - x))
            h = max(1, min(int(self.h_spin.value()), self._fh - y))
            self._set_sel((x, y, w, h))

        def _full(self) -> None:
            self._set_sel((0, 0, self._fw, self._fh))

        def _center(self) -> None:
            w = max(1, self._fw // 2)
            h = max(1, self._fh // 2)
            self._set_sel(((self._fw - w) // 2, (self._fh - h) // 2, w, h))

        def _render_preview(self) -> None:
            x, y, w, h = self._sel
            sub = self._img.copy(x, y, w, h)
            if self._transform is not None:
                try:
                    sub = self._transform(sub)
                except Exception:  # noqa: BLE001
                    pass
            pm = QtGui.QPixmap.fromImage(sub).scaled(
                self.preview.width() - 8,
                self.preview.height() - 8,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.preview.setPixmap(pm)

        def _accept(self) -> None:
            self.cropChanged.emit(self._sel)
            self.accept()

        def selection(self) -> Optional[tuple[int, int, int, int]]:
            if self._sel == (0, 0, self._fw, self._fh):
                return None
            return self._sel

    class _CropCanvas(QtWidgets.QLabel):
        """Image view with a draggable integer-aligned selection rect."""

        selectionChanged = Signal(object)

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.setObjectName("viewer")
            self.setAlignment(Qt.AlignCenter)
            self.setMinimumSize(320, 240)
            self.setMouseTracking(True)
            self._img: Optional[QtGui.QImage] = None
            self._pm: Optional[QtGui.QPixmap] = None
            self._sel = (0, 0, 0, 0)
            self._drag_from: Optional[QtCore.QPoint] = None

        def setImage(self, img: "QtGui.QImage") -> None:  # noqa: N802
            self._img = img
            self._pm = None
            self.update()

        def setSelection(self, x: int, y: int, w: int, h: int) -> None:  # noqa: N802
            self._sel = (x, y, w, h)
            self.update()

        def _scaled(self):
            if self._pm is None and self._img is not None:
                self._pm = QtGui.QPixmap.fromImage(self._img)
            return self._pm

        def _map_to_image(self, pos: QtCore.QPoint) -> tuple[int, int]:
            pm = self._scaled()
            if pm is None or pm.isNull() or self._img is None:
                return (0, 0)
            sx = pm.width() / max(self._img.width(), 1)
            sy = pm.height() / max(self._img.height(), 1)
            return (
                max(0, min(int(pos.x() / sx), self._img.width() - 1)),
                max(0, min(int(pos.y() / sy), self._img.height() - 1)),
            )

        def paintEvent(self, ev) -> None:  # noqa: N802
            super().paintEvent(ev)
            pm = self._scaled()
            if pm is None or pm.isNull():
                return
            target = pm.size()
            target.scale(self.width() - 8, self.height() - 8, Qt.KeepAspectRatio)
            scaled = pm.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            ox = (self.width() - scaled.width()) // 2
            oy = (self.height() - scaled.height()) // 2
            p = QtGui.QPainter(self)
            p.drawPixmap(ox, oy, scaled)
            x, y, w, h = self._sel
            if w > 0 and h > 0:
                sx = scaled.width() / max(pm.width(), 1)
                sy = scaled.height() / max(pm.height(), 1)
                p.fillRect(
                    ox,
                    oy,
                    scaled.width(),
                    scaled.height(),
                    QtGui.QColor(0, 0, 0, 110),
                )
                p.fillRect(
                    ox + int(x * sx),
                    oy + int(y * sy),
                    int(w * sx),
                    int(h * sy),
                    QtGui.QColor(0, 0, 0, 0),
                )
                pen = QtGui.QPen(QtGui.QColor("#7fb069"))
                pen.setWidth(2)
                p.setPen(pen)
                p.drawRect(
                    ox + int(x * sx),
                    oy + int(y * sy),
                    int(w * sx),
                    int(h * sy),
                )
            p.end()

        def mousePressEvent(self, ev) -> None:  # noqa: N802
            if ev.button() == Qt.LeftButton:
                self._drag_from = self._map_to_image(ev.position().toPoint())

        def mouseMoveEvent(self, ev) -> None:  # noqa: N802
            if self._drag_from is None:
                return
            cur = self._map_to_image(ev.position().toPoint())
            x0, y0 = self._drag_from
            x1, y1 = cur
            x, y = min(x0, x1), min(y0, y1)
            w, h = abs(x1 - x0) + 1, abs(y1 - y0) + 1
            if self._img is not None:
                w = min(w, self._img.width() - x)
                h = min(h, self._img.height() - y)
            self._sel = (x, y, max(w, 1), max(h, 1))
            self.update()

        def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
            if self._drag_from is not None:
                self._drag_from = None
                self.selectionChanged.emit(self._sel)

    def _spin(lo: int, val: int, hi: int) -> "QtWidgets.QSpinBox":
        s = QtWidgets.QSpinBox()
        s.setRange(int(lo), max(int(hi), int(lo)))
        s.setValue(int(val))
        return s

    class BatchCard(QtWidgets.QFrame):
        """One recording: thumbnail, facts, crop state, status, progress."""

        cropRequested = Signal(object)  # BatchItem
        previewRequested = Signal(object)  # BatchItem

        def __init__(self, item: BatchItem) -> None:
            super().__init__()
            self.setObjectName("card")
            self.item = item
            v = QtWidgets.QVBoxLayout(self)
            v.setContentsMargins(10, 8, 10, 10)
            v.setSpacing(6)

            self.thumb = QtWidgets.QLabel()
            self.thumb.setObjectName("viewer")
            self.thumb.setAlignment(Qt.AlignCenter)
            self.thumb.setFixedHeight(120)
            if item.thumb is not None:
                self.thumb.setPixmap(
                    QtGui.QPixmap.fromImage(item.thumb).scaled(
                        200,
                        120,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
            else:
                self.thumb.setText("no preview")
            v.addWidget(self.thumb)

            title = QtWidgets.QLabel(item.name)
            title.setObjectName("cardtitle")
            title.setToolTip(item.bin_path)
            v.addWidget(title)

            self.facts = QtWidgets.QLabel(
                f"{item.out_size} · {item.frames:,} frames"
                + (f" · {item.framerate:,.0f} fps" if item.framerate else "")
            )
            self.facts.setObjectName("hint")
            v.addWidget(self.facts)

            self.crop_lbl = QtWidgets.QLabel(item.crop_label)
            self.crop_lbl.setObjectName("hint")
            v.addWidget(self.crop_lbl)

            self.status_lbl = QtWidgets.QLabel(item.status)
            self.status_lbl.setObjectName("hint")
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

        def refresh(self) -> None:
            it = self.item
            self.facts.setText(
                f"{it.out_size} · {it.frames:,} frames"
                + (f" · {it.framerate:,.0f} fps" if it.framerate else "")
            )
            self.crop_lbl.setText(it.crop_label)
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
                txt = f"failed · {it.error[:80]}"
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
        Extract/Cancel buttons. Applying settings here applies them to the
        WHOLE batch — which is the behaviour the field report was missing.
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
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle(
                f"opngx batch — {os.path.basename(root.rstrip('/')) or root}"
            )
            self.resize(1180, 760)
            self.root = root
            self.out_root = out_root
            self.settings = dict(settings)
            self.items: list[BatchItem] = []
            self.cards: dict[str, BatchCard] = {}
            self._running = False
            self._cancel = False
            self._t0 = 0.0

            root_lay = QtWidgets.QVBoxLayout(self)
            top = QtWidgets.QHBoxLayout()
            self.summary = QtWidgets.QLabel()
            self.summary.setObjectName("subtitle")
            top.addWidget(self.summary)
            top.addStretch(1)
            self.rescan = QtWidgets.QPushButton("Rescan")
            self.rescan.clicked.connect(lambda: self.load(root))
            top.addWidget(self.rescan)
            root_lay.addLayout(top)

            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.grid_host = QtWidgets.QWidget()
            self.grid = QtWidgets.QGridLayout(self.grid_host)
            self.grid.setSpacing(10)
            self.scroll.setWidget(self.grid_host)
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
            self.summary.setText(
                f"{len(bins)} recording(s) · output {self.out_root} · "
                f"settings: {self._settings_line()}"
            )
            for n, b in enumerate(bins):
                it = make_item(b)
                it.out_dir = batch_out_dir(self.out_root, root, b, self.settings["fmt"])
                self.items.append(it)
                card = BatchCard(it)
                card.cropRequested.connect(self.open_crop_editor)
                card.previewRequested.connect(self.preview_item)
                self.cards[b] = card
                self.grid.addWidget(card, n // 3, n % 3)
            self.grid.setRowStretch(self.grid.rowCount(), 1)

        def _settings_line(self) -> str:
            s = self.settings
            bits = [f"mode={s.get('mode')}"]
            if s.get("mode") == "custom":
                bits.append(
                    f"B={s.get('brightness'):g} C={s.get('contrast'):g} "
                    f"γ={s.get('gamma'):g}"
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
        def open_crop_editor(self, item: BatchItem) -> None:
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
            )
            dlg.exec()
            sel = dlg.selection()
            if dlg.apply_all.isChecked():
                for it in self.items:
                    it.crop = sel
                    self.cards[it.bin_path].refresh()
                self.status.setText(
                    "crop applied to every recording"
                    if sel
                    else "crop cleared for every recording"
                )
            elif sel != item.crop:
                item.crop = sel
                self.cards[item.bin_path].refresh()
                self.status.setText(f"crop applied to {item.name}")
            else:
                self.status.setText("crop unchanged")

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
        def start(self) -> None:
            if self._running:
                return
            if not self.out_root:
                QtWidgets.QMessageBox.warning(self, "opngx", "Choose an output folder.")
                return
            self._running = True
            self._cancel = False
            self._t0 = time.perf_counter()
            self.go.setEnabled(False)
            self.stop.setEnabled(True)
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

            s = self.settings
            for it in self.items:
                if self._cancel:
                    it.status = "cancelled"
                    self.progress.emit(it)
                    continue
                it.status = "running"
                self.progress.emit(it)

                def cb(done: int, total: int, _it=it) -> None:
                    _it.frames_done = int(done)
                    _it.frames_total = int(total or _it.frames)
                    self.progress.emit(_it)

                try:
                    st = opngx.Extractor(it.bin_path).extract(
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
                    it.status = "cancelled" if st.cancelled else "done"
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
            self._running = False
            self.go.setEnabled(True)
            self.stop.setEnabled(False)
            failed = [i for i in items if i.status == "failed"]
            ok = sum(1 for i in items if i.status == "done")
            self.status.setText(
                f"finished: {ok} done, {len(failed)} failed, "
                f"{len(items)} total • {time.perf_counter() - self._t0:,.1f}s"
            )
            if failed:
                QtWidgets.QMessageBox.warning(
                    self,
                    "batch finished with errors",
                    "<br>".join(f"{i.name}: {i.error[:200]}" for i in failed[:8]),
                )

        def _on_failed(self, msg: str) -> None:
            self._running = False
            self.go.setEnabled(True)
            self.stop.setEnabled(False)
            self.status.setText(f"error: {msg}")
