"""opngx studio — Qt edition.

A complete redesign of the desktop UI using PySide6/Qt:

* real CSS styling via Qt Style Sheets (QSS) — gradients, radii, hover states
* layout managers + splitters: the window resizes flawlessly at any size
* rich HTML tooltips on every control; Help → Field guide documents them all
* drag & drop a .bin anywhere on the window to load it
* worker thread with Qt signals — the UI never freezes

Launch:  opngx-ui   (uses this Qt app when PySide6 is installed,
                     otherwise falls back to the Tkinter edition)
"""

from __future__ import annotations

import glob
import os
import threading
import time
from typing import Any, Optional

import opngx

# --------------------------------------------------------------------------- #
#  Qt import guard so the package stays installable without PySide6
# --------------------------------------------------------------------------- #
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal

    _QT = True
except Exception:  # pragma: no cover
    _QT = False


QSS = """
* { font-family: 'Segoe UI', 'Ubuntu', 'DejaVu Sans', sans-serif; }

QMainWindow, QDialog { background: #0f172a; }
QWidget#root        { background: #0f172a; }

/* ---------- header ---------- */
QLabel#title {
    color: #f8fafc; font-size: 21px; font-weight: 700;
}
QLabel#subtitle { color: #64748b; font-size: 11px; }
QLabel#chip {
    background: #1e293b; color: #94a3b8;
    border: 1px solid #334155; border-radius: 11px;
    padding: 3px 12px; font-size: 11px;
}

/* ---------- cards ---------- */
QFrame#card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 14px;
}
QLabel#cardtitle {
    color: #94a3b8; font-size: 11px; font-weight: 600;
    letter-spacing: 1px;
}
QLabel#hint { color: #64748b; font-size: 11px; }

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0b1220; color: #e2e8f0;
    border: 1px solid #334155; border-radius: 8px;
    padding: 7px 10px; selection-background-color: #3b82f6;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #0b1220; color: #e2e8f0;
    selection-background-color: #3b82f6;
    border: 1px solid #334155;
}

/* ---------- buttons ---------- */
QPushButton {
    background: #273449; color: #e2e8f0;
    border: 1px solid #334155; border-radius: 9px;
    padding: 9px 18px; font-weight: 500;
}
QPushButton:hover  { background: #334155; }
QPushButton:pressed{ background: #3b4a63; }
QPushButton:disabled { color: #475569; background: #16202f; }
QPushButton#accent {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #3b82f6, stop:1 #2563eb);
    color: white; border: none; font-weight: 700; padding: 10px 26px;
}
QPushButton#accent:hover { background: #2563eb; }
QPushButton#danger {
    background: #dc2626; color: white; border: none; font-weight: 700;
}
QPushButton#danger:hover { background: #b91c1c; }
QPushButton#danger:disabled { background: #3f1d1d; color: #7f5252; }

/* ---------- radio / check ---------- */
QRadioButton, QCheckBox { color: #cbd5e1; spacing: 7px; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 8px;
    border: 2px solid #475569; background: #0b1220;
}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.6, fx:0.5, fy:0.5,
                stop:0 #93c5fd, stop:0.55 #3b82f6, stop:0.56 #3b82f6);
    border-color: #60a5fa;
}
QRadioButton:hover, QCheckBox:hover { color: #e2e8f0; }

/* ---------- sliders ---------- */
QSlider::groove:horizontal {
    height: 6px; background: #0b1220; border-radius: 3px;
}
QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 3px; }
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
    background: #e2e8f0; border: 2px solid #3b82f6;
}
QSlider::handle:horizontal:hover { background: white; }

/* ---------- progress ---------- */
QProgressBar {
    background: #0b1220; border-radius: 7px; height: 14px;
    text-align: center; color: transparent; border: 1px solid #334155;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #3b82f6, stop:1 #60a5fa);
    border-radius: 6px;
}

/* ---------- table / log / splitters ---------- */
QTableWidget {
    background: #0b1220; color: #dbe4f0; gridline-color: #1e293b;
    border: 1px solid #334155; border-radius: 10px;
    selection-background-color: #1d4ed8;
}
QHeaderView::section {
    background: #16202f; color: #94a3b8; border: none;
    padding: 6px; font-size: 11px;
}
QPlainTextEdit, QTextBrowser {
    background: #0b1220; color: #cbd5e1;
    border: 1px solid #334155; border-radius: 10px;
    font-family: 'Cascadia Mono', Consolas, monospace; font-size: 12px;
}
QSplitter::handle { background: #0f172a; width: 5px; height: 5px; }
QSplitter::handle:hover { background: #3b82f6; }

/* ---------- scrollbars ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #334155; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #475569; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #334155; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

/* ---------- menus ---------- */
QMenuBar { background: #0f172a; color: #cbd5e1; }
QMenuBar::item:selected { background: #1e293b; border-radius: 6px; }
QMenu { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; }
QMenu::item:selected { background: #3b82f6; }

QToolTip {
    background: #0b1220; color: #dbe4f0;
    border: 1px solid #3b82f6; border-radius: 8px; padding: 8px;
}
"""


class WorkerSignals(QtCore.QObject):
    """Thread-safe bridge from the extraction worker into the UI."""

    progress = Signal(int, int, float)
    log = Signal(str, str)
    done = Signal(object)
    error = Signal(str)
    state = Signal(bool)


FIELD_GUIDE = """
<h2 style='color:#60a5fa'>Field guide</h2>
<p>Every control in opngx studio, explained.</p>

<h3 style='color:#93c5fd'>Source</h3>
<b>Path</b> — one .bin recording, or a folder containing
&lt;camera&gt;/&lt;name&gt;.bin pairs when <i>Batch folder</i> is selected.<br>
<b>Probe</b> — reads metadata only: geometry, frame count, framerate,
exposure and the vendor's display settings. Nothing is extracted.<br>
<b>Drag &amp; drop</b> — drop a .bin file anywhere on this window.

<h3 style='color:#93c5fd'>Quality mode</h3>
<b>reference</b> — reproduces the vendor player's display transform exactly.
Output pixels match Optronis-exported PNGs bit-for-bit (verified).<br>
<b>raw</b> — sensor bytes unchanged. The vendor transform clips bright
pixels at raw ≥ 139; raw mode keeps them. Maximum fidelity.<br>
<b>custom</b> — your own brightness / contrast / gamma.
Formula: out = clamp(round((v+B)·(1+C/50)), 0..255), gamma applied after.

<h3 style='color:#93c5fd'>Frame range</h3>
<b>start</b> — first frame index (0-based). <b>count</b> — how many frames;
empty/0 means everything remaining.

<h3 style='color:#93c5fd'>Container</h3>
<b>bit depth</b> — 8 matches vendor exports; 16 stores each value ×257
(no extra detail, source is 8-bit; PNG only).<br>
<b>channels</b> — rgba is the full vendor-like container; gray writes
single-channel images: identical pixels, ~2.5× faster, ~36% smaller.<br>
<b>format</b> — png (lossless default), jpg (lossy, quality slider),
bmp (lossless paletted grayscale), tif (lossless uncompressed grayscale).
The extension follows automatically unless you type your own.

<h3 style='color:#93c5fd'>Engine</h3>
<b>jobs</b> — worker threads; defaults to every logical core of this
machine. Expect ≈(cores×100)% total CPU during extraction.<br>
<b>level</b> — DEFLATE effort 1–12: 1–2 fastest/larger, 6 balanced
(vendor-like size), 9+ smallest/slowest.

<h3 style='color:#93c5fd'>Sidecar exports</h3>
<b>timestamps CSV</b> — per-frame camera-clock ticks for timing analysis.<br>
<b>metadata JSON</b> — geometry/settings/engine provenance record.
"""

MODES_GUIDE = """
<h2 style='color:#60a5fa'>Quality modes explained</h2>
<b>reference</b> — what the vendor player shows. Applies the display curve
from the recording's .footage sidecar. Verified pixel-exact against
Optronis exports.<br><br>
<b>raw</b> — what the sensor captured. Identity mapping; preserves the
highlights that reference mode clips at raw ≥ 139. Strictly more
informative.<br><br>
<b>custom</b> — same formula as reference with your numbers.
Gamma &gt; 1 brightens midtones, &lt; 1 darkens.
"""

TUNING_GUIDE = """
<h2 style='color:#60a5fa'>Performance tuning</h2>
<b>jobs</b> — auto-set to all logical cores. Extraction scales nearly
linearly because every frame is independent work.<br><br>
<b>level</b> — compression dominates runtime:
<table cellpadding=4>
<tr><td>1–2</td><td>fastest (2–5× vs 6), slightly larger files</td></tr>
<tr><td>3</td><td>throughput sweet spot</td></tr>
<tr><td>6</td><td>default — size parity with vendor exports</td></tr>
<tr><td>9+</td><td>smallest files, several times slower</td></tr>
</table><br>
<b>channels=gray</b> compresses 77 KB instead of 307 KB per frame →
~2.5× faster.<br><br>
<b>GPU</b> — detected and shown in the header. GPU compression libraries
are not yet production-ready for AMD (hipCOMP preview) and are CUDA-only
for NVIDIA, so opngx uses all CPU cores — measurably faster at these
frame sizes.
"""


def chip(text: str) -> "QtWidgets.QLabel":
    lbl = QtWidgets.QLabel(text)
    lbl.setObjectName("chip")
    return lbl


def _detect_gpus() -> list[str]:
    try:
        from opngx._engine import detect_gpus

        return detect_gpus()
    except Exception:
        return []


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("opngx studio")
        self.resize(1180, 800)
        self.setMinimumSize(980, 680)
        self.setAcceptDrops(True)

        self.meta: Optional[opngx.FootageMetadata] = None
        self._running = False
        self._cancel_requested = False
        self._t_start = 0.0
        self._sig = WorkerSignals()
        self._sig.progress.connect(self._on_progress)
        self._sig.log.connect(self._log)
        self._sig.done.connect(self._on_done)
        self._sig.error.connect(self._on_error)
        self._sig.state.connect(self._set_state)

        self._menu()
        self._build()

    # ------------------------------------------------------------- helpers
    def _card(self, title: str) -> tuple["QtWidgets.QFrame", "QtWidgets.QVBoxLayout"]:
        card = QtWidgets.QFrame()
        card.setObjectName("card")
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)
        t = QtWidgets.QLabel(title.upper())
        t.setObjectName("cardtitle")
        v.addWidget(t)
        return card, v

    @staticmethod
    def _tip(widget: QtWidgets.QWidget, title: str, body: str) -> None:
        widget.setToolTip(
            f"<div style='max-width:420px'>"
            f"<b style='color:#60a5fa'>{title}</b><br>{body}</div>"
        )

    # ---------------------------------------------------------------- menu
    def _menu(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("&File")
        act_open = QtGui.QAction("Open .bin…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._pick_bin)
        m_file.addAction(act_open)
        act_quit = QtGui.QAction("Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_help = mb.addMenu("&Help")
        g1 = QtGui.QAction("Field guide — what every control means", self)
        g1.setShortcut("F1")
        g1.triggered.connect(lambda: self._guide("Field guide", FIELD_GUIDE))
        m_help.addAction(g1)
        g2 = QtGui.QAction("Quality modes explained", self)
        g2.triggered.connect(lambda: self._guide("Quality modes", MODES_GUIDE))
        m_help.addAction(g2)
        g3 = QtGui.QAction("Performance tuning", self)
        g3.triggered.connect(lambda: self._guide("Tuning", TUNING_GUIDE))
        m_help.addAction(g3)
        m_help.addSeparator()
        about = QtGui.QAction("About", self)
        about.triggered.connect(self._about)
        m_help.addAction(about)

    def _guide(self, title: str, html: str) -> None:
        d = QtWidgets.QDialog(self)
        d.setWindowTitle(title)
        d.resize(720, 560)
        v = QtWidgets.QVBoxLayout(d)
        tb = QtWidgets.QTextBrowser()
        tb.setHtml(html)
        v.addWidget(tb)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(d.accept)
        v.addWidget(close)
        d.exec()

    def _about(self) -> None:
        gpus = ", ".join(_detect_gpus()) or "none detected"
        QtWidgets.QMessageBox.information(
            self,
            "About opngx",
            f"<h3>opngx {opngx.__version__}</h3>"
            f"engine: {opngx.engine_backend()}<br>"
            f"cpus: {os.cpu_count()} logical • gpus: {gpus}<br><br>"
            "Pixel-exact Optronis .bin → PNG/JPG/BMP/TIFF extraction.<br>"
            "All CPU cores used by default. MIT licensed.",
        )

    # --------------------------------------------------------------- build
    def _build(self) -> None:
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(18, 12, 18, 14)
        outer.setSpacing(10)

        # ---------------- header ----------------
        head = QtWidgets.QHBoxLayout()
        logo_box = QtWidgets.QVBoxLayout()
        t = QtWidgets.QLabel("opngx studio")
        t.setObjectName("title")
        s = QtWidgets.QLabel("Optronis footage → images · pixel-exact · all cores")
        s.setObjectName("subtitle")
        logo_box.addWidget(t)
        logo_box.addWidget(s)
        head.addLayout(logo_box)
        head.addStretch(1)

        gpus = (
            ", ".join(
                g.split("(")[1].rstrip(")").split(",")[0].strip()
                for g in _detect_gpus()
            )
            or "no GPU"
        )
        for txt in (
            f"{os.cpu_count()} cores",
            gpus,
            opngx.engine_backend().split("(")[0].strip(),
        ):
            head.addWidget(chip(txt))
        outer.addLayout(head)

        # ---------------- splitter body ----------------
        split = QtWidgets.QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)

        # ===== left column =====
        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(10)

        # --- source card ---
        src_card, sv = self._card("source footage")
        row = QtWidgets.QHBoxLayout()
        self.bin_edit = QtWidgets.QLineEdit()
        self.bin_edit.setPlaceholderText(
            "path to .bin … or just drag a file onto this window"
        )
        browse = QtWidgets.QPushButton("Browse…")
        probe = QtWidgets.QPushButton("Probe")
        row.addWidget(self.bin_edit, 1)
        row.addWidget(browse)
        row.addWidget(probe)
        sv.addLayout(row)
        scope_row = QtWidgets.QHBoxLayout()
        self.rb_single = QtWidgets.QRadioButton("Single bin")
        self.rb_batch = QtWidgets.QRadioButton("Batch folder")
        self.rb_single.setChecked(True)
        scope_row.addWidget(self.rb_single)
        scope_row.addWidget(self.rb_batch)
        scope_row.addStretch(1)
        sv.addLayout(scope_row)
        lv.addWidget(src_card)

        self._tip(
            self.bin_edit,
            "Recording path",
            "One .bin recording, or a folder of recordings when "
            "<i>Batch folder</i> is checked.",
        )
        self._tip(browse, "Browse", "Pick the recording with a file dialog.")
        self._tip(
            probe,
            "Probe",
            "Read metadata only — geometry, frames, fps, exposure "
            "and vendor display settings. Nothing extracted.",
        )
        self._tip(self.rb_single, "Single bin", "Extract exactly one recording.")
        self._tip(
            self.rb_batch,
            "Batch folder",
            "Walk the folder tree and extract every *.bin found.",
        )

        # --- settings card ---
        set_card, tv = self._card("extraction settings")

        # quality mode segmented row
        mode_row = QtWidgets.QHBoxLayout()
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.modes: dict[str, QtWidgets.QRadioButton] = {}
        for key, label in (
            ("reference", "reference"),
            ("raw", "raw"),
            ("custom", "custom"),
        ):
            rb = QtWidgets.QRadioButton(label)
            rb.setChecked(key == "reference")
            self.mode_group.addButton(rb)
            self.modes[key] = rb
            mode_row.addWidget(rb)
        mode_row.addStretch(1)
        tv.addLayout(mode_row)
        self._tip(
            self.modes["reference"],
            "reference mode",
            "Vendor display transform (B49/C18). Output pixels match "
            "Optronis exports bit-for-bit.",
        )
        self._tip(
            self.modes["raw"],
            "raw mode",
            "Identity mapping — nothing clipped or shifted. The most "
            "faithful data possible.",
        )
        self._tip(
            self.modes["custom"], "custom mode", "Your brightness/contrast/gamma below."
        )

        bcg = QtWidgets.QHBoxLayout()
        self.b_spin = QtWidgets.QDoubleSpinBox()
        self.b_spin.setRange(-255, 255)
        self.b_spin.setValue(49)
        self.c_spin = QtWidgets.QDoubleSpinBox()
        self.c_spin.setRange(0, 200)
        self.c_spin.setValue(18)
        self.g_spin = QtWidgets.QDoubleSpinBox()
        self.g_spin.setRange(0.1, 4.0)
        self.g_spin.setValue(1.0)
        self.g_spin.setSingleStep(0.05)
        for lbl, w, tip_t, tip_b in (
            (
                "B",
                self.b_spin,
                "Brightness",
                "Offset added to every raw byte before scaling.",
            ),
            (
                "C",
                self.c_spin,
                "Contrast",
                "Multiplier = 1 + C/50. Vendor default 18 → 1.36×.",
            ),
            ("γ", self.g_spin, "Gamma", "Applied after B/C. 1.0 = off."),
        ):
            box = QtWidgets.QHBoxLayout()
            lab = QtWidgets.QLabel(lbl)
            box.addWidget(lab)
            box.addWidget(w)
            bcg.addLayout(box)
            self._tip(w, tip_t, tip_b)
        bcg.addStretch(1)
        tv.addLayout(bcg)

        # range
        rng = QtWidgets.QHBoxLayout()
        rng.addWidget(QtWidgets.QLabel("start"))
        self.start_spin = QtWidgets.QSpinBox()
        self.start_spin.setRange(0, 10**9)
        rng.addWidget(self.start_spin)
        rng.addSpacing(12)
        rng.addWidget(QtWidgets.QLabel("count"))
        self.count_spin = QtWidgets.QSpinBox()
        self.count_spin.setRange(0, 10**9)
        self.count_spin.setSpecialValueText("all")
        rng.addWidget(self.count_spin)
        rng.addStretch(1)
        tv.addLayout(rng)
        self._tip(self.start_spin, "start", "Index of the first frame (0-based).")
        self._tip(
            self.count_spin,
            "count",
            "Frames to extract from start. 0 (= “all”) takes everything remaining.",
        )

        # container grid
        cont = QtWidgets.QGridLayout()
        cont.setHorizontalSpacing(14)
        self.depth_combo = QtWidgets.QComboBox()
        self.depth_combo.addItems(["8", "16"])
        self.chan_combo = QtWidgets.QComboBox()
        self.chan_combo.addItems(["rgba", "gray"])
        self.fmt_combo = QtWidgets.QComboBox()
        self.fmt_combo.addItems(["png", "jpg", "bmp", "tif"])
        self.jpg_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.jpg_slider.setRange(40, 100)
        self.jpg_slider.setValue(90)
        self.jpg_label = QtWidgets.QLabel("90")
        rows = (
            (
                "bit depth",
                self.depth_combo,
                "Bit depth",
                "8 matches vendor exports; 16 stores values ×257 "
                "(no extra detail; PNG only).",
            ),
            (
                "channels",
                self.chan_combo,
                "Channels",
                "rgba = vendor-like container; gray = single channel, "
                "identical pixels, ~2.5× faster.",
            ),
            (
                "format",
                self.fmt_combo,
                "Format",
                "png lossless · jpg lossy+small · bmp/tif lossless. "
                "Extension follows automatically.",
            ),
            (
                "jpeg q",
                self.jpg_slider,
                "JPEG quality",
                "40–100. Higher = better fidelity, bigger files.",
            ),
        )
        for r, (lbl, w, tt, tb_) in enumerate(rows):
            cont.addWidget(QtWidgets.QLabel(lbl), r, 0)
            if isinstance(w, QtWidgets.QSlider):
                h = QtWidgets.QHBoxLayout()
                h.addWidget(w, 1)
                h.addWidget(self.jpg_label)
                cont.addLayout(h, r, 1)
            else:
                cont.addWidget(w, r, 1)
            self._tip(w, tt, tb_)
        self.jpg_slider.valueChanged.connect(
            lambda v_: self.jpg_label.setText(str(int(v_)))
        )
        tv.addLayout(cont)

        # engine sliders
        eng = QtWidgets.QGridLayout()
        maxcores = max((os.cpu_count() or 4) * 2, 8)
        self.jobs_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.jobs_slider.setRange(1, maxcores)
        self.jobs_slider.setValue(os.cpu_count() or 4)
        self.jobs_label = QtWidgets.QLabel(str(self.jobs_slider.value()))
        self.level_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.level_slider.setRange(1, 12)
        self.level_slider.setValue(6)
        self.level_label = QtWidgets.QLabel("6")
        eng.addWidget(QtWidgets.QLabel("jobs"), 0, 0)
        eng.addWidget(self.jobs_slider, 0, 1)
        eng.addWidget(self.jobs_label, 0, 2)
        eng.addWidget(QtWidgets.QLabel("level"), 1, 0)
        eng.addWidget(self.level_slider, 1, 1)
        eng.addWidget(self.level_label, 1, 2)
        eng.setColumnStretch(1, 1)
        tv.addLayout(eng)
        self.jobs_slider.valueChanged.connect(
            lambda v_: self.jobs_label.setText(str(int(v_)))
        )
        self.level_slider.valueChanged.connect(
            lambda v_: self.level_label.setText(str(int(v_)))
        )
        self._tip(
            self.jobs_slider,
            "Worker threads (auto-detected)",
            f"This machine reports {os.cpu_count()} logical cores. "
            "Expect ≈(cores×100)% total CPU while extracting.",
        )
        self._tip(
            self.level_slider,
            "Compression level",
            "DEFLATE effort: 1–2 fast/large · 3 sweet spot · 6 default · "
            "9+ smallest/slowest.",
        )

        # sidecars
        side = QtWidgets.QHBoxLayout()
        self.ts_check = QtWidgets.QCheckBox("timestamps CSV")
        self.ts_check.setChecked(True)
        self.mj_check = QtWidgets.QCheckBox("metadata JSON")
        self.mj_check.setChecked(True)
        side.addWidget(self.ts_check)
        side.addWidget(self.mj_check)
        side.addStretch(1)
        tv.addLayout(side)
        self._tip(
            self.ts_check,
            "Timestamps export",
            "Writes prefix_timestamps.csv: index, raw tick, hex.",
        )
        self._tip(
            self.mj_check,
            "Metadata export",
            "Writes metadata.json with geometry/settings/engine info.",
        )

        lv.addWidget(set_card)
        lv.addStretch(1)

        # --- output card ---
        out_card, ov = self._card("output")
        orow = QtWidgets.QHBoxLayout()
        self.out_edit = QtWidgets.QLineEdit()
        obrowse = QtWidgets.QPushButton("Choose…")
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(obrowse)
        ov.addLayout(orow)
        nrow = QtWidgets.QHBoxLayout()
        nrow.addWidget(QtWidgets.QLabel("prefix"))
        self.prefix_edit = QtWidgets.QLineEdit("brow_")
        self.prefix_edit.setMaximumWidth(90)
        nrow.addWidget(self.prefix_edit)
        nrow.addSpacing(10)
        nrow.addWidget(QtWidgets.QLabel("ext"))
        self.ext_edit = QtWidgets.QLineEdit(".Png")
        self.ext_edit.setMaximumWidth(70)
        nrow.addWidget(self.ext_edit)
        nrow.addStretch(1)
        ov.addLayout(nrow)
        lv.addWidget(out_card)
        self._tip(
            self.prefix_edit,
            "Filename prefix",
            "Files become prefix + 5-digit index + ext, e.g. brow_00000.Png.",
        )
        self._tip(
            self.ext_edit,
            "Extension",
            "Follows the format dropdown unless you type your own.",
        )
        self._tip(obrowse, "Choose…", "Select the output directory.")
        self.fmt_combo.currentTextChanged.connect(self._fmt_changed)

        split.addWidget(left)

        # ===== right column =====
        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(10)

        vsplit = QtWidgets.QSplitter(Qt.Vertical)
        vsplit.setChildrenCollapsible(False)

        info_card, iv = self._card("recording info")
        self.info_table = QtWidgets.QTableWidget(0, 2)
        self.info_table.horizontalHeader().setStretchLastSection(True)
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.info_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.info_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents
        )
        self.info_table.setHorizontalHeaderLabels(["field", "value"])
        iv.addWidget(self.info_table)
        vsplit.addWidget(info_card)
        self._tip(
            self.info_table,
            "Metadata",
            "Filled by Probe. 'operating point' shows whether output is "
            "guaranteed pixel-identical to vendor exports.",
        )

        log_card, gv = self._card("log")
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        gv.addWidget(self.log_view)
        vsplit.addWidget(log_card)

        vsplit.setSizes([340, 260])
        rv.addWidget(vsplit)
        split.addWidget(right)
        split.setSizes([520, 620])

        # ---------------- action bar ----------------
        bar = QtWidgets.QHBoxLayout()
        self.extract_btn = QtWidgets.QPushButton("▶  Extract")
        self.extract_btn.setObjectName("accent")
        self.cancel_btn = QtWidgets.QPushButton("■  Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setEnabled(False)
        verify = QtWidgets.QPushButton("✓  Verify against reference dir…")
        bar.addWidget(self.extract_btn)
        bar.addWidget(self.cancel_btn)
        bar.addWidget(verify)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(16)
        bar.addWidget(self.progress, 1)
        self.status_lbl = QtWidgets.QLabel("idle")
        self.status_lbl.setObjectName("hint")
        bar.addWidget(self.status_lbl)
        outer.addLayout(bar)

        # wiring
        browse.clicked.connect(self._pick_bin)
        probe.clicked.connect(self._probe)
        obrowse.clicked.connect(self._pick_out)
        self.extract_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)
        verify.clicked.connect(self._verify)

        self._log(
            f"opngx {opngx.__version__} ready — engine: {opngx.engine_backend()}", "ok"
        )
        if opngx.engine_backend() == "python-fallback":
            for line in opngx.engine_diagnostics():
                self._log("  " + line, "warn")

    # ------------------------------------------------------------ dnd
    def dragEnterEvent(self, e: Any) -> None:
        urls = e.mimeData().urls() if hasattr(e, "mimeData") else []
        if urls and urls[0].toLocalFile().lower().endswith(".bin"):
            e.acceptProposedAction()

    def dropEvent(self, e: Any) -> None:
        p = e.mimeData().urls()[0].toLocalFile()
        self.bin_edit.setText(p)
        self.rb_single.setChecked(True)
        self._probe()

    # ------------------------------------------------------------- actions
    def _fmt_changed(self, fmt: str) -> None:
        extmap = {"png": ".Png", "jpg": ".jpg", "bmp": ".bmp", "tif": ".tif"}
        cur = self.ext_edit.text()
        if cur in extmap.values():
            self.ext_edit.setText(extmap.get(fmt, ".Png"))

    def _log(self, msg: str, tag: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        colors = {
            "info": "#94a3b8",
            "ok": "#34d399",
            "warn": "#fbbf24",
            "err": "#f87171",
        }
        self.log_view.appendHtml(
            f"<span style='color:#475569'>[{stamp}]</span> "
            f"<span style='color:{colors.get(tag, '#94a3b8')}'>{msg}</span>"
        )

    def _pick_bin(self) -> None:
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open recording", "", "Optronis footage (*.bin);;All files (*)"
        )
        if p:
            self.bin_edit.setText(p)
            self.rb_single.setChecked(True)
            self._probe()

    def _pick_out(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Output directory")
        if d:
            self.out_edit.setText(d)

    def _probe(self) -> None:
        target = self.bin_edit.text().strip()
        if not target:
            return
        if self.rb_batch.isChecked():
            bins = sorted(glob.glob(os.path.join(target, "*", "*.bin"))) + sorted(
                glob.glob(os.path.join(target, "*.bin"))
            )
            self._fill_info(
                [
                    ("scope", "batch folder"),
                    ("folder", target),
                    ("bins found", str(len(bins))),
                ]
            )
            self._log(f"batch scan: {len(bins)} bin(s) under {target}")
            return
        try:
            m = opngx.probe(target)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "probe failed", str(exc))
            return
        self.meta = m
        self._fill_info(
            [
                ("camera", m.camera_name or "?"),
                ("geometry", f"{m.width} × {m.height} px"),
                ("frames in XML", f"{m.num_images:,}" if m.num_images > 0 else "?"),
                ("capacity from size", f"{m.capacity_frames:,}"),
                ("frame stride", f"{m.frame_stride:,} B"),
                ("framerate", f"{m.framerate:g} fps" if m.framerate > 0 else "?"),
                ("exposure", f"{m.exposure_us:g} µs" if m.exposure_us > 0 else "?"),
                ("display B/C/G", f"{m.brightness:g} / {m.contrast:g} / {m.gamma:g}"),
                (
                    "operating point",
                    "✔ verified pixel-exact"
                    if m.verified_operating_point
                    else "⚠ unverified — fidelity not guaranteed",
                ),
            ]
        )
        self._log(f"probed {os.path.basename(m.bin_path)}")
        if not self.out_edit.text():
            self.out_edit.setText(
                os.path.join(
                    os.path.dirname(m.bin_path),
                    m.camera_name.replace(".", "_") + "_png",
                )
            )

    def _fill_info(self, rows) -> None:
        self.info_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.info_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.info_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))

    def _collect_opts(self) -> dict[str, Any]:
        return dict(
            mode=self.modes[self.mode_group.checkedButton().text()].text()
            if False
            else next(k for k, rb in self.modes.items() if rb.isChecked()),
            brightness=self.b_spin.value(),
            contrast=self.c_spin.value(),
            gamma=self.g_spin.value(),
            bit_depth=int(self.depth_combo.currentText()),
            channels=0 if self.chan_combo.currentText() == "gray" else 6,
            fmt=self.fmt_combo.currentText(),
            jpeg_quality=int(self.jpg_slider.value()),
            jobs=int(self.jobs_slider.value()),
            level=int(self.level_slider.value()),
            prefix=self.prefix_edit.text(),
            ext=self.ext_edit.text(),
            start=int(self.start_spin.value()),
            frames=(int(self.count_spin.value()) or None),
            export_timestamps=self.ts_check.isChecked(),
            export_metadata=self.mj_check.isChecked(),
        )

    def _start(self) -> None:
        if self._running:
            return
        out = self.out_edit.text().strip()
        if not out:
            QtWidgets.QMessageBox.warning(self, "opngx", "Choose an output directory.")
            return
        batch = self.rb_batch.isChecked()
        if batch:
            root_dir = self.bin_edit.text().strip()
            bins = sorted(glob.glob(os.path.join(root_dir, "*", "*.bin"))) + sorted(
                glob.glob(os.path.join(root_dir, "*.bin"))
            )
            if not bins:
                QtWidgets.QMessageBox.warning(self, "opngx", "No .bin files found.")
                return
        else:
            if not self.meta:
                QtWidgets.QMessageBox.warning(self, "opngx", "Probe a bin first.")
                return
            bins = [self.meta.bin_path]

        opts = self._collect_opts()
        self._running = True
        self._cancel_requested = False
        self._sig.state.emit(True)
        self._t_start = time.perf_counter()

        def worker() -> None:
            try:
                last = None
                for b in bins:
                    if self._cancel_requested:
                        break
                    stem = os.path.splitext(os.path.basename(b))[0]
                    od = (
                        out
                        if len(bins) == 1
                        else os.path.join(out, stem.replace(".", "_"))
                    )
                    o = opts
                    self._sig.log.emit(
                        f"extract {os.path.basename(b)} → {od}  "
                        f"[mode={o['mode']} fmt={o['fmt']} depth={o['bit_depth']} "
                        f"ch={o['channels']} jobs={o['jobs']} level={o['level']}]",
                        "info",
                    )
                    ex = opngx.Extractor(b)
                    last = ex.extract(
                        od,
                        progress=lambda d_, t_, dt=time.perf_counter(): (
                            self._sig.progress.emit(
                                d_,
                                t_,
                                d_ / max(time.perf_counter() - self._t_start, 1e-9),
                            )
                        ),
                        should_cancel=lambda: self._cancel_requested,
                        **opts,
                    )
                if last is not None:
                    self._sig.done.emit(last)
            except Exception as exc:  # noqa: BLE001
                self._sig.error.emit(str(exc))
            finally:
                self._running = False
                self._sig.state.emit(False)

        threading.Thread(target=worker, name="opngx-worker", daemon=True).start()

    def _cancel(self) -> None:
        self._cancel_requested = True
        self._log("cancel requested…", "warn")

    def _verify(self) -> None:
        ref = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Reference PNG directory"
        )
        if not ref or not self.out_edit.text().strip():
            QtWidgets.QMessageBox.warning(
                self, "opngx", "Pick both a reference dir and an output dir."
            )
            return

        def run() -> None:
            try:
                rep = opngx.verify(
                    ref, self.out_edit.text().strip(), prefix=self.prefix_edit.text()
                )
                msg = (
                    "<b style='color:#34d399'>PASS</b> — every compared "
                    "frame is pixel-exact."
                    if rep.passed
                    else f"<b style='color:#f87171'>FAIL</b> — "
                    f"{rep.mismatched_files} mismatched file(s).<br>"
                    f"<span style='color:#fbbf24'>{rep.first_error}</span>"
                )
                self._sig.log.emit(f"verify: {rep}", "ok" if rep.passed else "err")
                self._sig.dialog.emit(("verification", msg))
            except Exception as exc:  # noqa: BLE001
                self._sig.error.emit(str(exc))

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------- slots
    def _on_progress(self, done: int, total: int, fps: float) -> None:
        frac = done / max(total, 1)
        self.progress.setValue(int(100 * frac))
        elapsed = time.perf_counter() - self._t_start
        eta = elapsed / frac - elapsed if frac > 0.004 else float("nan")
        eta_txt = f" • eta {eta:,.0f}s" if eta == eta else ""
        self.status_lbl.setText(
            f"{done:,} / {total:,} ({frac * 100:.1f}%) • {fps:,.0f} fps{eta_txt}"
        )
        milestone = max(total // 10, 1)
        if done and done % milestone == 0:
            self._log(
                f"progress: {done:,}/{total:,} ({frac * 100:.0f}%, {fps:,.0f} fps)"
            )

    def _on_done(self, st) -> None:
        cancelled = getattr(st, "cancelled", False)
        self._log(
            f"finished: {st.frames_written:,}/{st.frames_total:,} frames in "
            f"{st.seconds:.2f}s ({st.frames_per_s:,.0f} fps, "
            f"{st.mib_per_s_in:.1f} MiB/s in, backend={st.backend})"
            + ("  — CANCELLED" if cancelled else ""),
            "warn" if cancelled else "ok",
        )
        self.status_lbl.setText(
            f"last run: {st.frames_written:,} frames in {st.seconds:.2f}s"
        )

    def _on_error(self, msg: str) -> None:
        self._log(f"ERROR: {msg}", "err")
        QtWidgets.QMessageBox.critical(self, "opngx", msg)

    def _set_state(self, running: bool) -> None:
        self.extract_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)


def main() -> int:
    if not _QT:
        raise SystemExit(
            "PySide6 is required for the Qt studio UI.\n"
            "  pip install 'opngx[qt]'      (or: uv add pyside6)\n"
            "Falling back to the Tkinter UI is available via: opngx-ui --tk"
        )
    app = QtWidgets.QApplication([])
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
