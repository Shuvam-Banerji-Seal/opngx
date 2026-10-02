#!/usr/bin/env python3
"""Regenerate every logo asset from the one geometry in opngx/ui/logo.py.

    python assets/logo/generate_logo.py

Writes assets/logo/{icon,logo-dark,logo-light,wordmark,wordmark-dark}.svg,
icon-{16..1024}.png, icon.png, icon.ico/app.ico (Windows exe + installer),
and the copies the studio loads from the package (opngx/ui/assets/).
The in-app animated logo draws the same geometry live, so they always match.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opngx.ui.logo import write_assets  # noqa: E402

if __name__ == "__main__":
    for p in write_assets(str(ROOT / "assets" / "logo"), str(ROOT / "python" / "src" / "opngx" / "ui" / "assets")):
        print(os.path.relpath(p, ROOT))
