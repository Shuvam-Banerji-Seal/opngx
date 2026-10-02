"""opngx studio UI: the Qt edition, with a Tkinter fallback.

Nothing is imported eagerly. v1.8.0 and earlier did `from .app import ...`
here, so importing ANY `opngx.ui.*` module — the Qt studio included —
required tkinter, which uv's standalone Pythons and many Linux installs do
not ship (the CI failure on every push since v1.6.x).
"""

__all__ = ["App", "main"]


def __getattr__(name):  # lazy: `from opngx.ui import App` still works
    if name == "App":
        from .app import App

        return App
    raise AttributeError(name)


def main(prefer_qt: bool = True) -> int:
    """Launch the studio UI: Qt edition when available, Tkinter fallback."""
    qt_error = ""
    if prefer_qt:
        try:
            from . import qt_app
        except ImportError as exc:
            qt_app = None
            qt_error = f"{type(exc).__name__}: {exc}"
        # qt_app imports fine without PySide6 (guarded) and its main() then
        # raises SystemExit — so check the flag, or the Tk fallback promised
        # above is never reached
        if qt_app is not None and getattr(qt_app, "_QT", False):
            return qt_app.main()
        if qt_app is not None:
            qt_error = getattr(qt_app, "_QT_ERROR", "") or qt_error
    try:
        from .app import main as tk_main
    except ImportError as exc:
        # v2.1: the packaged studio has no Tk; report WHY Qt failed instead
        # of "No module named 'tkinter'"
        raise RuntimeError(
            "The opngx studio could not start its Qt interface"
            + (f" ({qt_error})" if qt_error else "")
            + f", and the Tk fallback is not available ({exc})."
        ) from exc
    return tk_main()
