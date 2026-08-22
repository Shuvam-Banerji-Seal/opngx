#!/usr/bin/env python3
"""PyInstaller entry point for the opngx studio GUI (Windows bundle)."""

import multiprocessing

multiprocessing.freeze_support()  # required for onefile fallback pool

from opngx.ui.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
