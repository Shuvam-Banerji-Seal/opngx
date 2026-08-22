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


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


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
        with open(bin_path, "rb") as f:
            f.seek(start * meta.frame_stride + 8)
            stride_data = meta.width * meta.height
            for i in range(n):
                buf = f.read(stride_data)
                if len(buf) < stride_data:
                    raise IOError(f"unexpected EOF at frame {start + i}")
                try:
                    proc.stdin.write(
                        buf.translate(lut)
                    )  # LUT via bytes.translate — C speed
                    written += 1
                except BrokenPipeError:
                    err = (
                        proc.stderr.read().decode(errors="replace")
                        if proc.stderr
                        else "encoder died"
                    )
                    raise RuntimeError(f"ffmpeg failed: {err}") from None
                if progress and (i % 128 == 0 or i == n - 1):
                    progress(i + 1, n)
                if should_cancel is not None and should_cancel():
                    break
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
