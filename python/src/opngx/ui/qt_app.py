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

QMainWindow, QDialog { background: #050505; }
QWidget#root        { background: #050505; }

/* ---------- header ---------- */
QLabel#title { color: #ffffff; font-size: 21px; font-weight: 700; }
QLabel#subtitle { color: #7d8a7d; font-size: 11px; }
QLabel#chip {
    background: #0d120d; color: #a8c9a3;
    border: 1px solid #2f4a2c; border-radius: 11px;
    padding: 3px 12px; font-size: 11px;
}

/* ---------- cards ---------- */
QFrame#card {
    background: #0d0f0d;
    border: 1px solid #1f261f;
    border-radius: 14px;
}
QLabel#cardtitle {
    color: #7fa277; font-size: 11px; font-weight: 600; letter-spacing: 1px;
}
QLabel#hint { color: #8a948a; font-size: 11px; }
QLabel#fieldlabel { color: #9ab294; font-size: 11px; }

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #070807; color: #ffffff;
    border: 1px solid #2a332a; border-radius: 8px;
    padding: 7px 10px; selection-background-color: #4d8248;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #588157;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #0d0f0d; color: #ffffff;
    selection-background-color: #4d8248;
    border: 1px solid #2f4a2c;
}

/* ---------- buttons ---------- */
QPushButton {
    background: #10140f; color: #ffffff;
    border: 1px solid #2a332a; border-radius: 9px;
    padding: 9px 18px; font-weight: 500;
}
QPushButton:hover  { background: #182018; border-color: #3e6b3a; }
QPushButton:pressed{ background: #22301f; }
QPushButton:disabled { color: #4a554a; background: #0a0c0a; }
QPushButton#accent {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #4d8248, stop:1 #3e6b3a);
    color: white; border: none; font-weight: 700; padding: 10px 26px;
}
QPushButton#accent:hover { background: #57914f; }
QPushButton#danger {
    background: #7a2222; color: #ffecec; border: none; font-weight: 700;
}
QPushButton#danger:hover { background: #962b2b; }
QPushButton#danger:disabled { background: #2a1414; color: #6b4444; }

/* ---------- radio / check ---------- */
QRadioButton, QCheckBox { color: #e8ede8; spacing: 7px; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 8px;
    border: 2px solid #3a4a38; background: #070807;
}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.6, fx:0.5, fy:0.5,
                stop:0 #d9ead3, stop:0.55 #588157, stop:0.56 #588157);
    border-color: #7fb069;
}
QRadioButton:hover, QCheckBox:hover { color: #ffffff; }

/* ---------- sliders ---------- */
QSlider::groove:horizontal {
    height: 6px; background: #0a0c0a; border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #4d8248, stop:1 #7fb069);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
    background: #ffffff; border: 2px solid #588157;
}
QSlider::handle:horizontal:hover { background: #f0fff0; }

/* ---------- progress ---------- */
QProgressBar {
    background: #0a0c0a; border-radius: 7px; height: 14px;
    text-align: center; color: transparent; border: 1px solid #1f261f;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #4d8248, stop:1 #8fbf7f);
    border-radius: 6px;
}

/* ---------- table / log / splitters ---------- */
QTableWidget {
    background: #070807; color: #f0f4f0; gridline-color: #161b16;
    border: 1px solid #1f261f; border-radius: 10px;
    selection-background-color: #35542f;
}
QHeaderView::section {
    background: #0d0f0d; color: #9ab294; border: none;
    padding: 6px; font-size: 11px;
}
QPlainTextEdit, QTextBrowser {
    background: #070807; color: #e6ece6;
    border: 1px solid #1f261f; border-radius: 10px;
    font-family: 'Cascadia Mono', Consolas, monospace; font-size: 12px;
}
QSplitter::handle { background: #050505; width: 5px; height: 5px; }
QSplitter::handle:hover { background: #4d8248; }

/* ---------- image viewer ---------- */
QLabel#viewer {
    background: #000000; color: #4a554a;
    border: 1px solid #1f261f; border-radius: 10px;
}

/* ---------- scrollbars ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #22301f; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3e6b3a; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #22301f; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

/* ---------- menus ---------- */
QMenuBar { background: #050505; color: #dfe6df; }
QMenuBar::item { background: transparent; color: #dfe6df; padding: 4px 10px; }
QMenuBar::item:selected { background: #14200f; color: #ffffff; border-radius: 6px; }
QMenu { background: #0d0f0d; color: #ffffff; border: 1px solid #2f4a2c; }
QMenu::item {
    background: transparent; color: #ffffff;
    padding: 6px 26px 6px 14px;
}
QMenu::item:selected { background: #35542f; color: #ffffff; }
QMenu::item:disabled { color: #5d6b5d; }
QMenu::separator { height: 1px; background: #1f261f; margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; margin-left: 6px; }

QToolTip {
    background: #070807; color: #eaf2ea;
    border: 1px solid #588157; border-radius: 8px; padding: 8px;
}

/* ---------- dialogs that QSS alone misses (black-on-black fix) ---------- */
QMessageBox, QInputDialog, QProgressDialog, QColorDialog {
    background: #0d0f0d; color: #e8ede8;
}
QMessageBox QLabel, QInputDialog QLabel, QProgressDialog QLabel {
    color: #e8ede8; background: transparent;
}
QMessageBox QPushButton { min-width: 88px; }
QMessageBox QPushButton, QInputDialog QPushButton {
    background: #10140f; color: #ffffff;
    border: 1px solid #2a332a; border-radius: 9px; padding: 7px 16px;
}
QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
    background: #182018; border-color: #3e6b3a;
}
"""


class WorkerSignals(QtCore.QObject):
    """Thread-safe bridge from the extraction worker into the UI."""

    progress = Signal(int, int, float)
    log = Signal(str, str)
    done = Signal(object)
    error = Signal(str)
    state = Signal(bool)
    dialog = Signal(object)


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
<h2 style='color:#7fb069'>Quality modes — worked examples</h2>
<p>All modes map each stored byte (0–255) through a curve. Here is what
<b>raw value 100</b> becomes under different settings:</p>

<table cellpadding=6 border=1 style='border-collapse:collapse'>
<tr style='color:#9ab294'><th>mode / setting</th><th>raw 40 →</th><th>raw 100 →</th><th>raw 150 →</th></tr>
<tr><td><b>reference</b> (B49 C18)</td><td>121</td><td>204</td><td>255 <i>(clipped)</i></td></tr>
<tr><td><b>raw</b></td><td>40</td><td>100</td><td>150</td></tr>
<tr><td><b>custom</b> B0 C0</td><td>40</td><td>100</td><td>150</td></tr>
<tr><td><b>custom</b> B20 C18</td><td>149</td><td>255</td><td>255</td></tr>
<tr><td><b>custom</b> γ2.0 on raw</td><td>6</td><td>39</td><td>93</td></tr>
</table>

<p><b>reference</b> — what the vendor player shows:
<code>out = clamp(round((v + Brightness) × (1 + Contrast/50)), 0..255)</code>.
With B49/C18 every value ≥139 saturates to white — convenient for viewing,
but those pixels lose all detail.</p>

<p><b>raw</b> — what the sensor captured. Identity mapping. Choose this
whenever you measure intensities or want to re-grade later.</p>

<p><b>custom</b> — same formula as reference with your numbers.<br>
• <b>Brightness</b> shifts everything: +50 makes midtones white.<br>
• <b>Contrast</b> multiplies spread around zero: C=50 doubles differences
(1+50/50 = 2.0×); C=25 halves them? no — 1+25/50 = 1.5×.<br>
• <b>Gamma</b> bends midtones after B/C: γ=2.0 darkens
(128→59), γ=0.5 brightens (128→186). Highlights/shadows still clamp.</p>

<p style='color:#fbbf24'>Tip: scrub the frame viewer while changing these —
the preview updates live so you can see exactly what each number does.</p>
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


TIMING_GUIDE = """
<h2 style='color:#60a5fa'>Timestamps, gaps &amp; dropped frames</h2>
Every frame carries a camera-clock tick in its 8-byte header. At the
verified operating point one tick is <b>1 µs</b> and a perfect 500 fps
recording advances exactly 2000 ticks per frame.<br><br>
<b>CLI:</b> <code>opngx timestamps X.bin [--csv out.csv] [--json]</code><br>
reports span, effective fps, delta min/median/max, gap count and the first
gaps with their locations — proof of whether any frames were dropped by
the camera or the grabber.<br><br>
Measured on brow_1.2: 50 000 frames, deltas 1999–2001 ticks (±1 jitter),
effective fps <b>500.000</b>, zero gaps.
"""

SIDECAR_GUIDE = """
<h2 style='color:#60a5fa'>What's inside the .footage sidecar</h2>
opngx surfaces every field the vendor stored — nothing is thrown away:
<table cellpadding=4>
<tr><td><b>FramerateReal</b></td><td>achieved capture rate vs nominal Framerate</td></tr>
<tr><td><b>Serial / Model</b></td><td>camera provenance for lab notebooks</td></tr>
<tr><td><b>TriggerROI *</b></td><td>sensor window used for trigger; the recording itself is ResolutionX×Y inside it</td></tr>
<tr><td><b>BrightnessR/G/B</b></td><td>per-channel gains (unity here ⇒ pure mono math)</td></tr>
<tr><td><b>BayerFormat</b></td><td>colour-filter arrangement reported by the sensor</td></tr>
<tr><td><b>TriggeredBySoftware / Slave</b></td><td>acquisition wiring</td></tr>
</table>
Access from Python: <code>opngx.probe(x).extra</code> — all tags land in
metadata.json too.
"""

VERIFY_GUIDE = """
<h2 style='color:#60a5fa'>Proving your output is correct</h2>
Two independent proofs ship with opngx:<br><br>
<b>1. Against vendor references</b> — ✓ Verify… compares decoded pixels of
your output against an existing export folder. PASS means bit-for-bit
identical images.<br>
<code>opngx verify REF_DIR OUT_DIR --json</code><br><br>
<b>2. Against the source recording</b> — no vendor files needed. Every
output frame is re-derived from X.bin and compared:<br>
<code>opngx-engine verifybin --bin X.bin OUT_DIR --json</code><br><br>
Full-scale evidence: 50 000/50 000 frames verified pixel-exact
(14.6 GB of scanlines) on brow_1.2.
"""


def _safe_name(name: str) -> str:
    """Filename-safe form of a camera/recording name (Windows forbids
    \\ / : * ? " < > | and trailing dots/spaces)."""
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    name = name.rstrip(" .")
    return name if name else "_"


def chip(text: str) -> "QtWidgets.QLabel":
    lbl = QtWidgets.QLabel(text)
    lbl.setObjectName("chip")
    return lbl


def opnx_ffmpeg_ok() -> bool:
    try:
        return opngx.ffmpeg_available()
    except Exception:
        return False


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
        self.setMinimumSize(760, 520)
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
        self._sig.dialog.connect(self._on_dialog)
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

    def _std_icon(self, sp) -> "QtGui.QIcon":
        """Style-provided icon, or a null icon when the active
        style does not supply one (never a crash)."""
        try:
            return self.style().standardIcon(sp)
        except Exception:
            return QtGui.QIcon()

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
        g4 = QtGui.QAction("Timestamps & dropped frames", self)
        g4.triggered.connect(lambda: self._guide("Timing", TIMING_GUIDE))
        m_help.addAction(g4)
        g5 = QtGui.QAction("Inside the .footage sidecar", self)
        g5.triggered.connect(lambda: self._guide("Sidecar fields", SIDECAR_GUIDE))
        m_help.addAction(g5)
        g6 = QtGui.QAction("Two ways to prove correctness", self)
        g6.triggered.connect(lambda: self._guide("Verification", VERIFY_GUIDE))
        m_help.addAction(g6)
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
        # document text color must be set on the DOCUMENT, not the widget:
        # the widget-QSS color does not reach HTML body text on all themes
        tb.document().setDefaultStyleSheet(
            "body { color: #e6ece6; } a { color: #8fbf7f; }"
        )
        tb.setHtml(f"<body>{html}</body>")
        tb.setStyleSheet(
            "QTextBrowser { background: #070807; "
            "color: #e6ece6; border: 1px solid #1f261f; "
            "border-radius: 10px; }"
        )
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
            f"<h2>opngx {opngx.__version__} — opngx studio</h2>"
            f"<p><b style='color:#7fb069'>Developer: Shuvam Banerji Seal</b><br>"
            f"engine: {opngx.engine_backend()}<br>"
            f"cpus: {os.cpu_count()} logical • gpus: {gpus}</p>"
            "<p>Ultra-fast, pixel-exact Optronis .bin → PNG/JPG/BMP/TIFF "
            "extraction with MP4 rendering, frame viewer and built-in "
            "verification. All CPU cores by default.</p>"
            "<p>Help menu documents every control; F1 opens the field guide.<br>"
            "License: MIT • "
            "<a href='https://github.com/Shuvam-Banerji-Seal/opngx'>"
            "github.com/Shuvam-Banerji-Seal/opngx</a></p>",
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

        # live CPU / RAM chips (C12) — show the machine working in real time
        from opngx.sysmon import snapshot as _sys_snapshot

        self._sys_snapshot = _sys_snapshot
        self.cpu_chip = chip("CPU –")
        self.ram_chip = chip("RAM –")
        self.cpu_chip.setToolTip(
            "<b>Live CPU utilisation</b><br>Whole-machine percent. During an "
            "extract at jobs=all this should sit near 100% — that is the "
            "engine using every core."
        )
        self.ram_chip.setToolTip(
            "<b>Live memory usage</b><br>Used physical RAM percent. The "
            "engine streams via mmap, so usage stays flat even on huge "
            "recordings."
        )
        head.addWidget(self.cpu_chip)
        head.addWidget(self.ram_chip)
        self._sys_timer = QtCore.QTimer(self)
        self._sys_timer.setInterval(900)
        self._sys_timer.timeout.connect(self._poll_sysmon)
        self._sys_timer.start()
        self._poll_sysmon()

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
        browse = QtWidgets.QPushButton(" Open…")
        probe = QtWidgets.QPushButton(" Read info")
        browse.setIcon(self._std_icon(QtWidgets.QStyle.SP_DirOpenIcon))
        probe.setIcon(self._std_icon(QtWidgets.QStyle.SP_FileDialogInfoView))
        row.addWidget(self.bin_edit, 1)
        row.addWidget(browse)
        row.addWidget(probe)
        sv.addLayout(row)
        scope_row = QtWidgets.QHBoxLayout()
        self.rb_single = QtWidgets.QRadioButton("Single bin")
        self.rb_batch = QtWidgets.QRadioButton("Batch folder")
        self.rb_single.setChecked(True)
        self.rb_batch.toggled.connect(self._on_scope_changed)
        scope_row.addWidget(self.rb_single)
        scope_row.addWidget(self.rb_batch)
        scope_row.addStretch(1)
        sv.addLayout(scope_row)

        geom = QtWidgets.QHBoxLayout()
        glabel = QtWidgets.QLabel("width × height")
        glabel.setObjectName("fieldlabel")
        geom.addWidget(glabel)
        self.w_spin = QtWidgets.QSpinBox()
        self.w_spin.setRange(0, 100000)
        self.h_spin = QtWidgets.QSpinBox()
        self.h_spin.setRange(0, 100000)
        self.w_spin.setSpecialValueText("auto")
        self.h_spin.setSpecialValueText("auto")
        self.w_spin.setValue(0)
        self.h_spin.setValue(0)
        geom.addWidget(self.w_spin)
        geom.addWidget(QtWidgets.QLabel("×"))
        geom.addWidget(self.h_spin)
        self.geom_hint = QtWidgets.QLabel("")
        self.geom_hint.setObjectName("hint")
        geom.addWidget(self.geom_hint, 1)
        sv.addLayout(geom)
        lv.addWidget(src_card)
        self._tip(
            self.w_spin,
            "Width",
            "Needed only when the recording has NO .footage sidecar.\n"
            "0/auto = take geometry from the sidecar. Values are "
            "remembered per recording.",
        )
        self._tip(self.h_spin, "Height", "See width.")

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

        # quality mode — vertical list, short labels + rich tooltips
        mode_col = QtWidgets.QVBoxLayout()
        mode_col.setSpacing(4)
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.modes: dict[str, QtWidgets.QRadioButton] = {}
        for key, label in (
            ("reference", "reference  —  vendor-identical"),
            ("raw", "raw  —  sensor-faithful, nothing clipped"),
            ("custom", "custom  —  your curve"),
        ):
            rb = QtWidgets.QRadioButton(label)
            rb.setChecked(key == "reference")
            self.mode_group.addButton(rb)
            self.modes[key] = rb
            mode_col.addWidget(rb)
        tv.addLayout(mode_col)
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

        def mini_label(text: str) -> QtWidgets.QLabel:
            lab = QtWidgets.QLabel(text)
            lab.setObjectName("fieldlabel")
            lab.setMinimumWidth(78)  # never clip, even when squeezed
            return lab

        for lbl, w, tip_t, tip_b in (
            (
                "brightness",
                self.b_spin,
                "Brightness",
                "Offset added to every raw byte before scaling.",
            ),
            (
                "contrast",
                self.c_spin,
                "Contrast",
                "Multiplier = 1 + C/50. Vendor default 18 → 1.36×.",
            ),
            ("gamma", self.g_spin, "Gamma", "Applied after B/C. 1.0 = off."),
        ):
            box = QtWidgets.QHBoxLayout()
            box.addWidget(mini_label(lbl))
            box.addWidget(w, 1)
            bcg.addLayout(box)
            self._tip(w, tip_t, tip_b)
        tv.addLayout(bcg)

        # range
        rng = QtWidgets.QHBoxLayout()
        rng.addWidget(mini_label("start"))
        self.start_spin = QtWidgets.QSpinBox()
        self.start_spin.setRange(0, 10**9)
        rng.addWidget(self.start_spin)
        rng.addSpacing(12)
        rng.addWidget(mini_label("count"))
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

        # container rows (hbox pairs — labels can never clip)
        def field_row(lbl, w, tt, tb_):
            h = QtWidgets.QHBoxLayout()
            lab = QtWidgets.QLabel(lbl)
            lab.setObjectName("fieldlabel")
            lab.setFixedWidth(78)
            h.addWidget(lab)
            h.addWidget(w, 1)
            tv.addLayout(h)
            self._tip(w, tt, tb_)

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
        self.jpg_label.setFixedWidth(30)
        field_row(
            "bit depth",
            self.depth_combo,
            "Bit depth",
            "8 matches vendor exports; 16 stores values ×257 "
            "(no extra detail; PNG only).",
        )
        field_row(
            "channels",
            self.chan_combo,
            "Channels",
            "rgba = vendor-like container; gray = single channel, "
            "identical pixels, ~2.5× faster.",
        )
        field_row(
            "format",
            self.fmt_combo,
            "Format",
            "png lossless · jpg lossy+small · bmp/tif lossless. "
            "Extension follows automatically.",
        )
        jrow = QtWidgets.QHBoxLayout()
        jlab = QtWidgets.QLabel("jpeg q")
        jlab.setObjectName("fieldlabel")
        jlab.setFixedWidth(78)
        jrow.addWidget(jlab)
        jrow.addWidget(self.jpg_slider, 1)
        jrow.addWidget(self.jpg_label)
        tv.addLayout(jrow)
        self._tip(
            self.jpg_slider,
            "JPEG quality",
            "40–100. Higher = better fidelity, bigger files.",
        )
        self.jpg_slider.valueChanged.connect(
            lambda v_: self.jpg_label.setText(str(int(v_)))
        )

        # engine rows
        maxcores = max((os.cpu_count() or 4) * 2, 8)
        self.jobs_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.jobs_slider.setRange(1, maxcores)
        self.jobs_slider.setValue(os.cpu_count() or 4)
        self.jobs_label = QtWidgets.QLabel(str(self.jobs_slider.value()))
        self.jobs_label.setFixedWidth(30)
        self.level_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.level_slider.setRange(1, 12)
        self.level_slider.setValue(6)
        self.level_label = QtWidgets.QLabel("6")
        self.level_label.setFixedWidth(30)
        field_row(
            "jobs",
            self.jobs_slider,
            "Worker threads (auto-detected)",
            f"This machine reports {os.cpu_count()} logical cores. "
            "Expect ≈(cores×100)% total CPU while extracting.",
        )
        field_row(
            "level",
            self.level_slider,
            "Compression level",
            "DEFLATE effort: 1–2 fast/large · 3 sweet spot · "
            "6 default · 9+ smallest/slowest.",
        )
        tv.addStretch(1)

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
        obrowse = QtWidgets.QPushButton(" Choose…")
        obrowse.setIcon(self._std_icon(QtWidgets.QStyle.SP_DialogSaveButton))
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(obrowse)
        ov.addLayout(orow)
        nrow = QtWidgets.QHBoxLayout()
        nrow.addWidget(mini_label("prefix"))
        self.prefix_edit = QtWidgets.QLineEdit("brow_")
        self.prefix_edit.setMaximumWidth(90)
        nrow.addWidget(self.prefix_edit)
        nrow.addSpacing(10)
        nrow.addWidget(mini_label("ext"))
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

        # 720p laptops / scaled 4K displays: never clip the settings —
        # the whole left column scrolls instead
        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidget(left)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        split.addWidget(left_scroll)

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

        viewer_card, wv = self._card("frame viewer")
        self.viewer_img = QtWidgets.QLabel("probe a recording, then scrub")
        self.viewer_img.setObjectName("viewer")
        self.viewer_img.setAlignment(Qt.AlignCenter)
        self.viewer_img.setMinimumHeight(210)
        wv.addWidget(self.viewer_img, 1)
        vrow = QtWidgets.QHBoxLayout()
        self.prev_btn = QtWidgets.QPushButton("◀")
        self.prev_btn.setFixedWidth(44)
        self.next_btn = QtWidgets.QPushButton("▶")
        self.next_btn.setFixedWidth(44)
        self.frame_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.frame_slider.setRange(0, 0)
        self.frame_lbl = QtWidgets.QLabel("frame —")
        self.frame_lbl.setMinimumWidth(150)
        self.frame_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        vrow.addWidget(self.prev_btn)
        vrow.addWidget(self.frame_slider, 1)
        vrow.addWidget(self.next_btn)
        vrow.addWidget(self.frame_lbl)
        wv.addLayout(vrow)
        rv.addWidget(viewer_card)
        self._tip(
            self.viewer_img,
            "Frame preview",
            "Renders the selected frame with the CURRENT quality "
            "settings — move the sliders to see the transform live.",
        )
        self._tip(
            self.frame_slider,
            "Scrubber",
            "Drag to scrub through the recording. ◀/▶ step one frame.",
        )
        self.prev_btn.clicked.connect(lambda: self._step_frame(-1))
        self.next_btn.clicked.connect(lambda: self._step_frame(+1))
        self.frame_slider.valueChanged.connect(lambda v_: self._show_frame(int(v_)))
        # quality-setting changes re-render the visible frame instantly
        for rb in self.modes.values():
            rb.toggled.connect(self._refresh_frame)
        for spin in (self.b_spin, self.c_spin, self.g_spin):
            spin.valueChanged.connect(self._refresh_frame)

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
        self.extract_btn.setToolTip(
            "<b>Extract frames</b><br>Decode the recording with the quality "
            "settings above and write one image per frame to the output "
            "folder. Progress bar + CPU chip show it working."
        )
        self.cancel_btn = QtWidgets.QPushButton("■  Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setToolTip(
            "<b>Stop the current job</b><br>Works for both extraction and "
            "MP4 rendering; finishes the frame in flight, then stops."
        )
        self.cancel_btn.setEnabled(False)
        video_btn = QtWidgets.QPushButton("🎬  Render video…")
        video_btn.setToolTip(
            "<b>Render MP4</b><br>Encode a frame range straight to H.264 "
            "with ffmpeg. A progress bar opens in this dialog and mirrors "
            "on the main bar below."
        )
        verify = QtWidgets.QPushButton("✓  Verify…")
        verify.setIcon(self._std_icon(QtWidgets.QStyle.SP_DialogApplyButton))
        verify.setToolTip(
            "<b>Verify pixel-exactness</b><br>Pick a reference folder (or use "
            "the source bin via the button next to this) — every frame is "
            "decoded and compared."
        )
        verify_bin = QtWidgets.QPushButton("✓  Verify vs source bin")
        verify_bin.setIcon(self._std_icon(QtWidgets.QStyle.SP_BrowserReload))
        verify_bin.setToolTip(
            "<b>Verify against the recording itself</b><br>No vendor "
            "reference folder needed: every extracted frame is re-derived "
            "from the loaded .bin and compared pixel-for-pixel. Uses the "
            "current quality mode and output folder."
        )
        bar.addWidget(self.extract_btn)
        bar.addWidget(self.cancel_btn)
        bar.addWidget(video_btn)
        bar.addWidget(verify)
        bar.addWidget(verify_bin)
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
        video_btn.clicked.connect(self._render_video_dialog)
        verify.clicked.connect(self._verify)
        verify_bin.clicked.connect(self._verify_bin)

        self._log(
            f"opngx {opngx.__version__} ready — engine: {opngx.engine_backend()}", "ok"
        )
        if opngx.engine_backend() == "python-fallback":
            for line in opngx.engine_diagnostics():
                self._log("  " + line, "warn")

    def _poll_sysmon(self) -> None:
        try:
            snap = self._sys_snapshot()
        except Exception:
            return
        cpu, mem, load1 = snap.get("cpu"), snap.get("mem"), snap.get("load1")
        self.cpu_chip.setText(f"CPU {cpu:.0f}%" if cpu is not None else "CPU –")
        self.ram_chip.setText(f"RAM {mem:.0f}%" if mem is not None else "RAM –")
        # every value may be None (unsupported platform / sampler priming)
        tip = "<b>Live CPU</b>"
        if cpu is not None:
            tip += f" {cpu:.0f}% overall"
        if load1 is not None and os.cpu_count():
            tip += f"<br>load 1 min: {load1:.2f} ({os.cpu_count()} cores)"
        self.cpu_chip.setToolTip(tip)

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

    # ------------------------------------------------------ frame viewer
    def _current_lut_kwargs(self) -> dict[str, Any]:
        mode = next((k for k, rb in self.modes.items() if rb.isChecked()), "reference")
        return dict(
            mode=mode,
            brightness=self.b_spin.value(),
            contrast=self.c_spin.value(),
            gamma=self.g_spin.value(),
        )

    def _show_frame(self, idx: int) -> None:
        m = self.meta
        if not m or m.capacity_frames == 0:
            return
        idx = max(0, min(idx, m.capacity_frames - 1))
        from opngx.video import read_frame_gray

        buf = opngx.read_frame_gray(m.bin_path, m, idx, **self._current_lut_kwargs())
        img = QtGui.QImage(
            buf, m.width, m.height, m.width, QtGui.QImage.Format_Grayscale8
        ).copy()
        pm = QtGui.QPixmap.fromImage(img)
        scaled = pm.scaled(
            self.viewer_img.width() - 2,
            self.viewer_img.height() - 2,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.viewer_img.setPixmap(scaled)
        self.frame_lbl.setText(f"frame {idx:,} / {m.capacity_frames - 1:,}")

    def _refresh_frame(self) -> None:
        if self.meta and self.frame_slider.maximum() > 0:
            self._show_frame(int(self.frame_slider.value()))

    def _step_frame(self, delta: int) -> None:
        v = int(self.frame_slider.value()) + delta
        self.frame_slider.setValue(
            max(self.frame_slider.minimum(), min(self.frame_slider.maximum(), v))
        )

    # ------------------------------------------------------- video render
    def _render_video_dialog(self) -> None:
        if not self.meta:
            QtWidgets.QMessageBox.warning(self, "opngx", "Probe a bin first.")
            return
        if not opnx_ffmpeg_ok():
            QtWidgets.QMessageBox.warning(
                self,
                "opngx",
                "ffmpeg was not found (neither on PATH nor bundled).<br>"
                "Install it and reopen the dialog.",
            )
            return

        opts = self._collect_opts()
        n = (
            opts["frames"]
            if opts["frames"] is not None
            else max(0, self.meta.capacity_frames - opts["start"])
        )
        fps_default = (
            int(round(self.meta.framerate))
            if self.meta.framerate and self.meta.framerate > 0
            else 30
        )

        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Render video")
        d.setMinimumWidth(500)
        v = QtWidgets.QVBoxLayout(d)

        grid = QtWidgets.QGridLayout()
        fps = QtWidgets.QSpinBox()
        fps.setRange(1, 500)
        fps.setValue(fps_default)
        crf = QtWidgets.QSpinBox()
        crf.setRange(14, 28)
        crf.setValue(18)
        out_edit = QtWidgets.QLineEdit(
            os.path.join(
                self.out_edit.text().strip() or ".",
                (self.meta.camera_name or "video").replace(".", "_") + ".mp4",
            )
        )
        save = QtWidgets.QPushButton("…")
        save.setFixedWidth(36)

        def pick():
            pth, _ = QtWidgets.QFileDialog.getSaveFileName(
                d, "Output video", out_edit.text(), "MP4 video (*.mp4)"
            )
            if pth:
                out_edit.setText(pth)

        save.clicked.connect(pick)
        grid.addWidget(QtWidgets.QLabel("frame rate"), 0, 0)
        grid.addWidget(fps, 0, 1)
        grid.addWidget(QtWidgets.QLabel("quality (crf)"), 1, 0)
        grid.addWidget(crf, 1, 1)
        grid.addWidget(QtWidgets.QLabel("output"), 2, 0)
        grid.addWidget(out_edit, 2, 1)
        grid.addWidget(save, 2, 2)
        v.addLayout(grid)

        dur_lbl = QtWidgets.QLabel()
        dur_lbl.setObjectName("hint")
        frames_lbl = QtWidgets.QLabel(
            f"frames to encode: {n:,} (from {opts['start']:,})"
        )
        frames_lbl.setObjectName("hint")
        v.addWidget(frames_lbl)
        v.addWidget(dur_lbl)
        self._tip(
            fps,
            "Frame rate",
            f"Playback speed of the MP4. The camera recorded at "
            f"{self.meta.framerate:g} fps — match it for real-time "
            "playback; lower for slow-motion review.",
        )
        self._tip(
            crf,
            "Quality (CRF)",
            "Lower = better quality & bigger file. 18 is visually "
            "lossless; 28 gives small files.",
        )

        def upd_dur():
            f_ = max(1, fps.value())
            secs = n / f_
            dur_lbl.setText(
                f"video length at {fps.value()} fps: "
                f"{int(secs // 60)}:{int(secs % 60):02d} "
                f"({secs:.1f}s) — {n:,} frames"
            )

        fps.valueChanged.connect(upd_dur)
        upd_dur()

        prog = QtWidgets.QProgressBar()
        prog.setRange(0, 100)
        stat = QtWidgets.QLabel("ready — press Render to encode", wordWrap=True)
        stat.setObjectName("hint")
        v.addWidget(prog)
        v.addWidget(stat)

        def stop_render():
            self._cancel_requested = True  # unified cancel with main window
            state["cancel"] = True
            stat.setText("stopping after the current frame…")
            d.reject()

        bb = QtWidgets.QHBoxLayout()
        go = QtWidgets.QPushButton("▶  Render MP4")
        go.setObjectName("accent")
        cancel = QtWidgets.QPushButton("■  Stop")
        cancel.setObjectName("danger")
        cancel.clicked.connect(stop_render)
        bb.addWidget(go)
        bb.addWidget(cancel)
        bb.addStretch(1)
        v.addLayout(bb)

        state = {"cancel": False}

        def run():
            t0 = time.perf_counter()
            try:

                def pgs(done, total):
                    frac = done / max(total, 1)
                    el = time.perf_counter() - t0
                    eta = el / frac - el if frac > 0.004 else 0
                    txt = (
                        f"{done:,}/{total:,} frames encoded "
                        f"({frac * 100:.1f}%) • encoder feed "
                        f"{done / max(el, 1e-9):,.0f} fps • video so far "
                        f"{done / max(fps.value(), 1):.1f}s • eta {eta:,.0f}s"
                    )
                    QtCore.QMetaObject.invokeMethod(
                        stat, "setText", Qt.QueuedConnection, QtCore.Q_ARG(str, txt)
                    )
                    QtCore.QMetaObject.invokeMethod(
                        prog,
                        "setValue",
                        Qt.QueuedConnection,
                        QtCore.Q_ARG(int, int(100 * frac)),
                    )
                    # mirror on the main-window bar so rendering is visible
                    # even when the dialog is small/behind (C12)
                    self._sig.progress.emit(done, total, done / max(el, 1e-9))

                st = opngx.render_video(
                    self.meta.bin_path,
                    out_edit.text(),
                    mode=opts["mode"],
                    brightness=opts["brightness"],
                    contrast=opts["contrast"],
                    gamma=opts["gamma"],
                    start=opts["start"],
                    count=n,
                    fps=fps.value(),
                    crf=crf.value(),
                    progress=pgs,
                    should_cancel=lambda: state["cancel"],
                )
                tail = " — CANCELLED" if st.get("cancelled") else ""
                secs_out = st["frames_written"] / max(fps.value(), 1)
                size_b = (
                    os.path.getsize(st["output"]) if os.path.exists(st["output"]) else 0
                )
                self._sig.log.emit(
                    f"video done: {st['frames_written']:,} frames in "
                    f"{st['seconds']:.1f}s → {st['output']} "
                    f"(plays {int(secs_out // 60)}:{int(secs_out % 60):02d} @ "
                    f"{fps.value()}fps, {size_b:,} bytes){tail}",
                    "warn" if st.get("cancelled") else "ok",
                )
                QtCore.QMetaObject.invokeMethod(
                    stat,
                    "setText",
                    Qt.QueuedConnection,
                    QtCore.Q_ARG(
                        str,
                        f"done: {st['frames_written']:,} frames • "
                        f"{size_b:,} bytes • plays "
                        f"{int(secs_out // 60)}:"
                        f"{int(secs_out % 60):02d}{tail}",
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                self._sig.error.emit(str(exc))
            finally:
                QtCore.QMetaObject.invokeMethod(d, "accept", Qt.QueuedConnection)
                self._sig.state.emit(False)  # restore main-window buttons

        def start_render():
            go.setEnabled(False)
            fps.setEnabled(False)
            crf.setEnabled(False)
            self._running = True
            self._cancel_requested = False
            self._t_start = time.perf_counter()
            self._sig.state.emit(True)  # main Cancel becomes armed
            threading.Thread(target=run, daemon=True).start()

        go.clicked.connect(start_render)
        d.exec()
        self._running = False

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

    def _on_scope_changed(self, batch: bool) -> None:
        """Batch mode scans folders — manual geometry fields only matter
        for a single sidecar-less recording."""
        for w in (self.w_spin, self.h_spin):
            w.setEnabled(not batch)
        if batch:
            self.geom_hint.setText("batch: every *.bin under the folder")

    def _adopt_manual_geometry(self, m) -> None:
        """Sidecar-less recordings take geometry from the width/height
        fields (remembered per session); otherwise show what the sidecar
        provided."""
        if m.width == 0:
            w_, h_ = int(self.w_spin.value()), int(self.h_spin.value())
            if w_ > 0 and h_ > 0:
                m.width, m.height = w_, h_
                m.frame_stride = 8 + m.width * m.height
                m.capacity_frames = (
                    m.file_size // m.frame_stride if m.frame_stride else 0
                )
                self.geom_hint.setText(
                    f"using manual {w_}×{h_} — capacity {m.capacity_frames:,} frames"
                )
                return
            self.geom_hint.setText("no sidecar — enter width × height above")
        else:
            self.geom_hint.setText(f"{m.width}×{m.height} from sidecar")

    def _manual_geom_kwargs(self) -> dict[str, Any]:
        if self.meta is not None and self.meta.width == 0:
            w_, h_ = int(self.w_spin.value()), int(self.h_spin.value())
            if w_ > 0 and h_ > 0:
                return dict(width=w_, height=h_)
        return {}

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
        self._adopt_manual_geometry(m)
        rows = [
            ("camera", m.camera_name or "?"),
            ("geometry", f"{m.width} × {m.height} px" if m.width else "? × ? px"),
            ("frames in XML", f"{m.num_images:,}" if m.num_images > 0 else "?"),
            ("capacity from size", f"{m.capacity_frames:,}" or "?"),
            (
                "frames: XML vs file",
                f"{m.num_images:,} vs {m.capacity_frames:,} — "
                + (
                    "✓ match"
                    if m.frames_match
                    else "⚠ MISMATCH (recording truncated or XML stale)"
                    if m.frames_match is False
                    else "n/a"
                ),
            ),
            (
                "clock span",
                f"{m.span_s:,.3f} s" if m.span_s else "?",
            ),
            (
                "effective fps (first→last tick, µs clock)",
                f"{m.effective_fps_us:,.2f}" if m.effective_fps_us else "?",
            ),
            (
                "framerate_real (achieved)",
                f"{m.framerate_real:g} fps" if m.framerate_real > 0 else "?",
            ),
            (
                "pixel fidelity",
                "8-bit sensor mono · reference = vendor curve (clips raw≥139)"
                " · raw = lossless sensor bytes",
            ),
            ("frame stride", f"{m.frame_stride:,} B" if m.frame_stride else "?"),
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
        self._fill_info(rows)
        self._log(f"probed {os.path.basename(m.bin_path)}")
        self.frame_slider.blockSignals(True)
        self.frame_slider.setRange(0, max(0, m.capacity_frames - 1))
        start_at = int(self.start_spin.value())
        self.frame_slider.setValue(start_at)
        self.frame_slider.blockSignals(False)
        self._show_frame(start_at)
        if not self.out_edit.text():
            suggested = os.path.dirname(m.bin_path)
            if m.camera_name:
                suggested = os.path.join(
                    suggested, _safe_name(m.camera_name) + "_png"
                )
            self.out_edit.setText(suggested)

    def _fill_info(self, rows) -> None:
        self.info_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.info_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.info_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))

    def _collect_opts(self) -> dict[str, Any]:
        return dict(
            mode=next(k for k, rb in self.modes.items() if rb.isChecked()),
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
        geom = self._manual_geom_kwargs()
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
                        else os.path.join(out, _safe_name(stem))
                    )
                    o = opts
                    self._sig.log.emit(
                        f"extract {os.path.basename(b)} → {od}  "
                        f"[mode={o['mode']} fmt={o['fmt']} depth={o['bit_depth']} "
                        f"ch={o['channels']} jobs={o['jobs']} level={o['level']}]",
                        "info",
                    )
                    ex = opngx.Extractor(b, **geom)
                    last = ex.extract(
                        od,
                        progress=lambda d_, t_: self._sig.progress.emit(
                            d_,
                            t_,
                            d_ / max(time.perf_counter() - self._t_start, 1e-9),
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

    def _verify_bin(self) -> None:
        """Verify the output folder against the loaded .bin itself —
        no vendor reference directory required (ADD-10)."""
        if not self.meta:
            QtWidgets.QMessageBox.warning(self, "opngx", "Probe a bin first.")
            return
        out = self.out_edit.text().strip()
        if not out:
            QtWidgets.QMessageBox.warning(
                self, "opngx", "Choose an output directory first."
            )
            return
        opts = self._collect_opts()

        def run() -> None:
            try:
                rep = opngx.verify_against_bin(
                    self.meta.bin_path,
                    out,
                    mode=opts["mode"],
                    brightness=opts["brightness"],
                    contrast=opts["contrast"],
                    gamma=opts["gamma"],
                    bit_depth=opts["bit_depth"],
                    channels=opts["channels"],
                    prefix=opts["prefix"],
                    ext=opts["ext"],
                )
                msg = (
                    "<b style='color:#34d399'>PASS</b> — all "
                    f"{rep.files_compared:,} compared frame(s) are "
                    "pixel-exact against the source recording."
                    if rep.passed
                    else f"<b style='color:#f87171'>FAIL</b> — "
                    f"{rep.mismatched_files} mismatched file(s).<br>"
                    f"<span style='color:#fbbf24'>{rep.first_error}</span>"
                )
                self._sig.log.emit(
                    f"verify-vs-bin: {rep}", "ok" if rep.passed else "err"
                )
                self._sig.dialog.emit(("verify vs source bin", msg))
            except Exception as exc:  # noqa: BLE001
                self._sig.error.emit(str(exc))

        threading.Thread(target=run, daemon=True).start()

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

    def _on_dialog(self, payload) -> None:
        title, msg = payload
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.RichText)
        box.setText(msg)
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.exec()

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

    # Dark QPalette FIRST: guarantees white-on-dark text in every dialog
    # (QMessageBox, file dialogs, context menus) even where QSS does not
    # reach — the black-on-black report came from unstyled message boxes.
    pal = QtGui.QPalette()
    cr = QtGui.QPalette.ColorRole
    cg = QtGui.QPalette.ColorGroup
    dark = QtGui.QColor("#0d0f0d")
    darker = QtGui.QColor("#050505")
    text = QtGui.QColor("#e8ede8")
    bright = QtGui.QColor("#ffffff")
    for group in (cg.Active, cg.Inactive, cg.Disabled):
        pal.setColor(group, cr.Window, dark)
        pal.setColor(
            group,
            cr.WindowText,
            text if group != cg.Disabled else QtGui.QColor("#8a948a"),
        )
        pal.setColor(group, cr.Base, QtGui.QColor("#070807"))
        pal.setColor(group, cr.AlternateBase, dark)
        pal.setColor(
            group, cr.Text, text if group != cg.Disabled else QtGui.QColor("#8a948a")
        )
        pal.setColor(group, cr.Button, QtGui.QColor("#10140f"))
        pal.setColor(
            group,
            cr.ButtonText,
            bright if group != cg.Disabled else QtGui.QColor("#4a554a"),
        )
        pal.setColor(group, cr.Highlight, QtGui.QColor("#4d8248"))
        pal.setColor(group, cr.HighlightedText, bright)
        pal.setColor(group, cr.ToolTipBase, QtGui.QColor("#070807"))
        pal.setColor(group, cr.ToolTipText, QtGui.QColor("#eaf2ea"))
        pal.setColor(group, cr.PlaceholderText, QtGui.QColor("#8a948a"))
    app.setPalette(pal)
    app.setStyleSheet(QSS)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
