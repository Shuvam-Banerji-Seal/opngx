"""Resolution-independent UI scaling for the Qt studio (cycle 24).

Qt already multiplies everything by the OS scale factor (devicePixelRatio),
so a 4K panel at 200 % looks like 1080p and needs nothing. The cases it does
not cover are the ones users hit:

* 1280x720 / 1366x768 laptops: the studio opened at 1180x800, taller than
  the screen, with its bottom action bar off-screen;
* 4K (or 1440p) at 100 % OS scaling — common on Linux/X11 and on Windows
  with scaling turned off: every 11 px label was a quarter of its intended
  physical size.

`auto_scale()` derives a factor from the screen's LOGICAL height (already
DPR-corrected), so the two cases above get 0.9x and 2x while an OS-scaled
4K screen stays at 1x. `UiScale` then applies one factor live, to the QSS
(every `Npx` literal), the application font and every registered fixed
size, and re-applies it when the window moves to a different monitor. The
user can pin a factor from View → Interface scale; the choice is saved.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

CHOICES = (0.0, 0.9, 1.0, 1.15, 1.25, 1.5, 1.75, 2.0)  # 0.0 == auto
_PX = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)px")


def auto_scale(screen: Optional["QtGui.QScreen"]) -> float:
    """Scale factor for a screen: logical height / 1080, clamped, 0.05 steps."""
    if screen is None:
        return 1.0
    # full (logical) height, not the available area: a taskbar must not
    # push a 1080p screen off 1.0
    h = screen.geometry().height()
    s = max(0.9, min(2.0, h / 1080.0))
    return round(s * 20) / 20.0


def scale_qss(qss: str, s: float) -> str:
    """Multiply every `Npx` literal in a stylesheet by `s` (min 1 px)."""
    if abs(s - 1.0) < 1e-6:
        return qss

    def sub(m: "re.Match[str]") -> str:
        v = float(m.group(1))
        return f"{max(1, round(v * s))}px" if v else "0px"

    return _PX.sub(sub, qss)


class UiScale(QtCore.QObject):
    """Holds the current factor and re-applies it everywhere on change."""

    changed = QtCore.Signal(float)

    def __init__(self, app: "QtWidgets.QApplication", base_qss: str) -> None:
        super().__init__(app)
        self.app = app
        self.base_qss = base_qss
        f = app.font()
        self._base_pt = f.pointSizeF() if f.pointSizeF() > 0 else 10.0
        self._settings = QtCore.QSettings("opngx", "opngx-studio")
        try:
            self.choice = float(self._settings.value("ui/scale", 0.0))
        except (TypeError, ValueError):
            self.choice = 0.0
        self.factor = 1.0
        self._fixed: list[tuple[QtWidgets.QWidget, str, tuple]] = []
        self._hooks: list[Callable[[float], None]] = []

    # ------------------------------------------------------------------
    def px(self, v: float) -> int:
        return max(1, round(v * self.factor))

    def fix(self, widget: "QtWidgets.QWidget", method: str, *base) -> None:
        """Call widget.<method>(*base scaled) now and on every change."""
        self._fixed.append((widget, method, base))
        self._apply_one(widget, method, base)

    def on_change(self, fn: Callable[[float], None]) -> None:
        self._hooks.append(fn)

    def _apply_one(self, widget, method, base) -> None:
        try:
            getattr(widget, method)(*(self.px(v) for v in base))
        except RuntimeError:  # widget already deleted
            pass

    # ------------------------------------------------------------------
    def resolve(self, screen: Optional["QtGui.QScreen"] = None) -> float:
        if self.choice > 0:
            return self.choice
        return auto_scale(screen or self.app.primaryScreen())

    def apply(self, screen: Optional["QtGui.QScreen"] = None, force=False) -> None:
        s = self.resolve(screen)
        if not force and abs(s - self.factor) < 1e-6:
            return
        self.factor = s
        f = self.app.font()
        f.setPointSizeF(self._base_pt * s)
        self.app.setFont(f)
        self.app.setStyleSheet(scale_qss(self.base_qss, s))
        alive = []
        for w, m, b in self._fixed:
            try:
                w.objectName()  # raises RuntimeError once deleted
            except RuntimeError:
                continue
            alive.append((w, m, b))
            self._apply_one(w, m, b)
        self._fixed = alive
        for fn in list(self._hooks):
            try:
                fn(s)
            except RuntimeError:
                pass
        self.changed.emit(s)

    def set_choice(self, choice: float, screen=None) -> None:
        self.choice = float(choice)
        self._settings.setValue("ui/scale", self.choice)
        self.apply(screen, force=True)

    def track(self, window: "QtWidgets.QWidget") -> None:
        """Re-evaluate the automatic factor when `window` changes monitor."""
        handle = window.windowHandle()
        if handle is None:
            window.winId()  # force a native handle
            handle = window.windowHandle()
        if handle is not None:
            handle.screenChanged.connect(lambda scr: self.apply(scr))


_INSTANCE: Optional[UiScale] = None


def install(app: "QtWidgets.QApplication", base_qss: str) -> UiScale:
    global _INSTANCE
    _INSTANCE = UiScale(app, base_qss)
    _INSTANCE.apply(force=True)
    return _INSTANCE


def get() -> Optional[UiScale]:
    return _INSTANCE


def px(v: float) -> int:
    """Scaled pixels, usable even before/without an installed UiScale."""
    return _INSTANCE.px(v) if _INSTANCE is not None else int(v)


def fix(widget, method: str, *base) -> None:
    if _INSTANCE is not None:
        _INSTANCE.fix(widget, method, *base)
    else:
        getattr(widget, method)(*base)


def fit_to_screen(window: "QtWidgets.QWidget", want_w: int, want_h: int) -> None:
    """Size a top-level window to `want` (scaled) but never beyond ~94 % of
    its screen's available area, and keep it on-screen. The v1.8.0 studio
    opened at a fixed 1180x800 — taller than a 720p screen."""
    scr = window.screen() or QtWidgets.QApplication.primaryScreen()
    if scr is None:
        window.resize(want_w, want_h)
        return
    ag = scr.availableGeometry()
    w = min(px(want_w), int(ag.width() * 0.94))
    h = min(px(want_h), int(ag.height() * 0.94))
    window.resize(w, h)
    fr = window.frameGeometry()
    fr.moveCenter(ag.center())
    window.move(max(ag.left(), fr.left()), max(ag.top(), fr.top()))


def ensure_on_screen(window: "QtWidgets.QWidget") -> None:
    """After restoreGeometry(): shrink/move a window saved on a bigger or
    now-disconnected monitor so it fits the screen it lands on."""
    scr = window.screen() or QtWidgets.QApplication.primaryScreen()
    if scr is None:
        return
    ag = scr.availableGeometry()
    g = window.geometry()
    w, h = min(g.width(), ag.width()), min(g.height(), ag.height())
    x = min(max(g.x(), ag.left()), ag.right() - w + 1)
    y = min(max(g.y(), ag.top()), ag.bottom() - h + 1)
    if (w, h, x, y) != (g.width(), g.height(), g.x(), g.y()):
        window.setGeometry(x, y, w, h)
