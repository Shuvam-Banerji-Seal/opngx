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
from typing import Any, Callable, Optional

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
    import glob as _g

    for _d in search_dirs:
        for _name in (
            "_bundled_ffmpeg.exe",
            "_bundled_ffmpeg",
            "_ffmpeg.exe",
            "_ffmpeg",
        ):
            _cand = os.path.join(_d, _name)
            if os.path.isfile(_cand):
                _FFCACHE = _cand
                return _FFCACHE
    # glob fallback: any file starting with _bundled_ffmpeg or _ffmpeg
    for _d in search_dirs:
        try:
            for _pat in ("_bundled_ffmpeg*", "_ffmpeg*"):
                for _cand in _g.glob(os.path.join(_d, _pat)):
                    if os.path.isfile(_cand):
                        _FFCACHE = _cand
                        return _FFCACHE
        except Exception:
            pass
    # PyInstaller imageio_ffmpeg hook puts the binary at
    # _MEIPASS/imageio_ffmpeg/binaries/ffmpeg-*.exe
    if _mei:
        _iio_bin = os.path.join(_mei, "imageio_ffmpeg", "binaries")
        try:
            for _f in os.listdir(_iio_bin):
                if "ffmpeg" in _f.lower() and (_f.endswith(".exe") or not "." in _f):
                    _cand = os.path.join(_iio_bin, _f)
                    if os.path.isfile(_cand):
                        _FFCACHE = _cand
                        return _FFCACHE
        except Exception:
            pass
    # also check the module dir's imageio_ffmpeg subpath
    try:
        _mod_dir = os.path.dirname(os.path.abspath(__file__))
        _iio_bin2 = os.path.join(_mod_dir, "imageio_ffmpeg", "binaries")
        for _f in os.listdir(_iio_bin2):
            if "ffmpeg" in _f.lower() and (_f.endswith(".exe") or not "." in _f):
                _cand = os.path.join(_iio_bin2, _f)
                if os.path.isfile(_cand):
                    _FFCACHE = _cand
                    return _FFCACHE
    except Exception:
        pass
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


def resolve_transform(
    meta,
    mode: str = "reference",
    brightness: Optional[float] = None,
    contrast: Optional[float] = None,
    gamma: Optional[float] = None,
) -> tuple[float, float, float]:
    """The (B, C, G) a mode resolves to — one rule for previews, video and
    extraction. `None` means "from this recording's .footage" in reference
    mode and the identity value in custom mode."""
    b, c, g = brightness, contrast, gamma
    if mode == "raw":
        return 0.0, 0.0, 1.0
    if mode == "custom":
        return (
            0.0 if b is None else float(b),
            0.0 if c is None else float(c),
            1.0 if not g else float(g),
        )
    return (
        float(meta.brightness if b is None else b),
        float(meta.contrast if c is None else c),
        float(meta.gamma if g is None else g),
    )


def read_frame_gray(
    bin_path: str,
    meta,
    index: int,
    mode: str = "reference",
    brightness: Optional[float] = None,
    contrast: Optional[float] = None,
    gamma: Optional[float] = None,
) -> bytes:
    """Decode one frame into LUT-mapped grayscale bytes (for previews)."""
    b, c, g = resolve_transform(meta, mode, brightness, contrast, gamma)
    lut = bytes(build_lut(b, c, g))
    with open(bin_path, "rb") as f:
        f.seek(index * meta.frame_stride + 8)
        buf = f.read(meta.width * meta.height)
    return buf.translate(lut)


class FrameReader:
    """Random-access frame decoder for interactive previews (cycle 23).

    The studio used to reopen the multi-GB .bin and rebuild the LUT for
    every scrub step. This keeps one read-only memmap per recording and a
    small LUT cache, so scrubbing costs one strided copy plus one gather.
    """

    def __init__(self, meta) -> None:
        import numpy as np

        self.meta = meta
        self.width, self.height = int(meta.width), int(meta.height)
        self.frames = int(meta.capacity_frames)
        self._np = np
        self._mm = None
        if self.frames > 0 and self.width > 0 and self.height > 0:
            self._mm = np.memmap(
                meta.bin_path,
                dtype=np.uint8,
                mode="r",
                shape=(self.frames, int(meta.frame_stride)),
            )
        self._luts: dict[tuple[float, float, float], Any] = {}

    def lut(self, mode="reference", brightness=None, contrast=None, gamma=None):
        key = resolve_transform(self.meta, mode, brightness, contrast, gamma)
        lut = self._luts.get(key)
        if lut is None:
            if len(self._luts) > 32:
                self._luts.clear()
            lut = self._np.asarray(build_lut(*key), dtype=self._np.uint8)
            self._luts[key] = lut
        return lut

    def raw(self, index: int):
        """(H, W) uint8 view of the untransformed sensor bytes."""
        if self._mm is None:
            raise ValueError("recording has no decodable frames")
        index = max(0, min(int(index), self.frames - 1))
        return self._mm[index, 8 : 8 + self.width * self.height].reshape(
            self.height, self.width
        )

    def gray(self, index: int, crop=None, **transform):
        """Contiguous (h, w) uint8 frame through the resolved LUT, optionally
        restricted to an (x, y, w, h) crop."""
        px = self.raw(index)
        if crop:
            x, y, w, h = crop
            px = px[y : y + h, x : x + w]
        return self._np.take(self.lut(**transform), px)

    def close(self) -> None:
        self._mm = None


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
    crop: Optional[tuple[int, int, int, int]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    footage: Optional[str] = None,
) -> dict:
    """Render a range of frames into an H.264 MP4 using the same verified
    transform as PNG extraction. Returns stats."""
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg was not found on PATH — required for video rendering.\n"
            "Install it (e.g. 'winget install ffmpeg' / 'pacman -S ffmpeg') "
            "and try again."
        )

    meta = probe(bin_path, footage)
    if width and height:
        meta.width = int(width)
        meta.height = int(height)
        meta.frame_stride = 8 + meta.width * meta.height
        meta.capacity_frames = meta.file_size // meta.frame_stride
    if meta.width == 0 or meta.height == 0:
        raise ValueError("unknown geometry; a .footage sidecar is required")

    b, c, g = resolve_transform(meta, mode, brightness, contrast, gamma)
    import numpy as np

    lut = bytes(build_lut(b, c, g))

    # region of interest (cycle 22): the MP4 must carry the SAME window the
    # PNGs do, or the two outputs of one run disagree.
    W, H = int(meta.width), int(meta.height)
    if crop is None:
        cx = cy = cw = ch = 0
    else:
        cx, cy, cw, ch = (int(v) for v in crop)
    if cw == 0:
        cw = W - cx
    if ch == 0:
        ch = H - cy
    if cx < 0 or cy < 0 or cw < 1 or ch < 1 or cx + cw > W or cy + ch > H:
        raise ValueError(
            f"crop {cx},{cy} {cw}x{ch} does not fit inside the {W}x{H} frame"
        )

    n = count if count is not None else meta.capacity_frames - start
    n = max(0, min(n, meta.capacity_frames - start))
    if n == 0:
        raise ValueError("empty frame range")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # CRITICAL: use the RESOLVED ffmpeg (bundled _MEIPASS copy, app dir,
    # or PATH). Passing the bare name "ffmpeg" made Windows fail with
    # WinError 2 "The system cannot find the file specified" whenever the
    # user had no ffmpeg on PATH — even though the installer bundles one.
    ffmpeg_bin = resolve_ffmpeg()
    if not ffmpeg_bin:
        raise RuntimeError(
            "ffmpeg was not found (bundled copy missing and not on PATH).\n"
            "Reinstall opngx, or install ffmpeg and try again."
        )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-s",
        f"{cw}x{ch}",
        "-r",
        str(fps),
        "-i",
        "-",
    ]
    # H.264 4:2:0 needs even dimensions; a hand-dragged crop is odd half the
    # time and ffmpeg refused it outright (cycle 23). Pad ONE black
    # column/row rather than trimming, so every selected pixel is kept.
    if cw % 2 or ch % 2:
        cmd += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:black"]
    cmd += [
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
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    import os
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    t0 = time.perf_counter()
    written = 0
    try:
        # Streaming pipeline: translate chunk k+1 on the workers while
        # chunk k streams into ffmpeg, RAM bounded to a few chunks.
        # A read-only memmap viewed as (frames, stride) turns the crop into
        # one strided slice + one LUT gather per chunk; v1.7.0 built every
        # cropped frame from `ch` separate Python byte slices (cycle 23).
        frames_arr = np.memmap(
            bin_path,
            dtype=np.uint8,
            mode="r",
            shape=(meta.capacity_frames, meta.frame_stride),
        )
        nth = max(1, os.cpu_count() or 1)
        n_chunks = min(n, nth * 2)
        chunk_sz = max(1, n // n_chunks)
        max_inflight = 4  # bounds RAM to ~4 chunks

        def work(chunk_idx: int):
            if should_cancel is not None and should_cancel():
                return chunk_idx, None
            s0 = chunk_idx * chunk_sz
            e0 = s0 + chunk_sz if chunk_idx < n_chunks - 1 else n
            px = frames_arr[start + s0 : start + e0, 8 : 8 + W * H]
            win = px.reshape(-1, H, W)[:, cy : cy + ch, cx : cx + cw]
            # one contiguous gather of the window, then ONE bytes.translate
            # for the whole chunk: measured 1.8x the v1.7.0 per-row feed and
            # 1.3x a numpy LUT gather on real 256x300 footage
            flat = np.ascontiguousarray(win).tobytes().translate(lut)
            fb = cw * ch
            return chunk_idx, [flat[k * fb : (k + 1) * fb] for k in range(e0 - s0)]

        inflight = deque()
        next_chunk = 0
        cancelled = False
        with ThreadPoolExecutor(max_workers=nth) as ex:
            while next_chunk < n_chunks and len(inflight) < max_inflight:
                inflight.append(ex.submit(work, next_chunk))
                next_chunk += 1
            while inflight:
                _, pieces = inflight.popleft().result()
                if next_chunk < n_chunks:
                    inflight.append(ex.submit(work, next_chunk))
                    next_chunk += 1
                if pieces is None:
                    cancelled = True
                    break
                if proc.stdin and not proc.stdin.closed:
                    for blob in pieces:
                        proc.stdin.write(blob)
                        written += 1
                if progress:
                    progress(min(written, n), n)
                if should_cancel is not None and should_cancel():
                    cancelled = True
                    break
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        rc = proc.wait(timeout=60)

    dt = time.perf_counter() - t0
    out_path = Path(out)
    cancelled = bool(should_cancel and should_cancel())
    if (
        rc != 0
        or not out_path.exists()
        or (out_path.stat().st_size == 0 and not cancelled)
    ):
        err = ""
        if proc.stderr:
            err = proc.stderr.read().decode(errors="replace")[-800:]
        raise RuntimeError(
            f"ffmpeg failed (rc={rc}, frames={written}): {err or 'no output produced'}"
        )
    return {
        "frames_written": written,
        "seconds": dt,
        "output": str(out),
        "cancelled": cancelled,
        "fps_effective": written / max(dt, 1e-9),
    }
