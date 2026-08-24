"""v1.6 output-tree helpers — Qt-free so the CLI can use them too.

Layout produced by the studio and by `--layout format`:

    <mother-out>/
      <recording-name>/          (camera/recording stem, filename-safe)
        PNG/  *.Png
        JPG/  *.jpg              (when that format was selected)
        BMP/  TIF/               (likewise)
        MP4/  <name>.mp4         (Render-video joins its sibling folder)
"""

from __future__ import annotations

import os

_WINDOWS_BAD = '\\/:*?"<>|'


def safe_name(name: str) -> str:
    """Filename-safe form of a camera/recording name (Windows forbids
    \\/ : * ? " < > | and trailing dots/spaces)."""
    for ch in _WINDOWS_BAD:
        name = name.replace(ch, "_")
    name = name.rstrip(" .")
    return name if name else "_"


def run_out_dir(out_root: str, bin_path: str, fmt: str = "png") -> str:
    """Directory for one extraction run under the v1.6 tree."""
    stem = safe_name(os.path.splitext(os.path.basename(bin_path))[0])
    return os.path.join(out_root, stem, (fmt or "png").upper())


def mp4_dir(out_root: str, bin_path: str) -> str:
    """Sibling MP4 folder for a recording under the v1.6 tree."""
    stem = safe_name(os.path.splitext(os.path.basename(bin_path))[0])
    return os.path.join(out_root, stem, "MP4")
