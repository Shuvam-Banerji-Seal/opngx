#!/usr/bin/env python3
"""PyInstaller entry point for the opngx studio GUI.

Uses the Qt edition (PySide6, bundled); falls back to Tkinter if Qt is
unavailable at runtime.
"""
import multiprocessing

multiprocessing.freeze_support()          # required for onefile pools

from opngx.ui import main                 # noqa: E402  (Qt-preferred dispatcher)

if __name__ == "__main__":
    raise SystemExit(main())
