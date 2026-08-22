"""Tk UI subpackage."""

from .app import App, main

__all__ = ["App", "main"]


def main(prefer_qt: bool = True) -> int:
    """Launch the studio UI: Qt edition when available, Tkinter fallback."""
    if prefer_qt:
        try:
            from .qt_app import main as qt_main
            return qt_main()
        except ImportError:
            pass
    from .app import main as tk_main
    return tk_main()
