"""Video tab (v2.1): render the loaded recording with any codec of the
bundled ffmpeg, and prove the lossless ones are bit-exact.

Replaces v2.0's modal "Render video" dialog, whose title-bar X returned
while ffmpeg kept encoding unseen and whose renders ignored the main
Cancel button. Here a render is ordinary studio work: the main Cancel and
this tab's Stop both end it, and the window knows it is busy.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt, Signal

import opngx
from opngx import video as _video
from opngx.layout import mp4_dir, safe_name
from opngx.ui import icons as _icons

PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")

_HELP = {
    "h264": "Plays everywhere (PowerPoint, browsers, phones). Lossy but visually excellent at CRF 18. "
            "Odd crop sizes get one black row/column of padding.",
    "h265": "About half the size of H.264 at the same quality. Plays in modern players, Windows 10/11 "
            "with the HEVC extension, macOS/iOS.",
    "vp9": "Open, royalty-free WebM for the web. Small; slower to encode than H.264.",
    "av1": "The smallest lossy files. Slow to encode - fine for a few thousand frames.",
    "ffv1": "LOSSLESS: every frame decodes to exactly the extracted pixels (bit-exact grey, checked "
            "below). The archival choice - a whole recording in one file, much smaller than PNGs.",
    "prores": "Apple ProRes 422 HQ for video editors (Premiere, DaVinci Resolve, Final Cut). "
              "Near-lossless and large.",
    "mjpeg": "Motion-JPEG: every frame stands alone, so frame-accurate seeking in old software. Lossy.",
    "gif": "Animated GIF with 256 greys - LOSSLESS for this 8-bit footage. For slides and chat; "
           "keep it short (files grow quickly).",
    "h264_gpu": "H.264 on the graphics card (NVIDIA NVENC, Intel Quick Sync, AMD AMF). Fastest when "
                "available; quality per byte is a little below the CPU encoder.",
}


_USE = {
    "h264": "slides, sharing, any player",
    "h265": "same quality as H.264 in half the size",
    "vp9": "the web (open format)",
    "av1": "smallest files; slow to encode",
    "ffv1": "archiving and measurements: bit-exact",
    "prores": "video editing software",
    "mjpeg": "frame-accurate seeking in old software",
    "gif": "short clips in slides and chat; exact",
    "h264_gpu": "fastest H.264, on the graphics card",
}


class _Sig(QtCore.QObject):
    progress = Signal(int, int)
    status = Signal(str)
    finished = Signal(object)
    check = Signal(str)
    codecs = Signal(object)


class VideoView(QtWidgets.QWidget):
    def __init__(self, studio, parent=None) -> None:
        super().__init__(parent)
        self.studio = studio
        self._stop = False
        self._busy = False
        self._last_out: Optional[str] = None
        self._sig = _Sig()
        self._sig.progress.connect(self._on_progress)
        self._sig.status.connect(lambda s: self.stat.setText(s))
        self._sig.finished.connect(self._on_finished)
        self._sig.check.connect(lambda s: self.check_lbl.setText(s))
        self._sig.codecs.connect(self._codecs_ready)
        self._avail: dict = {}
        self._build()
        QtCore.QTimer.singleShot(0, self._probe_codecs)

    # ------------------------------------------------------------- build --
    def _build(self) -> None:
        sc = self.studio._scaling
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(sc.px(12))

        left, lv = self.studio._card("video settings")
        grid = QtWidgets.QGridLayout()
        grid.setColumnStretch(1, 1)
        r = 0
        grid.addWidget(QtWidgets.QLabel("codec"), r, 0)
        self.codec = QtWidgets.QComboBox()
        for key, c in _video.CODECS.items():
            self.codec.addItem(c["label"], key)
        self.codec.currentIndexChanged.connect(self._codec_changed)
        grid.addWidget(self.codec, r, 1, 1, 2)
        r += 1
        self.help = QtWidgets.QLabel("")
        self.help.setWordWrap(True)
        self.help.setObjectName("hint")
        grid.addWidget(self.help, r, 0, 1, 3)
        r += 1
        self.q_lbl = QtWidgets.QLabel("quality")
        self.quality = QtWidgets.QSpinBox()
        grid.addWidget(self.q_lbl, r, 0)
        grid.addWidget(self.quality, r, 1)
        self.q_hint = QtWidgets.QLabel("")
        self.q_hint.setObjectName("hint")
        grid.addWidget(self.q_hint, r, 2)
        r += 1
        grid.addWidget(QtWidgets.QLabel("speed preset"), r, 0)
        self.preset = QtWidgets.QComboBox()
        self.preset.addItems(PRESETS)
        self.preset.setCurrentText("medium")
        self.preset.setToolTip("x264/x265 only: slower presets give smaller files at the same quality.")
        grid.addWidget(self.preset, r, 1)
        r += 1
        grid.addWidget(QtWidgets.QLabel("frame rate"), r, 0)
        self.fps = QtWidgets.QSpinBox()
        self.fps.setRange(1, 2000)
        self.fps.setValue(30)
        self.fps.valueChanged.connect(self._update_estimate)
        grid.addWidget(self.fps, r, 1)
        self.fps_real = QtWidgets.QPushButton("real time")
        self.fps_real.setObjectName("compact")
        self.fps_real.setToolTip("Use the camera's frame rate (from the frame timestamps): the video "
                                 "plays in real time. Lower values give slow motion.")
        self.fps_real.clicked.connect(self._set_real_fps)
        grid.addWidget(self.fps_real, r, 2)
        r += 1
        self.use_crop = QtWidgets.QCheckBox("only the crop region (set on the Extract tab)")
        self.use_crop.setChecked(True)
        self.use_crop.toggled.connect(self._update_estimate)
        grid.addWidget(self.use_crop, r, 0, 1, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("output file"), r, 0)
        self.out = QtWidgets.QLineEdit()
        grid.addWidget(self.out, r, 1)
        browse = QtWidgets.QPushButton("Choose…")
        _icons.set_icon(browse, "folder", "text")
        browse.clicked.connect(self._browse)
        grid.addWidget(browse, r, 2)
        lv.addLayout(grid)

        self.estimate = QtWidgets.QLabel("")
        self.estimate.setWordWrap(True)
        self.estimate.setObjectName("hint")
        lv.addWidget(self.estimate)
        lv.addStretch(1)

        bar = QtWidgets.QHBoxLayout()
        self.go = QtWidgets.QPushButton("Render video")
        self.go.setObjectName("accent")
        _icons.set_icon(self.go, "film", "on_accent")
        self.go.clicked.connect(self.render)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        _icons.set_icon(self.stop_btn, "stop", "on_danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.open_btn = QtWidgets.QPushButton("Show file")
        _icons.set_icon(self.open_btn, "external", "text")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._show_file)
        bar.addWidget(self.go)
        bar.addWidget(self.stop_btn)
        bar.addWidget(self.open_btn)
        bar.addStretch(1)
        lv.addLayout(bar)
        self.prog = QtWidgets.QProgressBar()
        self.prog.setRange(0, 1000)
        sc.fix(self.prog, "setFixedHeight", 12)
        lv.addWidget(self.prog)
        self.stat = QtWidgets.QLabel("Load a recording on the Extract tab, then render it here.")
        self.stat.setWordWrap(True)
        self.stat.setObjectName("hint")
        lv.addWidget(self.stat)
        outer.addWidget(left, 3)

        right, rv = self.studio._card("what the codecs keep")
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["codec", "pixels", "on this PC", "use it for"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(True)
        self.table.cellClicked.connect(lambda row, _c: self.codec.setCurrentIndex(row))
        rv.addWidget(self.table, 1)
        self.check_btn = QtWidgets.QPushButton("Check the last video is bit-exact")
        _icons.set_icon(self.check_btn, "shield", "text")
        self.check_btn.setToolTip("Decode the last FFV1 / GIF video and compare every frame with the "
                                  "extracted pixels.")
        self.check_btn.setEnabled(False)
        self.check_btn.clicked.connect(self._check_exact)
        rv.addWidget(self.check_btn)
        self.check_lbl = QtWidgets.QLabel("")
        self.check_lbl.setWordWrap(True)
        self.check_lbl.setObjectName("hint")
        rv.addWidget(self.check_lbl)
        outer.addWidget(right, 2)
        self._fill_table()
        self._codec_changed()

    def _fill_table(self) -> None:
        self.table.setRowCount(len(_video.CODECS))
        for i, (key, c) in enumerate(_video.CODECS.items()):
            ok = self._avail.get(key)
            cells = [c["label"].split(" (")[0], "exact" if c["lossless"] else "lossy",
                     "…" if ok is None else ("yes" if ok else "not available"),
                     _USE.get(key, "")]
            for j, txt in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(txt)
                it.setToolTip(_HELP.get(key, ""))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

    def _probe_codecs(self) -> None:
        def run():
            try:
                av = _video.available_codecs() if _video.ffmpeg_available() else {k: False for k in _video.CODECS}
            except Exception:  # noqa: BLE001
                av = {k: False for k in _video.CODECS}
            self._sig.codecs.emit(av)

        threading.Thread(target=run, daemon=True, name="opngx-codec-probe").start()

    def _codecs_ready(self, av) -> None:
        self._avail = dict(av)
        model = self.codec.model()
        for i in range(self.codec.count()):
            key = self.codec.itemData(i)
            item = model.item(i)
            if item is not None:
                item.setEnabled(bool(av.get(key)))
                if not av.get(key):
                    item.setToolTip("not available with this ffmpeg / computer")
        self._fill_table()
        if not _video.ffmpeg_available():
            self.stat.setText("ffmpeg was not found: the studio normally ships it. Reinstall opngx, "
                              "or install ffmpeg and restart.")

    # ------------------------------------------------------------ state --
    def refresh(self) -> None:
        """Called when the tab is shown or a recording is loaded."""
        m = self.studio.meta
        if not m:
            self.estimate.setText("No recording loaded.")
            return
        if not self.out.text().strip() or not self.out.property("user_set"):
            self._default_out()
        if self.fps.property("user_set") is None:
            self._set_real_fps()
        self._update_estimate()
        if not self._busy and self.stat.text().startswith("Load a recording"):
            import os as _os

            self.stat.setText(f"Ready: {_os.path.basename(m.bin_path)}. Choose a codec and press Render video.")

    def _codec_key(self) -> str:
        return self.codec.currentData() or "h264"

    def _codec_changed(self, *_a) -> None:
        key = self._codec_key()
        c = _video.CODECS[key]
        self.help.setText(_HELP.get(key, ""))
        knob = c["knob"]
        self.q_lbl.setVisible(bool(knob))
        self.quality.setVisible(bool(knob))
        self.q_hint.setVisible(bool(knob))
        if knob:
            name, default, lo, hi, better = knob
            self.q_lbl.setText(name)
            self.quality.setRange(lo, hi)
            self.quality.setValue(default)
            self.q_hint.setText(f"{better} = better quality, bigger file (default {default})")
        self.preset.setEnabled(key in ("h264", "h265"))
        if self.studio.meta and not self.out.property("user_set"):
            self._default_out()
        elif self.out.text():
            base, _ext = os.path.splitext(self.out.text())
            self.out.setText(base + c["ext"])
        self._update_estimate()

    def _default_out(self) -> None:
        m = self.studio.meta
        if not m:
            return
        root = self.studio.out_edit.text().strip() or os.path.dirname(m.bin_path)
        name = safe_name(m.camera_name or os.path.splitext(os.path.basename(m.bin_path))[0])
        suffix = "" if self._codec_key() == "h264" else f"_{self._codec_key()}"
        self.out.setText(os.path.join(mp4_dir(root, m.bin_path), name + suffix + _video.CODECS[self._codec_key()]["ext"]))

    def _set_real_fps(self) -> None:
        m = self.studio.meta
        fps = 30
        if m:
            for cand in (getattr(m, "effective_fps_us", None), getattr(m, "framerate_real", None), m.framerate):
                if cand and cand > 0:
                    fps = int(round(cand))
                    break
        self.fps.blockSignals(True)
        self.fps.setValue(max(1, min(2000, fps)))
        self.fps.blockSignals(False)
        self._update_estimate()

    def _frames(self) -> tuple[int, int]:
        m = self.studio.meta
        o = self.studio._collect_opts()
        start = int(o.get("start") or 0)
        n = o["frames"] if o.get("frames") is not None else max(0, m.capacity_frames - start)
        return start, max(0, min(n, m.capacity_frames - start))

    def _update_estimate(self, *_a) -> None:
        m = self.studio.meta
        if not m:
            return
        start, n = self._frames()
        crop = self.studio._crop if self.use_crop.isChecked() else None
        w, h = (crop[2], crop[3]) if crop else (m.width, m.height)
        secs = n / max(1, self.fps.value())
        dur = f"{secs:.1f} s" if secs < 60 else f"{int(secs // 60)}:{int(secs % 60):02d} min"
        self.estimate.setText(
            f"{n:,} frames from frame {start:,} · {w}×{h} px{' (crop)' if crop else ''} · "
            f"plays {dur} at {self.fps.value()} fps · "
            f"transform: {self.studio._collect_opts()['mode']} (as on the Extract tab)")

    def _browse(self) -> None:
        key = self._codec_key()
        ext = _video.CODECS[key]["ext"]
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Output video", self.out.text(), f"Video (*{ext})")
        if p:
            if not p.lower().endswith(ext):
                p += ext
            self.out.setText(p)
            self.out.setProperty("user_set", True)

    # ----------------------------------------------------------- render --
    def stop(self) -> None:
        self._stop = True
        self.stat.setText("stopping…")

    def render(self) -> None:
        st = self.studio
        if not st.meta:
            QtWidgets.QMessageBox.information(self, "opngx", "Load a recording on the Extract tab first.")
            return
        if st._running:
            QtWidgets.QMessageBox.information(self, "opngx", "Another task is running; wait for it or cancel it.")
            return
        key = self._codec_key()
        if self._avail and not self._avail.get(key):
            QtWidgets.QMessageBox.warning(self, "opngx", "This codec is not available on this computer.")
            return
        out = self.out.text().strip()
        if not out:
            return
        o = st._collect_opts()
        start, n = self._frames()
        crop = st._crop if self.use_crop.isChecked() else None
        knob = _video.CODECS[key]["knob"]
        q = self.quality.value() if knob else None
        fps = self.fps.value()
        preset = self.preset.currentText()
        self._stop = False
        self._busy = True
        st._running = True
        st._cancel_requested = False
        st._sig.state.emit(True)
        self.go.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.check_lbl.setText("")
        t0 = time.perf_counter()

        def pgs(done, total):
            self._sig.progress.emit(done, total)
            el = time.perf_counter() - t0
            frac = done / max(total, 1)
            eta = el / frac - el if frac > 0.004 else 0
            self._sig.status.emit(f"{done:,}/{total:,} frames · {done / max(el, 1e-9):,.0f} frames/s · eta {eta:,.0f}s")

        def run():
            res = None
            try:
                res = opngx.render_video(
                    st.meta.bin_path, out, mode=o["mode"], brightness=o["brightness"], contrast=o["contrast"],
                    gamma=o["gamma"], start=start, count=n, fps=fps, crf=q, preset=preset, codec=key,
                    crop=crop, progress=pgs,
                    should_cancel=lambda: self._stop or st._cancel_requested,
                )
                res["crop"] = crop
                res["start"] = start
                res["mode"] = o
            except Exception as exc:  # noqa: BLE001
                res = {"error": str(exc)}
            self._sig.finished.emit(res)

        threading.Thread(target=run, daemon=True, name="opngx-video").start()

    def _on_progress(self, done: int, total: int) -> None:
        self.prog.setValue(int(1000 * done / max(1, total)))
        self.studio._sig.progress.emit(done, total, 0.0)

    def _on_finished(self, res) -> None:
        st = self.studio
        self._busy = False
        st._running = False
        st._sig.state.emit(False)
        self.go.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if "error" in res:
            self.stat.setText("failed: " + res["error"][:400])
            st._log(f"video failed: {res['error']}", "err")
            return
        size = os.path.getsize(res["output"]) if os.path.exists(res["output"]) else 0
        tail = " — STOPPED" if res.get("cancelled") else ""
        self._last_out = res["output"]
        self._last = res
        self.open_btn.setEnabled(True)
        self.check_btn.setEnabled(bool(res.get("lossless")) and not res.get("cancelled"))
        self.stat.setText(f"done: {res['frames_written']:,} frames · {size / 1e6:,.1f} MB · "
                          f"{res['seconds']:.1f} s ({res['codec']}){tail}")
        st._log(f"video: {res['frames_written']:,} frames → {res['output']} ({size:,} bytes, "
                f"{res['codec']}){tail}", "warn" if res.get("cancelled") else "ok")

    def _show_file(self) -> None:
        if self._last_out:
            from PySide6 import QtGui

            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(self._last_out)))

    def _check_exact(self) -> None:
        res = getattr(self, "_last", None)
        if not res:
            return
        st = self.studio
        self.check_btn.setEnabled(False)
        self.check_lbl.setText("decoding and comparing…")

        def run():
            try:
                import numpy as np

                from opngx.quality import build_lut
                from opngx.video import resolve_transform

                m = st.meta
                o = res["mode"]
                b, c, g = resolve_transform(m, o["mode"], o["brightness"], o["contrast"], o["gamma"])
                lut = np.asarray(build_lut(b, c, g), np.uint8)
                crop = res.get("crop") or (0, 0, m.width, m.height)
                x, y, w, h = crop
                dec = _video.decode_video_gray(res["output"], w, h)
                raw = np.memmap(m.bin_path, np.uint8, "r")
                n = len(dec)
                bad = 0
                for i in range(n):
                    o0 = (res["start"] + i) * m.frame_stride + 8
                    f = raw[o0 : o0 + m.width * m.height].reshape(m.height, m.width)[y : y + h, x : x + w]
                    if not np.array_equal(lut[f], dec[i]):
                        bad += 1
                ok = bad == 0 and n == res["frames_written"]
                self._sig.check.emit(
                    f"✓ bit-exact: all {n:,} decoded frames equal the extracted pixels." if ok else
                    f"✗ {bad:,} of {n:,} frames differ (expected {res['frames_written']:,} frames).")
            except Exception as exc:  # noqa: BLE001
                self._sig.check.emit(f"check failed: {exc}")

        threading.Thread(target=run, daemon=True, name="opngx-video-check").start()
