"""Video rendering — stream LUT-mapped frames straight into ffmpeg.

No intermediate files: decoded+transformed grayscale frames are piped to
ffmpeg's rawvideo input and encoded to H.264 MP4. Requires an ffmpeg
binary on PATH (checked once).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from .footage import probe
from .quality import build_lut


_FFCACHE: Optional[str] = None


def resolve_ffmpeg() -> Optional[str]:
    """Find an ffmpeg executable. Checks bundled binary first, then PATH."""
    global _FFCACHE
    if _FFCACHE:
        return _FFCACHE
    import sys, os
    search_dirs = []
    _mei = getattr(sys, "_MEIPASS", None)
    if _mei:
        search_dirs.append(_mei)
    try:
        search_dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
    except Exception:
        pass
    try:
        search_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    for _d in search_dirs:
        for _name in ("_bundled_ffmpeg.exe", "_bundled_ffmpeg",
                      "_ffmpeg.exe", "_ffmpeg"):
            _cand = os.path.join(_d, _name)
            if os.path.isfile(_cand):
                _FFCACHE = _cand
                return _FFCACHE
    exe = shutil.which("ffmpeg")
    if exe:
        _FFCACHE = exe
        return _FFCACHE
    try:
        import imageio_ffmpeg
        c = imageio_ffmpeg.get_ffmpeg_exe()
        if c and Path(c).exists():
            _FFCACHE = c
            return _FFCACHE
    except Exception:
        pass
    return None


def ffmpeg_available() -> bool:
    return resolve_ffmpeg() is not None


def read_frame_gray(bin_path: str, meta, index: int,
                    mode: str = "reference",
                    brightness: Optional[float] = None,
                    contrast: Optional[float] = None,
                    gamma: Optional[float] = None) -> bytes:
    """Decode one frame into LUT-mapped grayscale bytes (for previews)."""
    import numpy as np
    b, c, g = brightness, contrast, gamma
    if mode == "raw":
        b = c = 0; g = 1.0
    elif mode == "custom":
        b = b or 0.0; c = c or 0.0; g = g or 1.0
    else:
        b = meta.brightness if b is None else b
        c = meta.contrast if c is None else c
        g = meta.gamma if g is None else g
    lut = bytes(build_lut(b, c, g))
    with open(bin_path, "rb") as f:
        f.seek(index * meta.frame_stride + 8)
        buf = f.read(meta.width * meta.height)
    return buf.translate(lut)


def render_video(
    bin_path: str,
    out_path: str,
    *,
    mode: str = "reference",
    brightness: Optional[float] = None,
    contrast: Optional[float] = None,
    gamma: Optional[float] = None,
    width: int = 0,
    height: int = 0,
    start: int = 0,
    count: Optional[int] = None,
    fps: int = 30,
    crf: int = 18,
    preset: str = "medium",
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict:
    """Render a range of frames into an H.264 MP4 using the same verified
    transform as PNG extraction. Returns stats."""
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg was not found on PATH — required for video rendering.\n"
            "Install it (e.g. 'winget install ffmpeg' / 'pacman -S ffmpeg') "
            "and try again.")

    meta = probe(bin_path)
    if width and height:
        meta.width = int(width)
        meta.height = int(height)
        meta.frame_stride = 8 + meta.width * meta.height
        meta.capacity_frames = meta.file_size // meta.frame_stride
    if meta.width == 0 or meta.height == 0:
        raise ValueError("unknown geometry; a .footage sidecar is required")

    b, c, g = brightness, contrast, gamma
    if mode == "raw":
        b = c = 0
        g = 1.0
    elif mode == "custom":
        b = b or 0.0
        c = c or 0.0
        g = g or 1.0
    else:  # reference
        b = meta.brightness if b is None else b
        c = meta.contrast if c is None else c
        g = meta.gamma if g is None else g
    lut = bytes(build_lut(b, c, g))

    n = count if count is not None else meta.capacity_frames - start
    n = max(0, min(n, meta.capacity_frames - start))
    if n == 0:
        raise ValueError("empty frame range")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "gray",
        "-s", f"{meta.width}x{meta.height}", "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stderr=subprocess.PIPE)

    import mmap
    import os
    from concurrent.futures import ThreadPoolExecutor

    px = meta.width * meta.height
    t0 = time.perf_counter()
    written = 0
    try:
        # All-core decode: bytes.translate releases the GIL, so we split
        # the frame range into per-core chunks, translate each chunk in a
        # worker thread, then write to ffmpeg strictly in frame order.
        with open(bin_path, "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                nth = max(1, os.cpu_count() or 1)
                n_chunks = min(n, nth * 2)
                chunk_sz = max(1, n // n_chunks)

                def work(chunk_idx: int):
                    s0 = chunk_idx * chunk_sz
                    e0 = s0 + chunk_sz if chunk_idx < n_chunks - 1 else n
                    pieces = []
                    for i in range(s0, e0):
                        base = (start + i) * meta.frame_stride + 8
                        raw = mm[base:base + px]
                        pieces.append(raw.translate(lut))
                    return chunk_idx, pieces

                with ThreadPoolExecutor(max_workers=nth) as ex:
                    futures = [ex.submit(work, c) for c in range(n_chunks)]
                    buf = [None] * n_chunks
                    for fut in futures:
                        ci, pieces = fut.result()
                        buf[ci] = pieces
                    if proc.stdin and proc.stdin.writable():
                        for pieces in buf:
                            if pieces is None:
                                continue
                            if should_cancel is not None and should_cancel():
                                break
                            for blob in pieces:
                                proc.stdin.write(blob)
                                written += 1
                            if progress:
                                progress(min(written, n), n)
            finally:
                mm.close()
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        rc = proc.wait(timeout=60)

    dt = time.perf_counter() - t0
    out_path = Path(out)
    if rc != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        err = ""
        if proc.stderr:
            err = proc.stderr.read().decode(errors="replace")[-800:]
        raise RuntimeError(
            f"ffmpeg failed (rc={rc}, frames={written}): {err or 'no output produced'}")
    return {
        "frames_written": written,
        "seconds": dt,
        "output": str(out),
        "cancelled": bool(should_cancel and should_cancel()),
        "fps_effective": written / max(dt, 1e-9),
    }
