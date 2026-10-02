"""The opngx logo (v2.1): one geometry for the SVG/PNG/ICO assets and the
animated logo inside the studio.

The mark: a dark rounded tile, a six-blade green camera iris (high-speed
capture) and, in its opening, a bright particle on a dotted orbit with a
fading trail (motion tracking). `geometry(t)` returns the drawing for an
animation phase t in [0, 1); t = 0 is the static logo.
"""

from __future__ import annotations

import math
from typing import Optional

ACCENT = "#6fbf5f"
ACCENT_DARK = "#2f6b33"
ACCENT_MID = "#4d9a4a"
ACCENT_LIGHT = "#a6e08f"
TILE_TOP = "#121a12"
TILE_BOTTOM = "#050705"
TILE_EDGE = "#24331f"
OPENING = "#050805"
PARTICLE = "#ffffff"
TRAIL = "#d8ffcb"

BLADES = 6


def _polar(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def geometry(t: float = 0.0, size: float = 1024.0) -> dict:
    """Shapes for phase t (0 = static logo) on a size x size canvas.

    Returns {"tile": (x, y, w, h, radius), "ring": (cx, cy, r, width),
    "blades": [[(x, y) * 4], ...] with "blade_shade" per blade,
    "opening": radius, "orbit": (cx, cy, r), "particle": (x, y, r),
    "trail": [(x, y, r, alpha), ...]}."""
    s = size / 1024.0
    c = 512 * s
    rot = -18 + 360.0 / BLADES * t           # one blade-step per cycle: seamless loop
    breathe = 0.5 - 0.5 * math.cos(2 * math.pi * t)
    r_open = (150 + 22 * breathe) * s          # aperture opening
    r_out = 318 * s
    twist = 38
    inner = [_polar(c, c, r_open, 360.0 / BLADES * k + rot) for k in range(BLADES)]
    outer = [_polar(c, c, r_out, 360.0 / BLADES * k + rot + twist) for k in range(BLADES)]
    blades = [[inner[k], inner[(k + 1) % BLADES], outer[(k + 1) % BLADES], outer[k]] for k in range(BLADES)]
    shades = [ACCENT_MID if k % 2 == 0 else ACCENT_DARK for k in range(BLADES)]
    small = size <= 40  # favicon / title-bar sizes: fewer, bigger shapes
    orbit_r = r_open * (0.0 if small else 0.62)
    ang = -60 + 360.0 * t
    px, py = _polar(c, c, orbit_r, ang)
    trail = []
    if not small:
        for i in range(1, 6):
            tx, ty = _polar(c, c, orbit_r, ang - 13 * i)
            trail.append((tx, ty, (30 - 4 * i) * s, max(0.08, 0.55 - 0.1 * i)))
    return {
        "tile": (14 * s, 14 * s, 996 * s, 996 * s, 230 * s),
        "ring": (c, c, 352 * s, 20 * s),
        "blades": blades,
        "blade_shade": shades,
        "opening": r_open,
        "center": (c, c),
        "orbit": (c, c, orbit_r),
        "particle": (px, py, (70 if small else 34) * s),
        "trail": trail,
        "small": small,
    }


def svg(t: float = 0.0, size: int = 1024, tile: bool = True) -> str:
    g = geometry(t, size)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
           f'role="img" aria-label="opngx logo">',
           "<title>opngx</title>",
           "<defs>",
           f'<linearGradient id="tile" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{TILE_TOP}"/>'
           f'<stop offset="1" stop-color="{TILE_BOTTOM}"/></linearGradient>',
           f'<linearGradient id="ring" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{ACCENT_LIGHT}"/>'
           f'<stop offset="1" stop-color="{ACCENT_DARK}"/></linearGradient>',
           f'<radialGradient id="glow"><stop offset="0" stop-color="{ACCENT_LIGHT}" stop-opacity="0.55"/>'
           f'<stop offset="1" stop-color="{ACCENT_LIGHT}" stop-opacity="0"/></radialGradient>',
           "</defs>"]
    if tile:
        x, y, w, h, r = g["tile"]
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r:.1f}" '
                   f'fill="url(#tile)" stroke="{TILE_EDGE}" stroke-width="{size / 1024 * 10:.1f}"/>')
    cx, cy, rr, rw = g["ring"]
    out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr:.1f}" fill="none" stroke="url(#ring)" stroke-width="{rw:.1f}"/>')
    for poly, shade in zip(g["blades"], g["blade_shade"]):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in poly)
        out.append(f'<polygon points="{pts}" fill="{shade}" stroke="{OPENING}" '
                   f'stroke-width="{size / 1024 * 6:.1f}" stroke-linejoin="round"/>')
    ox, oy = g["center"]
    out.append(f'<circle cx="{ox:.1f}" cy="{oy:.1f}" r="{g["opening"] * 0.93:.1f}" fill="{OPENING}"/>')
    ocx, ocy, orr = g["orbit"]
    if not g["small"]:
        out.append(f'<circle cx="{ocx:.1f}" cy="{ocy:.1f}" r="{orr:.1f}" fill="none" stroke="{ACCENT}" '
               f'stroke-opacity="0.55" stroke-width="{size / 1024 * 5:.1f}" stroke-dasharray="{size / 1024 * 6:.1f} {size / 1024 * 14:.1f}"/>')
    for tx, ty, tr, ta in g["trail"]:
        out.append(f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="{tr:.1f}" fill="{TRAIL}" fill-opacity="{ta:.2f}"/>')
    px, py, pr = g["particle"]
    out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{pr * 2.2:.1f}" fill="url(#glow)"/>')
    out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{pr:.1f}" fill="{PARTICLE}"/>')
    out.append("</svg>")
    return "\n".join(out)


def wordmark_svg(dark: bool = True) -> str:
    """Logo + "opngx" (with "gx" in the accent) + tagline, 1200 x 360."""
    mark = svg(0.0, 300).split("\n", 1)[1].rsplit("</svg>", 1)[0]
    text = "#eef4ec" if dark else "#0d140c"
    sub = "#8fa98a" if dark else "#4a5d47"
    bg = '<rect width="1200" height="360" rx="40" fill="#070a07"/>' if dark else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="360" viewBox="0 0 1200 360" '
            f'role="img" aria-label="opngx">{bg}<g transform="translate(30 30)">{mark}</g>'
            f'<text x="370" y="205" font-family="Segoe UI, Inter, Helvetica Neue, Arial, sans-serif" '
            f'font-size="170" font-weight="700" letter-spacing="-4" fill="{text}">opn<tspan fill="{ACCENT}">gx</tspan></text>'
            f'<text x="376" y="275" font-family="Segoe UI, Inter, Helvetica Neue, Arial, sans-serif" '
            f'font-size="40" fill="{sub}">high-speed footage · pixel-exact · analysis</text></svg>')


# ---------------------------------------------------------------------------
# Qt: painter, animated widget, splash screen
# ---------------------------------------------------------------------------
def paint(p, rect, t: float = 0.0, tile: bool = True) -> None:
    """Draw the logo with QPainter into `rect` (QRectF) at phase t."""
    from PySide6 import QtCore, QtGui

    side = min(rect.width(), rect.height())
    g = geometry(t, side)
    p.save()
    p.translate(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    C = QtGui.QColor
    if tile:
        x, y, w, h, r = g["tile"]
        grad = QtGui.QLinearGradient(0, y, 0, y + h)
        grad.setColorAt(0, C(TILE_TOP))
        grad.setColorAt(1, C(TILE_BOTTOM))
        p.setPen(QtGui.QPen(C(TILE_EDGE), side / 1024 * 10))
        p.setBrush(grad)
        p.drawRoundedRect(QtCore.QRectF(x, y, w, h), r, r)
    cx, cy, rr, rw = g["ring"]
    rg = QtGui.QLinearGradient(cx - rr, cy - rr, cx + rr, cy + rr)
    rg.setColorAt(0, C(ACCENT_LIGHT))
    rg.setColorAt(1, C(ACCENT_DARK))
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QBrush(rg), rw))
    p.drawEllipse(QtCore.QPointF(cx, cy), rr, rr)
    for poly, shade in zip(g["blades"], g["blade_shade"]):
        p.setPen(QtGui.QPen(C(OPENING), side / 1024 * 6, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        p.setBrush(C(shade))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in poly]))
    ox, oy = g["center"]
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(C(OPENING))
    p.drawEllipse(QtCore.QPointF(ox, oy), g["opening"] * 0.93, g["opening"] * 0.93)
    ocx, ocy, orr = g["orbit"]
    if not g["small"]:
        pen = QtGui.QPen(C(ACCENT), side / 1024 * 5)
        pen.setDashPattern([1.2, 2.8])
        oc = C(ACCENT)
        oc.setAlphaF(0.55)
        pen.setColor(oc)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(QtCore.QPointF(ocx, ocy), orr, orr)
    p.setPen(QtCore.Qt.NoPen)
    for tx, ty, tr, ta in g["trail"]:
        tc = C(TRAIL)
        tc.setAlphaF(ta)
        p.setBrush(tc)
        p.drawEllipse(QtCore.QPointF(tx, ty), tr, tr)
    px_, py_, pr = g["particle"]
    glow = QtGui.QRadialGradient(px_, py_, pr * 2.2)
    gc = C(ACCENT_LIGHT)
    gc.setAlphaF(0.55)
    glow.setColorAt(0, gc)
    gc2 = C(ACCENT_LIGHT)
    gc2.setAlphaF(0.0)
    glow.setColorAt(1, gc2)
    p.setBrush(glow)
    p.drawEllipse(QtCore.QPointF(px_, py_), pr * 2.2, pr * 2.2)
    p.setBrush(C(PARTICLE))
    p.drawEllipse(QtCore.QPointF(px_, py_), pr, pr)
    p.restore()


def qicon():
    """The application icon (window, taskbar) drawn at every size Windows
    asks for - no file lookup, so it can't go missing in the frozen exe."""
    from PySide6 import QtCore, QtGui

    ic = QtGui.QIcon()
    for s in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
        pm = QtGui.QPixmap(s, s)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        paint(p, QtCore.QRectF(0, 0, s, s))
        p.end()
        ic.addPixmap(pm)
    return ic


def _widgets():
    from PySide6 import QtCore, QtGui, QtWidgets

    class LogoMark(QtWidgets.QWidget):
        """The logo, optionally animated: the iris turns and breathes while
        the particle runs its orbit (one cycle per `period_ms`)."""

        def __init__(self, size: int = 64, animated: bool = True, period_ms: int = 4200, parent=None):
            super().__init__(parent)
            self._t = 0.0
            self._period = max(500, int(period_ms))
            self.setFixedSize(size, size)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(33)
            self._timer.timeout.connect(self._tick)
            self._clock = QtCore.QElapsedTimer()
            self.set_animated(animated)

        def set_animated(self, on: bool) -> None:
            if on:
                self._clock.start()
                self._timer.start()
            else:
                self._timer.stop()
                self._t = 0.0
                self.update()

        def is_animated(self) -> bool:
            return self._timer.isActive()

        def _tick(self) -> None:
            self._t = (self._clock.elapsed() % self._period) / self._period
            self.update()

        def paintEvent(self, _e):  # noqa: N802
            p = QtGui.QPainter(self)
            paint(p, QtCore.QRectF(self.rect()), self._t)
            p.end()

    class Splash(QtWidgets.QWidget):
        """Start-up splash: the animated logo, the name, the version and a
        status line, shown while the main window is being built."""

        def __init__(self, version: str):
            super().__init__(None, QtCore.Qt.SplashScreen | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
            lay = QtWidgets.QVBoxLayout(self)
            card = QtWidgets.QFrame()
            card.setStyleSheet(f"QFrame{{background:#070a07;border:1px solid {TILE_EDGE};border-radius:18px;}}"
                               "QLabel{border:none;background:transparent;}")
            lay.addWidget(card)
            v = QtWidgets.QVBoxLayout(card)
            v.setContentsMargins(36, 30, 36, 24)
            v.setSpacing(8)
            self.mark = LogoMark(132, animated=True, period_ms=2600)
            v.addWidget(self.mark, 0, QtCore.Qt.AlignHCenter)
            name = QtWidgets.QLabel(f'<span style="color:#eef4ec">opn</span><span style="color:{ACCENT}">gx</span>'
                                    '<span style="color:#8fa98a;font-weight:400"> studio</span>')
            f = name.font()
            f.setPointSizeF(f.pointSizeF() * 2.1)
            f.setBold(True)
            name.setFont(f)
            v.addWidget(name, 0, QtCore.Qt.AlignHCenter)
            ver = QtWidgets.QLabel(f'<span style="color:#8fa98a">version {version} · pixel-exact · all cores</span>')
            v.addWidget(ver, 0, QtCore.Qt.AlignHCenter)
            self.status = QtWidgets.QLabel('<span style="color:#6f8a6a">starting…</span>')
            v.addWidget(self.status, 0, QtCore.Qt.AlignHCenter)

        def message(self, text: str) -> None:
            self.status.setText(f'<span style="color:#6f8a6a">{text}</span>')
            QtWidgets.QApplication.processEvents()

        def show_centered(self) -> None:
            self.adjustSize()
            scr = QtWidgets.QApplication.primaryScreen()
            if scr is not None:
                g = scr.availableGeometry()
                self.move(g.center() - self.rect().center())
            self.show()
            QtWidgets.QApplication.processEvents()

    return LogoMark, Splash


_W = None


def LogoMark(*a, **k):  # noqa: N802 - factory with the class name
    global _W
    if _W is None:
        _W = _widgets()
    return _W[0](*a, **k)


def Splash(*a, **k):  # noqa: N802
    global _W
    if _W is None:
        _W = _widgets()
    return _W[1](*a, **k)


def write_assets(out_dir: str, package_dir: Optional[str] = None) -> list[str]:
    """Write the SVG masters, PNG sizes and the Windows .ico."""
    import os

    os.makedirs(out_dir, exist_ok=True)
    written = []

    def w(name, text):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        written.append(p)

    w("icon.svg", svg())
    w("logo-dark.svg", svg())
    w("wordmark.svg", wordmark_svg(dark=False))
    w("wordmark-dark.svg", wordmark_svg(dark=True))
    w("logo-light.svg", wordmark_svg(dark=False))
    # rasters through Qt (no rsvg dependency)
    from PySide6 import QtCore, QtGui, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    _ = app
    pngs = {}
    for s in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        img = QtGui.QImage(s, s, QtGui.QImage.Format_ARGB32)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        paint(p, QtCore.QRectF(0, 0, s, s))
        p.end()
        path = os.path.join(out_dir, f"icon-{s}.png")
        img.save(path)
        pngs[s] = path
        written.append(path)
    import shutil

    shutil.copyfile(pngs[256], os.path.join(out_dir, "icon.png"))
    written.append(os.path.join(out_dir, "icon.png"))
    from PIL import Image

    ico = os.path.join(out_dir, "icon.ico")
    big = Image.open(pngs[256])
    big.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    written.append(ico)
    shutil.copyfile(ico, os.path.join(out_dir, "app.ico"))
    if package_dir:
        os.makedirs(package_dir, exist_ok=True)
        for name in ("icon.svg", "icon-256.png", "wordmark-dark.svg"):
            shutil.copyfile(os.path.join(out_dir, name), os.path.join(package_dir, name))
            written.append(os.path.join(package_dir, name))
    return written
