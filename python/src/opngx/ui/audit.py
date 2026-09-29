"""Layout audit (v2.0): find overlapping and clipped widgets automatically.

Used by the test-suite on every tab and dialog at several screen sizes and
themes, so "a button is drawn on top of another" is caught by a machine,
not by a user. A finding is one of:

* ``overlap``  — two visible sibling widgets intersect;
* ``outside``  — a widget sticks out of its parent (and is not inside a
  scroll area, where that is the point);
* ``clipped``  — a button / single-line label is narrower than its text.
"""

from __future__ import annotations

from PySide6 import QtWidgets

# containers whose children legitimately stack or scroll
_SKIP_PARENTS = (
    QtWidgets.QStackedWidget,
    QtWidgets.QAbstractScrollArea,
    QtWidgets.QTabBar,
    QtWidgets.QSplitter,
    QtWidgets.QMenuBar,
    QtWidgets.QToolBar,
    QtWidgets.QAbstractSpinBox,
    QtWidgets.QComboBox,
    QtWidgets.QDockWidget,
    QtWidgets.QMainWindow,
    QtWidgets.QProgressBar,
)


def _in_scroll_area(w) -> bool:
    p = w.parentWidget()
    while p is not None:
        if isinstance(p, QtWidgets.QAbstractScrollArea):
            return True
        p = p.parentWidget()
    return False


def _label(w) -> str:
    name = type(w).__name__
    txt = ""
    if hasattr(w, "text") and callable(w.text):
        try:
            txt = str(w.text())[:30]
        except TypeError:
            txt = ""
    on = w.objectName()
    return f"{name}" + (f"#{on}" if on and not on.startswith("qt_") else "") + (f"('{txt}')" if txt else "")


def audit(root: QtWidgets.QWidget, min_overlap: int = 3) -> list[str]:
    issues: list[str] = []
    widgets = [root] + root.findChildren(QtWidgets.QWidget)
    for w in widgets:
        if not w.isVisible() or w.width() <= 0:
            continue
        par = w.parentWidget()
        # --- clipped text
        if isinstance(w, (QtWidgets.QPushButton, QtWidgets.QToolButton)) and w.text():
            if w.sizeHint().width() - w.width() > 2 and not isinstance(par, QtWidgets.QTabBar):
                issues.append(f"clipped: {_label(w)} is {w.width()}px, needs {w.sizeHint().width()}px")
        elif isinstance(w, QtWidgets.QLabel) and not w.wordWrap() and w.text() and w.pixmap().isNull():
            fm = w.fontMetrics()
            txt = w.text()
            if "<" not in txt and "\n" not in txt:
                need = fm.horizontalAdvance(txt) + w.contentsMargins().left() + w.contentsMargins().right()
                if need - w.width() > 3:
                    issues.append(f"clipped: {_label(w)} is {w.width()}px, text needs {need}px")
        # --- outside the parent
        if par is not None and par.isVisible() and not isinstance(par, _SKIP_PARENTS) and not _in_scroll_area(w):
            g = w.geometry()
            pr = par.rect()
            if g.right() > pr.right() + 2 or g.bottom() > pr.bottom() + 2 or g.left() < -2 or g.top() < -2:
                if not w.isWindow():
                    issues.append(f"outside: {_label(w)} {g.getRect()} exceeds parent {_label(par)} {pr.getRect()}")
    # --- sibling overlaps (only among layout-managed plain children)
    seen = set()
    for par in widgets:
        if not par.isVisible() or isinstance(par, _SKIP_PARENTS):
            continue
        kids = [
            c for c in par.children()
            if isinstance(c, QtWidgets.QWidget) and c.isVisible() and not c.isWindow()
            and c.width() > 0 and c.height() > 0
            and not isinstance(c, (QtWidgets.QRubberBand, QtWidgets.QSizeGrip, QtWidgets.QFocusFrame))
            and not c.objectName().startswith("qt_")
        ]
        for i, a in enumerate(kids):
            for b in kids[i + 1 :]:
                inter = a.geometry().intersected(b.geometry())
                if inter.width() >= min_overlap and inter.height() >= min_overlap:
                    key = (id(a), id(b))
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(
                        f"overlap: {_label(a)} {a.geometry().getRect()} and {_label(b)} "
                        f"{b.geometry().getRect()} in {_label(par)}"
                    )
    return issues
