"""Child-process helpers shared by the engine wrappers.

The Windows studio is a windowed (GUI) program; every console program it
starts (opngx-engine.exe for Verify, ffmpeg for video) would otherwise open
a console window, and closing that window kills the child.
"""

from __future__ import annotations

import os
import subprocess


def no_window() -> dict:
    """Popen/run keyword arguments that suppress the console window on
    Windows (no-op elsewhere)."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


# the engine prints UTF-8 (file paths); the locale code page (cp1252 on most
# Windows machines) raised UnicodeDecodeError for e.g. Cyrillic folder names
TEXT_UTF8 = {"text": True, "encoding": "utf-8", "errors": "replace"}
