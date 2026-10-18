"""Output file names and times that follow frame order (v2.1.1).

The C engine applies the same two rules (src/extract.c), so every path -
engine, pure-Python fallback, Pillow/numpy formats - names and stamps files
identically:

* the frame number is zero-padded to the digits of the recording's LAST
  frame index, at least 5 (TimeViewer's own width). With a fixed 5 digits a
  500,000-frame recording sorted brow_100000 between brow_10000 and
  brow_10001 in every name-sorted listing (Explorer, ImageJ, sorted(glob()));
* each file's modification time follows its frame order: frame i of a run
  gets base + i milliseconds, the last one "now". Frames are written by many
  threads at once, so their natural times were out of order and any tool
  sorting by date mixed the sequence up.
"""

from __future__ import annotations

import os
import time


def name_width(capacity_frames: int) -> int:
    last = max(0, int(capacity_frames) - 1)
    return max(5, len(str(last)))


def frame_name(prefix: str, index: int, width: int, ext: str) -> str:
    return f"{prefix}{int(index):0{width}d}{ext}"


def mtime_base_ms(n_frames: int) -> int:
    return int(time.time()) * 1000 - max(0, int(n_frames) - 1)


def stamp(path, base_ms: int, i: int) -> None:
    """Set the modification time of the i-th file of a run (best effort)."""
    ns = (int(base_ms) + int(i)) * 1_000_000
    try:
        os.utime(path, ns=(ns, ns))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Output-folder guard - the same record the C engine writes (src/extract.c,
# output_guard), so engine and Python paths recognise each other's runs.
# ---------------------------------------------------------------------------
RUN_FILE = ".opngx-run"  # hidden: frame globbing never sees it


class MixedOutputError(RuntimeError):
    """The output folder holds frames of another recording / other settings."""


def _fnv1a(data: bytes, h: int = 1469598103934665603) -> int:
    for b in data:
        h ^= b
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def run_identity(bin_path: str, stride: int, src_w: int, src_h: int, lut8, bit_depth: int, channels: int,
                 fmt: str, quality: int, crop, prefix: str, ext: str) -> tuple[str, str]:
    import numpy as np

    with open(bin_path, "rb") as fh:
        ts0 = int.from_bytes(fh.read(8).ljust(8, b"\0"), "little")
    frames = os.path.getsize(bin_path) // max(1, stride)
    rec = f"recording=first_timestamp {ts0}, frames {frames}, {src_w}x{src_h}"
    h = _fnv1a(np.asarray(lut8, dtype=np.uint8).tobytes())
    try:
        from .formats import native_code

        fcode = str(native_code(fmt))
    except (KeyError, ValueError):
        fcode = str(fmt)  # Pillow/numpy formats have no engine number
    cx, cy, cw, ch = crop
    color_type = 0 if channels == 0 else 6
    q = int(quality) if fmt in ("jpg", "webp") else 0
    st = (f"settings=curve {h:016x}, bits {bit_depth}, channels {color_type}, format {fcode}, quality {q}, "
          f"crop {cx},{cy},{cw}x{ch}, names {prefix}#{ext}")
    return rec, st


def _read_record(out_dir: str) -> dict:
    path = os.path.join(out_dir, RUN_FILE)
    old = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                k, sep, _v = line.rstrip("\r\n").partition("=")
                if sep:
                    old[k] = line.rstrip("\r\n")
    return old


def conflict(out_dir: str, rec: str, st: str):
    """None if a run with this identity may write into out_dir, else why not."""
    old = _read_record(out_dir)
    if not old or (old.get("recording") == rec and old.get("settings") == st):
        return None
    what = "another recording" if old.get("recording") != rec else "the same recording with other settings"
    return f"{out_dir} holds frames of {what} ({old.get('source', 'source=?')[7:]})"


def clear_frames(out_dir: str, prefix: str, ext: str) -> int:
    """Delete ONLY what an extraction with this naming wrote into out_dir:
    <prefix><digits><ext> frames, <prefix>stack.npy, <prefix>_timestamps.csv,
    metadata.json and the run record. Anything else is left alone. Returns
    the number of files removed."""
    import re

    if not os.path.isdir(out_dir):
        return 0
    namings = {(prefix, ext)}
    old = _read_record(out_dir).get("settings", "")
    m = re.search(r"names (.*)#(.*)$", old)
    if m:  # the PREVIOUS run's naming too, or its frames would survive
        namings.add((m.group(1), m.group(2)))
    pats, extra = [], {"metadata.json", RUN_FILE}
    for pfx, ex in namings:
        pats.append(re.compile(re.escape(pfx) + r"\d+" + re.escape(ex) + r"$", re.IGNORECASE))
        extra |= {f"{pfx}stack.npy", f"{pfx}_timestamps.csv"}
    n = 0
    for name in os.listdir(out_dir):
        if any(p_.match(name) for p_ in pats) or name in extra:
            p = os.path.join(out_dir, name)
            if os.path.isfile(p):
                _set_hidden(p, False)
                os.remove(p)
                n += 1
    return n


def output_guard(out_dir: str, bin_path: str, rec: str, st: str, allow_mixed: bool = False) -> None:
    """Refuse (MixedOutputError) to write into a folder whose frames came
    from another recording or other settings; record this run otherwise."""
    from opngx import __version__

    path = os.path.join(out_dir, RUN_FILE)
    old = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                k, _, v = line.rstrip("\r\n").partition("=")
                if _:
                    old[k] = line.rstrip("\r\n")
        same = old.get("recording") == rec and old.get("settings") == st
        if not same and not allow_mixed:
            what = "ANOTHER recording" if old.get("recording") != rec else "the same recording with OTHER settings"
            src = old.get("source", "source=see .opngx-run")[7:]
            raise MixedOutputError(
                f"the output folder already holds frames of {what} ({src}). Writing this run there would "
                f"mix two sequences. Choose an empty folder, or allow mixing explicitly (allow_mixed=True / "
                f"--allow-mixed). Folder: {out_dir}")
    try:
        os.makedirs(out_dir, exist_ok=True)
        _set_hidden(path, False)  # Windows: a hidden file cannot be opened for writing
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"opngx-run 1 (written by opngx {__version__}; identifies the frames in this folder)\n"
                     f"{rec}\n{st}\nsource={bin_path}\n")
        _set_hidden(path, True)
    except OSError:
        pass


def _set_hidden(path: str, hidden: bool) -> None:
    if os.name != "nt" or not os.path.exists(path):
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        a = k32.GetFileAttributesW(str(path))
        if a != -1 and a != 0xFFFFFFFF:
            a = (a | 0x2) if hidden else (a & ~0x2)
            k32.SetFileAttributesW(str(path), a or 0x80)
    except Exception:  # noqa: BLE001
        pass
