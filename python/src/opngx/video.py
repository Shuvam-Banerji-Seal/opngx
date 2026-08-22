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
    """Path to an ffmpeg executable: PATH first, then the one shipped
    inside imageio-ffmpeg (bundled in the Windows build)."""
    global _FFCACHE
    if _FFCACHE:
        return _FFCACHE
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            exe = None
    _FFCACHE = exe
    return exe


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
    lut = build_lut(b, c, g)
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
            "and try again."
        )

    meta = probe(bin_path)
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
        c = meta.contrast if c is not None else meta.contrast
        g = meta.gamma if g is not None else meta.gamma
        b = meta.brightness if b is None else b
    lut = build_lut(b, c, g)

    n = count if count is not None else meta.capacity_frames - start
    n = max(0, min(n, meta.capacity_frames - start))
    if n == 0:
        raise ValueError("empty frame range")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-s",
        f"{meta.width}x{meta.height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    t0 = time.perf_counter()
    written = 0
    try:
        # Bulk pipeline: mmap once, LUT big runs of frames with one
        # bytes.translate per chunk (C speed), few large pipe writes.
        import mmap

        CHUNK = 256  # frames per LUT/write batch
        px = meta.width * meta.height
        with open(bin_path, "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                base_off = start * meta.frame_stride + 8
                i = 0
                while i < n:
                    if should_cancel is not None and should_cancel():
                        break
                    take = min(CHUNK, n - i)
                    off0 = base_off + i * meta.frame_stride
                    span = (take - 1) * meta.frame_stride + 8 + px
                    raw = mm[off0 : off0 + span]
                    if len(raw) < span:
                        raise IOError(
                            f"unexpected EOF at frame {start + i + take - 1}"
                        )
                    lutted = raw.translate(lut)
                    view = memoryview(lutted)
                    parts = [
                        view[k * meta.frame_stride + 8 :
                             k * meta.frame_stride + 8 + px]
                        for k in range(take)
                    ]
                    try:
                        proc.stdin.write(b"".join(parts))
                    except BrokenPipeError:
                        err = (
                            proc.stderr.read().decode(errors="replace")
                            if proc.stderr
                            else "encoder died"
                        )
                        raise RuntimeError(f"ffmpeg failed: {err}") from None
                    written += take
                    i += take
                    if progress:
                        progress(min(i, n), n)
            finally:
                mm.close()
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        rc = proc.wait(timeout=60)

    dt = time.perf_counter() - t0
    if rc != 0 and written:
        raise RuntimeError(f"ffmpeg exited {rc}")
    return {
        "frames_written": written,
        "seconds": dt,
        "output": str(out),
        "cancelled": bool(should_cancel and should_cancel()),
        "fps_effective": written / max(dt, 1e-9),
    }
