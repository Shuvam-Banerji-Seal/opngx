"""Start tab (v2.1): what opngx does, the three steps of a session, which
output to choose, recent recordings and shortcuts."""

from __future__ import annotations

import os

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt

import opngx
from opngx import formats
from opngx.ui import icons as _icons

RECENT_KEY = "recent/recordings"


def remember_recent(path: str) -> None:
    qs = QtCore.QSettings("opngx", "opngx-studio")
    cur = [p for p in (qs.value(RECENT_KEY) or []) if isinstance(p, str)]
    path = os.path.abspath(path)
    cur = [path] + [p for p in cur if os.path.abspath(p) != path]
    qs.setValue(RECENT_KEY, cur[:10])


def recent() -> list[str]:
    qs = QtCore.QSettings("opngx", "opngx-studio")
    return [p for p in (qs.value(RECENT_KEY) or []) if isinstance(p, str) and os.path.exists(p)]


class HomeView(QtWidgets.QScrollArea):
    def __init__(self, studio, parent=None) -> None:
        super().__init__(parent)
        self.studio = studio
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget()
        self.setWidget(body)
        sc = studio._scaling
        v = QtWidgets.QVBoxLayout(body)
        v.setContentsMargins(sc.px(4), sc.px(6), sc.px(4), sc.px(6))
        v.setSpacing(sc.px(12))

        # ---- hero -----------------------------------------------------
        hero, hv = studio._card("welcome")
        top = QtWidgets.QHBoxLayout()
        from opngx.ui.logo import LogoMark

        self.mark = LogoMark(sc.px(96), animated=True, period_ms=5200)
        top.addWidget(self.mark, 0, Qt.AlignTop)
        intro = QtWidgets.QLabel(
            f"<h2 style='margin:0'>opngx studio {opngx.__version__}</h2>"
            "<p>Turns Optronis high-speed-camera recordings (<code>.bin</code> + <code>.footage</code>) into "
            "images and videos <b>pixel-identical to TimeViewer's exports</b>, using every CPU core, and "
            "measures what happens in them: sub-pixel motion tracking, Brownian motion and optical-trap "
            "stiffness, focus, drift, particles, brightness, flicker - or your own Python modules.</p>"
            "<p>Nothing is uploaded anywhere: everything runs on this computer.</p>")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        top.addWidget(intro, 1)
        hv.addLayout(top)
        v.addWidget(hero)

        # ---- three steps ---------------------------------------------
        steps = QtWidgets.QHBoxLayout()
        steps.setSpacing(sc.px(12))
        for n, (icon, title, text, button, fn) in enumerate((
            ("folder-open", "Open a recording",
             "Pick the <code>.bin</code> file (its <code>.footage</code> sidecar is found automatically), "
             "or a folder of recordings for a batch. The first frame appears at once.",
             "Open recording…", self._open),
            ("sliders", "Choose what to make",
             "<b>Extract</b>: one image per frame. <b>Video</b>: one movie file, lossy or bit-exact. "
             "Crop and the brightness/contrast curve apply to both.",
             "Go to Extract", lambda: self._goto("extract")),
            ("chart", "Measure",
             "<b>Analyze</b> runs modules over the frames and writes CSV/JSON/NPZ/TSV tables you can "
             "plot here or open in Excel, Origin, MATLAB or Python.",
             "Go to Analyze", lambda: self._goto("analyze")),
        ), start=1):
            card, cv = studio._card(f"step {n}")
            head = QtWidgets.QHBoxLayout()
            ic = QtWidgets.QLabel()
            ic.setPixmap(_icons.icon(icon, "accent_fg").pixmap(sc.px(28), sc.px(28)))
            head.addWidget(ic)
            t = QtWidgets.QLabel(f"<b>{title}</b>")
            head.addWidget(t, 1)
            cv.addLayout(head)
            body_l = QtWidgets.QLabel(text)
            body_l.setWordWrap(True)
            body_l.setTextFormat(Qt.RichText)
            cv.addWidget(body_l, 1)
            b = QtWidgets.QPushButton(button)
            _icons.set_icon(b, icon, "text")
            b.clicked.connect(fn)
            cv.addWidget(b)
            steps.addWidget(card, 1)
        v.addLayout(steps)

        # ---- which output ---------------------------------------------
        mid = QtWidgets.QHBoxLayout()
        mid.setSpacing(sc.px(12))
        fc, fv = studio._card("which output should I use?")
        tbl = QtWidgets.QTableWidget(len(formats.FORMATS), 3)
        tbl.setHorizontalHeaderLabels(["format", "pixels", "what for"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        tbl.setWordWrap(True)
        tbl.horizontalHeader().setStretchLastSection(True)
        for i, f in enumerate(formats.FORMATS.values()):
            bits = " / ".join(f"{b}-bit" for b in f.bit_depths)
            for j, txt in enumerate((f"{f.label}  ({bits})", "exact" if f.lossless else "lossy", f.summary)):
                it = QtWidgets.QTableWidgetItem(txt)
                it.setToolTip(f"{f.summary}\nOpens in: {f.opens_in}")
                tbl.setItem(i, j, it)
        tbl.resizeColumnsToContents()
        tbl.resizeRowsToContents()
        tbl.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        h = tbl.horizontalHeader().height() + sum(tbl.rowHeight(i) for i in range(tbl.rowCount())) + 6
        tbl.setMinimumHeight(h)  # every format visible, no inner scrollbar
        fv.addWidget(tbl)
        note = QtWidgets.QLabel(
            "For measurements use a lossless format. For one file per recording use the NumPy stack "
            "(images) or FFV1 (video): both are bit-exact. The System tab can verify every format on "
            "your own recording.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        fv.addWidget(note)
        mid.addWidget(fc, 3)

        rc, rv = studio._card("recent recordings")
        self.recent_list = QtWidgets.QListWidget()
        self.recent_list.itemActivated.connect(self._open_recent)
        self.recent_list.itemDoubleClicked.connect(self._open_recent)
        rv.addWidget(self.recent_list, 1)
        tips = QtWidgets.QLabel(
            "<b>Shortcuts</b><br>Ctrl+O open · Ctrl+E extract · Esc cancel · Ctrl+1…7 tabs<br>"
            "Mouse wheel zooms the frame, right-drag pans.")
        tips.setWordWrap(True)
        tips.setObjectName("hint")
        rv.addWidget(tips)
        mid.addWidget(rc, 2)
        v.addLayout(mid)
        v.addStretch(1)
        self.refresh_recent()

    def refresh_recent(self) -> None:
        self.recent_list.clear()
        items = recent()
        for p in items:
            it = QtWidgets.QListWidgetItem(_icons.icon("film"), os.path.basename(p))
            it.setToolTip(p)
            it.setData(Qt.UserRole, p)
            self.recent_list.addItem(it)
        if not items:
            it = QtWidgets.QListWidgetItem("recordings you open appear here")
            it.setFlags(Qt.NoItemFlags)
            self.recent_list.addItem(it)

    def _open(self) -> None:
        self._goto("extract")
        if hasattr(self.studio, "_pick_source"):
            self.studio._pick_source()

    def _open_recent(self, item) -> None:
        p = item.data(Qt.UserRole)
        if not p:
            return
        st = self.studio
        if hasattr(st, "rb_single"):
            st.rb_single.setChecked(True)
        st.bin_edit.setText(p)
        st._probe()
        self._goto("extract")

    def _goto(self, name: str) -> None:
        if hasattr(self.studio, "goto_tab"):
            self.studio.goto_tab(name)
