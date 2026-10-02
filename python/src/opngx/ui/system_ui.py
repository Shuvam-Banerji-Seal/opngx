"""System tab (v2.1): what the studio is running on, what it found, and
built-in checks - so "is something missing / is it slow / is it exact?"
can be answered on the user's own computer, and copied into a bug report.
"""

from __future__ import annotations

import os
import platform
import sys
import tempfile
import threading
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal

import opngx
from opngx.ui import icons as _icons


def _ram_gb() -> str:
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return f"{m.ullTotalPhys / 2**30:.1f} GB"
        with open("/proc/meminfo") as fh:
            kb = int(fh.readline().split()[1])
        return f"{kb / 2**20:.1f} GB"
    except Exception:  # noqa: BLE001
        return "?"


def _cpu_name() -> str:
    try:
        if os.name == "nt":
            import winreg

            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:  # noqa: BLE001
        pass
    return platform.processor() or "?"


def collect() -> list[tuple[str, list[tuple[str, str]]]]:
    """[(section, [(key, value), ...]), ...] - everything the System tab
    shows; also used for the copyable report."""
    from opngx import _engine
    from opngx import video as _video

    secs = []
    app = QtWidgets.QApplication.instance()
    screens = []
    if app is not None:
        for s in app.screens():
            g = s.geometry()
            screens.append(f"{s.name()}: {g.width()}x{g.height()} logical, scaling {s.devicePixelRatio() * 100:.0f}%")
    try:
        from opngx.ui import scaling

        sc = scaling.get()
        ui_scale = f"{sc.factor:.2f}" if sc is not None and hasattr(sc, "factor") else "?"
    except Exception:  # noqa: BLE001
        ui_scale = "?"
    secs.append(("This computer", [
        ("system", f"{platform.system()} {platform.release()} ({platform.version()[:60]})"),
        ("processor", _cpu_name()),
        ("logical cores", str(os.cpu_count())),
        ("memory", _ram_gb()),
        ("graphics", ", ".join(opngx.detect_gpus()) or "none detected"),
        ("screens", " · ".join(screens) or "?"),
        ("studio UI scale", ui_scale),
    ]))
    try:
        from opngx.analysis import native as _an

        an = "C kernels" if _an.available() else "numpy (slower)"
    except Exception:  # noqa: BLE001
        an = "?"
    try:
        from opngx.verify import _engine_binary

        cli = _engine_binary() or "not found (Verify falls back to Python)"
    except Exception:  # noqa: BLE001
        cli = "?"
    secs.append(("opngx", [
        ("version", opngx.__version__),
        ("engine library", _engine.library_path() or "not loaded - Python fallback (much slower)"),
        ("engine backend", opngx.engine_backend()),
        ("engine CLI", cli),
        ("analysis", an),
        ("Python", f"{sys.version.split()[0]} ({'packaged app' if getattr(sys, 'frozen', False) else 'interpreter'})"),
        ("Qt", f"PySide6 {__import__('PySide6').__version__}"),
    ]))
    ff = _video.resolve_ffmpeg()
    ffv = "?"
    if ff:
        try:
            import subprocess

            from opngx._proc import no_window

            r = subprocess.run([ff, "-hide_banner", "-version"], capture_output=True, timeout=15, **no_window())
            ffv = r.stdout.decode(errors="replace").splitlines()[0][:80]
        except Exception:  # noqa: BLE001
            pass
    rows = [("ffmpeg", ff or "NOT FOUND - video export is unavailable"), ("version", ffv)]
    if ff:
        av = _video.available_codecs()
        rows.append(("codecs", "  ".join(f"{k} {'✓' if v else '✗'}" for k, v in av.items())))
        rows.append(("GPU encoder", _video.gpu_encoder() or "none"))
    secs.append(("ffmpeg (video)", rows))
    import opngx.analysis as oa

    from opngx.ui.analysis_ui import user_docs_dir
    from opngx.ui.qt_app import crash_log_path

    secs.append(("Folders", [
        ("your modules", oa.user_modules_dir()),
        ("your docs", user_docs_dir()),
        ("crash log", crash_log_path()),
        ("temp", tempfile.gettempdir()),
    ]))
    return secs


def report_text() -> str:
    out = [f"opngx system report — {time.strftime('%Y-%m-%d %H:%M')}"]
    for sec, rows in collect():
        out.append(f"\n[{sec}]")
        out += [f"  {k}: {v}" for k, v in rows]
    return "\n".join(out)


def speed_test(frames: int = 3000) -> str:
    """Extract a synthetic 256x300 recording (in a temp folder) with the
    default settings; report frames/s, CPU use and time to the first file."""
    import struct

    import numpy as np

    d = tempfile.mkdtemp(prefix="opngx_speed_")
    try:
        rec = os.path.join(d, "speed")
        os.makedirs(rec)
        w, h = 256, 300
        rng = np.random.default_rng(1)
        yy, xx = np.mgrid[0:h, 0:w]
        base = 40 + 8 * rng.standard_normal((h, w))
        with open(os.path.join(rec, "speed.bin"), "wb") as f:
            for i in range(frames):
                r = np.hypot(xx - 128 - 3 * np.sin(i / 40), yy - 150)
                img = base + 90 * np.exp(-((r - 18) ** 2) / 8) + rng.normal(0, 3, (h, w))
                f.write(struct.pack("<Q", 1_000_000 + 2000 * i) + np.clip(img, 0, 255).astype(np.uint8).tobytes())
        with open(os.path.join(rec, "speed.footage"), "w", encoding="utf-8") as fh:
            fh.write("<x><Footage><ResolutionX>256</ResolutionX><ResolutionY>300</ResolutionY>"
                     f"<NumberOfImages>{frames}</NumberOfImages></Footage><SettingsProcessing>"
                     "<Brightness>49</Brightness><Contrast>18</Contrast><Gamma>1</Gamma>"
                     "</SettingsProcessing></x>")
        out = os.path.join(d, "out")
        first = [None]
        t0 = time.perf_counter()

        def watch():
            while first[0] is None and time.perf_counter() - t0 < 300:
                if os.path.isdir(out) and any(n.endswith(".Png") for n in os.listdir(out)):
                    first[0] = time.perf_counter() - t0
                    return
                time.sleep(0.002)

        threading.Thread(target=watch, daemon=True).start()
        c0 = os.times()
        st = opngx.extract(os.path.join(rec, "speed.bin"), out, export_timestamps=True)
        dt = time.perf_counter() - t0
        c1 = os.times()
        cpu = (c1.user - c0.user + c1.system - c0.system) / dt * 100
        cores = os.cpu_count() or 1
        return (f"speed test: {st.frames_written:,} frames in {dt:.2f} s = {st.frames_written / dt:,.0f} frames/s\n"
                f"  CPU {cpu:,.0f}% of {cores * 100}% ({cpu / cores:.0f}% of every core) · backend {st.backend}\n"
                f"  first frame written after {first[0] if first[0] is not None else float('nan'):.3f} s\n"
                f"  (the disk of the temp folder matters too: {tempfile.gettempdir()})")
    finally:
        import shutil

        shutil.rmtree(d, ignore_errors=True)


def format_check(meta, frames: int = 60) -> str:
    """Every image format on the loaded recording: bit-exact or not, error,
    size per frame, speed."""
    import shutil

    import numpy as np

    from opngx import formats
    from opngx.quality import build_lut

    lut = np.asarray(build_lut(meta.brightness, meta.contrast, meta.gamma), np.uint8)
    raw = np.memmap(meta.bin_path, np.uint8, "r")
    n = max(1, min(frames, meta.capacity_frames))
    lines = [f"format check on {os.path.basename(meta.bin_path)}, {n} frames (reference transform):",
             f"  {'format':8}{'bits':>5}  {'exact':6}{'max err':>8}{'PSNR':>9}{'KiB/frame':>11}{'frames/s':>10}"]
    for key, f in formats.FORMATS.items():
        for bits in f.bit_depths:
            d = tempfile.mkdtemp(prefix="opngx_fmt_")
            try:
                t0 = time.perf_counter()
                opngx.Extractor(meta.bin_path).extract(d, fmt=key, bit_depth=bits, frames=n,
                                                       channels=0 if key == "png" else 6)
                dt = time.perf_counter() - t0
                files = sorted(p for p in os.listdir(d) if not p.endswith((".csv", ".json")))
                errs, exact = [], True
                if key == "npy":
                    stack = np.load(os.path.join(d, files[0]))
                    dec = [stack[i] for i in range(len(stack))]
                else:
                    dec = [formats.read_frame(os.path.join(d, p)) for p in files]
                for i, a in enumerate(dec):
                    o = i * meta.frame_stride + 8
                    e = lut[raw[o : o + meta.width * meta.height].reshape(meta.height, meta.width)]
                    if bits == 16:
                        e = e.astype(np.uint16) * 257
                    r = formats.quality_report(e, a)
                    exact &= bool(r.get("exact"))
                    errs.append(r)
                size = sum(os.path.getsize(os.path.join(d, p)) for p in files) / n / 1024
                mx = max(r.get("max_abs_error", 0) for r in errs)
                ps = min(r.get("psnr_db", 0) for r in errs)
                pss = "∞" if ps == float("inf") else f"{ps:.1f} dB"
                lines.append(f"  {key:8}{bits:>5}  {'yes' if exact else 'NO':6}{mx:>8.0f}{pss:>9}{size:>11.1f}{n / dt:>10,.0f}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"  {key:8}{bits:>5}  failed: {exc}")
            finally:
                shutil.rmtree(d, ignore_errors=True)
    return "\n".join(lines)


class _Sig(QtCore.QObject):
    text = Signal(str)
    busy = Signal(bool)
    info = Signal(object)


class SystemView(QtWidgets.QWidget):
    def __init__(self, studio, parent=None) -> None:
        super().__init__(parent)
        self.studio = studio
        self._sig = _Sig()
        self._sig.text.connect(self._append)
        self._sig.busy.connect(self._set_busy)
        self._sig.info.connect(self._fill)
        sc = studio._scaling
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(sc.px(12))

        left, lv = studio._card("system")
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["", ""])
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setWordWrap(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lv.addWidget(self.tree, 1)
        row = QtWidgets.QHBoxLayout()
        for text, icon, fn in (("Refresh", "refresh", self.refresh), ("Copy report", "copy", self.copy_report),
                               ("Open crash log folder", "external", self._open_log)):
            b = QtWidgets.QPushButton(text)
            _icons.set_icon(b, icon, "text")
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lv.addLayout(row)
        outer.addWidget(left, 3)

        right, rv = studio._card("checks")
        hint = QtWidgets.QLabel(
            "<b>Speed test</b> extracts a synthetic recording with the default settings and shows "
            "frames per second, how much of the CPU was used, and how soon the first frame appeared.<br>"
            "<b>Format check</b> writes the loaded recording in every image format, reads each file "
            "back and reports whether it is bit-exact (and the error and size if not).")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        rv.addWidget(hint)
        row2 = QtWidgets.QHBoxLayout()
        self.speed_btn = QtWidgets.QPushButton("Speed test")
        _icons.set_icon(self.speed_btn, "gauge", "text")
        self.speed_btn.clicked.connect(self.run_speed)
        self.fmt_btn = QtWidgets.QPushButton("Format check")
        _icons.set_icon(self.fmt_btn, "image", "text")
        self.fmt_btn.clicked.connect(self.run_formats)
        row2.addWidget(self.speed_btn)
        row2.addWidget(self.fmt_btn)
        row2.addStretch(1)
        rv.addLayout(row2)
        self.out = QtWidgets.QPlainTextEdit()
        self.out.setReadOnly(True)
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.out.setFont(f)
        rv.addWidget(self.out, 1)
        outer.addWidget(right, 3)
        self._loaded = False

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if not self._loaded:
            self._loaded = True
            QtCore.QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        self.tree.clear()
        wait = QtWidgets.QTreeWidgetItem(["…", "collecting"])
        self.tree.addTopLevelItem(wait)

        def run():
            try:
                data = collect()
            except Exception as exc:  # noqa: BLE001
                data = [("error", [("collect", str(exc))])]
            self._sig.info.emit(data)

        threading.Thread(target=run, daemon=True, name="opngx-sysinfo").start()

    def _fill(self, data) -> None:
        self.tree.clear()
        bold = self.font()
        bold.setBold(True)
        for sec, rows in data:
            h = QtWidgets.QTreeWidgetItem([sec, ""])
            h.setFont(0, bold)
            h.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(h)
            for k, v in rows:
                it = QtWidgets.QTreeWidgetItem([f"   {k}", str(v)])
                it.setToolTip(1, str(v))
                self.tree.addTopLevelItem(it)
        self.tree.resizeColumnToContents(0)

    def copy_report(self) -> None:
        txt = report_text()
        QtWidgets.QApplication.clipboard().setText(txt)
        self._append("system report copied to the clipboard.")

    def _open_log(self) -> None:
        from opngx.ui.qt_app import crash_log_path

        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(crash_log_path())))

    def _append(self, s: str) -> None:
        self.out.appendPlainText(s)

    def _set_busy(self, b: bool) -> None:
        self.speed_btn.setEnabled(not b)
        self.fmt_btn.setEnabled(not b)
        if hasattr(self.studio, "logo_mark"):
            self.studio.logo_mark.set_animated(b)

    def _run(self, fn, *a) -> None:
        self._sig.busy.emit(True)

        def run():
            try:
                self._sig.text.emit(fn(*a))
            except Exception as exc:  # noqa: BLE001
                self._sig.text.emit(f"failed: {exc}")
            finally:
                self._sig.busy.emit(False)

        threading.Thread(target=run, daemon=True, name="opngx-check").start()

    def run_speed(self) -> None:
        self._append("speed test running…")
        self._run(speed_test)

    def run_formats(self) -> None:
        if not self.studio.meta:
            self._append("load a recording on the Extract tab first.")
            return
        self._append("format check running…")
        self._run(format_check, self.studio.meta)
