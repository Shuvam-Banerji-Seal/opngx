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


def recording_key(root: str, bin_path: str) -> str:
    """Identity of a recording inside a batch mother folder.

    Cycle-22 field finding: keying the output folder on the .bin FILENAME
    silently destroys data whenever two recordings share a name. Cameras
    are routinely dumped as <root>/<camera>/recording.bin, so a whole
    night's batch collapsed into one folder and the later recording
    overwrote the earlier one frame-for-frame (16 frames extracted, 8 on
    disk). In the mother-folder architecture the RECORDING FOLDER is the
    identity, so that is what we key on. A loose .bin sitting directly in
    the root falls back to its stem, which is unique in that position.
    """
    root_abs = os.path.abspath(root)
    bin_abs = os.path.abspath(bin_path)
    parent = os.path.dirname(bin_abs)
    if parent and os.path.abspath(parent) != root_abs:
        return safe_name(os.path.basename(parent))
    return safe_name(os.path.splitext(os.path.basename(bin_abs))[0])


def batch_out_dir(out_root: str, root: str, bin_path: str, fmt: str = "png") -> str:
    """Per-recording output directory for a batch run.

    Same shape as run_out_dir (<out>/<recording>/<FMT>/) but keyed on the
    recording folder so same-named .bin files cannot collide.
    """
    return os.path.join(out_root, recording_key(root, bin_path), (fmt or "png").upper())


def mp4_dir(out_root: str, bin_path: str) -> str:
    """Sibling MP4 folder for a recording under the v1.6 tree."""
    stem = safe_name(os.path.splitext(os.path.basename(bin_path))[0])
    return os.path.join(out_root, stem, "MP4")
