"""Vector icons for the studio (v2.1).

Every icon is a small 24x24 stroke drawing written for opngx (no third-party
icon set, so no licence to track). Icons are rendered from SVG at the
screen's device-pixel ratio, so they stay sharp from 720p to 4K and at any
Windows scaling, and they take the colour of the active theme: switching
theme re-colours every icon already on screen.

    from opngx.ui import icons
    icons.set_icon(button, "play")                # theme text colour
    icons.set_icon(button, "play", role="accent")  # accent colour
    icons.icon("folder")                           # a QIcon
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

# stroke paths (the <path>/<circle>/... body of each icon; viewBox 0 0 24 24)
_BODY: dict[str, str] = {
    "play": '<path d="M7 4.5v15l12.5-7.5z" fill="C" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="C" stroke="none"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "folder-open": '<path d="M3 17V7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V11"/><path d="M3 17l2.6-6.2A1.5 1.5 0 0 1 7 10h13.2a1 1 0 0 1 .9 1.4L18.4 18a1.6 1.6 0 0 1-1.5 1H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.6 2.6 0 0 1 5 .9c0 1.8-2.5 2.2-2.5 3.9M12 17v.4"/>',
    "warning": '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2v.3"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "shield": '<path d="M12 3l7 3v5.5c0 4.4-3 8-7 9.5-4-1.5-7-5.1-7-9.5V6z"/><path d="M8.8 12.2l2.3 2.3 4.3-4.6"/>',
    "crop": '<path d="M6 2.5V18h15.5"/><path d="M2.5 6H18v15.5"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 8.5h4M3 15.5h4M17 8.5h4M17 15.5h4"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9.5" r="1.8"/><path d="M21 16l-5-5-9.5 9"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5.5-7"/>',
    "target": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1" fill="C"/>',
    "code": '<path d="M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5M13.5 4.5l-3 15"/>',
    "book": '<path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H20v15H5.5A1.5 1.5 0 0 0 4 19.5z"/><path d="M4 19.5A1.5 1.5 0 0 0 5.5 21H20v-3"/><path d="M8 7.5h8"/>',
    "sliders": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="1.5"/><rect x="9.5" y="9.5" width="5" height="5"/><path d="M9 2.5v3.5M15 2.5v3.5M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    "gauge": '<path d="M4.2 17a9 9 0 1 1 15.6 0"/><path d="M12 13.5 16 8.5"/><circle cx="12" cy="13.5" r="1.4" fill="C"/>',
    "layers": '<path d="M12 3 2.5 8 12 13l9.5-5z"/><path d="M2.5 12.5 12 17.5l9.5-5M2.5 16.5 12 21.5l9.5-5"/>',
    "download": '<path d="M12 3.5v12M7 10.5l5 5 5-5M4 20h16"/>',
    "upload": '<path d="M12 20V8M7 13l5-5 5 5M4 4h16"/>',
    "save": '<path d="M5 3h11l4 4v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a1 1 0 0 1 1-1z"/><path d="M8 3v5h7V3M7.5 21v-6h9v6"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8"/><path d="M4 3.5V8h4.5M4 13a8 8 0 0 0 14.6 4.5L20 16"/><path d="M20 20.5V16h-4.5"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "trash": '<path d="M4 6.5h16M9.5 6.5V4h5v2.5M6 6.5l1 13.5h10l1-13.5M10 10.5v6M14 10.5v6"/>',
    "copy": '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V5a1.5 1.5 0 0 0-1.5-1.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h3.5"/>',
    "zoom-in": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5M10.5 7.5v6M7.5 10.5h6"/>',
    "zoom-out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5M7.5 10.5h6"/>',
    "fit": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "home": '<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.5V20h5v-6h3v6h5V9.5"/>',
    "palette": '<path d="M12 3a9 9 0 0 0 0 18c1.3 0 2-.8 2-1.8 0-1.4-1.2-1.6-1.2-2.8 0-1 .8-1.6 1.8-1.6H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3z"/><circle cx="7.5" cy="11" r="1.1" fill="C"/><circle cx="10" cy="7" r="1.1" fill="C"/><circle cx="15" cy="7.5" r="1.1" fill="C"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3.5 3L7 15M12.5 15.5H17"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1" fill="C"/><circle cx="4.5" cy="12" r="1" fill="C"/><circle cx="4.5" cy="18" r="1" fill="C"/>',
    "sparkle": '<path d="M12 3.5l1.8 4.9 4.9 1.8-4.9 1.8L12 16.9l-1.8-4.9-4.9-1.8 4.9-1.8z"/><path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    "aperture": '<circle cx="12" cy="12" r="9"/><path d="M12 3l4.4 7.6M21 12h-8.8M16.5 19.8 12 12.2M7.5 19.8l4.4-7.6M3 12h8.8M7.6 4.2 12 11.8"/>',
    "track": '<circle cx="17" cy="7" r="2.6"/><path d="M3.5 19.5c3-1 4-4.5 6.5-6.5s4-2.5 5-3.8" stroke-dasharray="2.2 2.4"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.5M9.5 10h.5M13 10h.5M16.5 10h1M6 14h1M8 14h8M18 14h.5"/>',
    "chev-left": '<path d="M15 5l-7 7 7 7"/>',
    "chev-right": '<path d="M9 5l7 7-7 7"/>',
    "chev-up": '<path d="M5 15l7-7 7 7"/>',
    "chev-down": '<path d="M5 9l7 7 7-7"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "play-all": '<path d="M4 5v14l8-7zM12.5 5v14l8-7z" fill="C" stroke="none"/>',
    "scale": '<path d="M3 3h7v7H3zM14 14h7v7h-7z"/><path d="M10 6.5h7.5V14"/>',
}


def _svg(name: str, color: str) -> bytes:
    body = _BODY[name].replace('fill="C"', f'fill="{color}"')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    ).encode()


def names() -> list[str]:
    return sorted(_BODY)


def _role_color(role: str) -> str:
    try:
        from opngx.ui import themes

        return themes.qcolor(role).name()
    except Exception:  # noqa: BLE001 - themes not loaded yet (tests, early start)
        return {"accent": "#6fbf5f", "danger": "#e5534b"}.get(role, "#e6e6e6")


_RENDERER = None


def _render(data: bytes, px: int) -> QtGui.QPixmap:
    global _RENDERER
    if _RENDERER is None:
        try:
            from PySide6 import QtSvg  # noqa: F401

            _RENDERER = "svg"
        except Exception:  # noqa: BLE001
            _RENDERER = "plugin"
    pm = QtGui.QPixmap(px, px)
    pm.fill(QtCore.Qt.transparent)
    if _RENDERER == "svg":
        from PySide6.QtSvg import QSvgRenderer

        r = QSvgRenderer(QtCore.QByteArray(data))
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r.render(p, QtCore.QRectF(0, 0, px, px))
        p.end()
    else:  # the qsvg image-format plugin (no QtSvg module): still vector
        img = QtGui.QImage.fromData(data, "SVG")
        if not img.isNull():
            p = QtGui.QPainter(pm)
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            p.drawImage(QtCore.QRectF(0, 0, px, px), img)
            p.end()
    return pm


_CACHE: dict = {}


def icon(name: str, role: str = "text", color: Optional[str] = None) -> QtGui.QIcon:
    """A multi-resolution QIcon for `name` in a theme role's colour (or an
    explicit `color`). Unknown names give an empty icon, never an error."""
    if name not in _BODY:
        return QtGui.QIcon()
    col = color or _role_color(role)
    key = (name, col)
    if key in _CACHE:
        return _CACHE[key]
    data = _svg(name, col)
    ic = QtGui.QIcon()
    for px in (16, 20, 24, 32, 40, 48, 64, 96):
        ic.addPixmap(_render(data, px))
    dim = _svg(name, QtGui.QColor(col).darker(180).name())
    for px in (16, 24, 32, 48):
        ic.addPixmap(_render(dim, px), QtGui.QIcon.Disabled)
    _CACHE[key] = ic
    return ic


def set_icon(widget, name: str, role: str = "text", size: Optional[int] = None) -> None:
    """Put an icon on a button/action/tool button and remember it, so a
    theme change can re-colour it (see refresh())."""
    widget.setProperty("opngx_icon", f"{name}|{role}")
    widget.setIcon(icon(name, role))
    if size and hasattr(widget, "setIconSize"):
        from opngx.ui import scaling

        s = scaling.px(size) if hasattr(scaling, "px") else size
        widget.setIconSize(QtCore.QSize(s, s))


def set_tab_icon(tabs: QtWidgets.QTabWidget, index: int, name: str, role: str = "text") -> None:
    tabs.setTabIcon(index, icon(name, role))
    meta = dict(tabs.property("opngx_tab_icons") or {})
    meta[str(index)] = f"{name}|{role}"
    tabs.setProperty("opngx_tab_icons", meta)


def refresh(app: Optional[QtWidgets.QApplication] = None) -> None:
    """Re-colour every icon set through this module (after a theme change)."""
    _CACHE.clear()
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        spec = w.property("opngx_icon")
        if spec:
            n, r = str(spec).split("|", 1)
            w.setIcon(icon(n, r))
        tabmeta = w.property("opngx_tab_icons") if isinstance(w, QtWidgets.QTabWidget) else None
        if tabmeta:
            for idx, spec2 in dict(tabmeta).items():
                n, r = str(spec2).split("|", 1)
                w.setTabIcon(int(idx), icon(n, r))
