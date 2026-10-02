"""Output formats: one table that the engine, the studio and the docs share.

Every image format writes the same pixels: the recording's sensor values
mapped through the selected transform (reference / raw / custom). A
*lossless* format stores them exactly; a *lossy* one stores an
approximation whose error `opngx.formats.quality_report()` measures.

Native formats are encoded by the C engine (all cores, fastest). The
others go through Pillow / numpy on a thread pool (Pillow releases the GIL
while it encodes), so they also use every core, only less efficiently.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np


@dataclass(frozen=True)
class FormatInfo:
    key: str
    label: str
    ext: str
    lossless: bool
    engine: str  # "native" (C engine) | "python" (Pillow / numpy)
    bit_depths: tuple = (8,)
    quality: bool = False  # takes a 1-100 quality setting
    single_file: bool = False  # one file for the whole range
    summary: str = ""
    opens_in: str = ""
    aliases: tuple = field(default_factory=tuple)


FORMATS: dict[str, FormatInfo] = {
    f.key: f
    for f in (
        FormatInfo("png", "PNG", ".Png", True, "native", (8, 16),
                   summary="Lossless, compressed (~36 KiB per 256x300 frame as grey). "
                           "TimeViewer-identical RGBA container by default; the grey option is faster and smaller.",
                   opens_in="everything"),
        FormatInfo("tif", "TIFF", ".tif", True, "native", (8, 16),
                   summary="Lossless, uncompressed grey (2x the size of PNG). 16-bit for pipelines that expect it.",
                   opens_in="ImageJ/Fiji, MATLAB, Photoshop, Python", aliases=("tiff",)),
        FormatInfo("pgm", "PGM (Netpbm)", ".pgm", True, "native", (8, 16),
                   summary="Lossless, uncompressed grey with a 15-byte header: the simplest "
                           "format to read from your own code.",
                   opens_in="ImageJ/Fiji, OpenCV, numpy/imageio, GIMP"),
        FormatInfo("bmp", "BMP", ".bmp", True, "native",
                   summary="Lossless, uncompressed 8-bit with a grey palette.",
                   opens_in="Windows tools, older software"),
        FormatInfo("webp", "WebP", ".webp", True, "python", quality=True,
                   summary="Lossless by default (quality 100, about the size of grey PNG). Below 100 it is "
                           "lossy and beats JPEG: 21 KiB at 45 dB vs JPEG's 26 KiB at 43 dB.",
                   opens_in="browsers, Python (Pillow), ImageJ with a plugin"),
        FormatInfo("jp2", "JPEG 2000", ".jp2", True, "python",
                   summary="Lossless JPEG 2000 (reversible 5/3 wavelet), about the size of grey PNG; slowest.",
                   opens_in="MATLAB, Photoshop, OpenJPEG tools, Python (Pillow)", aliases=("jpeg2000", "j2k")),
        FormatInfo("jpg", "JPEG", ".jpg", False, "native", quality=True,
                   summary="Lossy (quality 90: max error ~19 levels, ~40 dB). Previews and slides; "
                           "never for measurements.",
                   opens_in="everything", aliases=("jpeg",)),
        FormatInfo("npy", "NumPy stack", ".npy", True, "python", (8, 16), single_file=True,
                   summary="All frames in ONE lossless (frames, height, width) array file - "
                           "np.load(path, mmap_mode='r') opens 50,000 frames instantly.",
                   opens_in="Python/numpy, MATLAB (npy-matlab), Julia"),
    )
}

_ALIASES = {a: f.key for f in FORMATS.values() for a in f.aliases}


def get(fmt: str) -> FormatInfo:
    key = str(fmt).lower().lstrip(".")
    key = _ALIASES.get(key, key)
    if key not in FORMATS:
        raise ValueError(f"unknown format '{fmt}' (choose from {', '.join(FORMATS)})")
    return FORMATS[key]


def native_code(fmt: str) -> int:
    """The engine's OPNGX_FMT_* number."""
    return {"png": 0, "bmp": 1, "tif": 2, "jpg": 3, "pgm": 4}[get(fmt).key]


# --------------------------------------------------------------------------
# Pillow / numpy formats
# --------------------------------------------------------------------------
def _encode(img8: np.ndarray, fmt: FormatInfo, quality: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    im = Image.fromarray(np.ascontiguousarray(img8, dtype=np.uint8))
    buf = BytesIO()
    if fmt.key == "webp":
        # method 1: measured 3.4x faster than 4 for files 0.3% larger
        if quality >= 100:
            im.save(buf, format="WEBP", lossless=True, quality=25, method=1)
        else:
            im.save(buf, format="WEBP", quality=int(quality), method=4)
    elif fmt.key == "jp2":
        im.save(buf, format="JPEG2000", irreversible=False)  # reversible = lossless
    else:  # pragma: no cover - guarded by the caller
        raise ValueError(fmt.key)
    return buf.getvalue()


def _processes_usable() -> bool:
    """A process pool can start workers only if they can import __main__:
    a frozen app, or a program started from a real file (not stdin / -c)."""
    import sys

    if getattr(sys, "frozen", False):
        return True
    main = sys.modules.get("__main__")
    f = getattr(main, "__file__", None)
    return bool(f) and os.path.isfile(f)


def _proc_chunk(args) -> int:
    """Process-pool worker (JPEG 2000: Pillow holds the GIL while encoding
    it, so threads ran one at a time - measured 0.9x on 16 threads)."""
    (bin_path, out_dir, key, width, height, stride, start, i0, i1, crop, lut8, prefix, suffix, quality) = args
    raw = np.memmap(bin_path, dtype=np.uint8, mode="r")
    cx, cy, cw, ch = crop
    info = FORMATS[key]
    lut8 = np.asarray(lut8, dtype=np.uint8)
    for i in range(i0, i1):
        o = (start + i) * stride + 8
        f = raw[o : o + width * height].reshape(height, width)[cy : cy + ch, cx : cx + cw]
        Path(out_dir, f"{prefix}{start + i:05d}{suffix}").write_bytes(_encode(lut8[f], info, quality))
    return i1 - i0


def extract_python_format(
    bin_path: str,
    out_dir: str,
    *,
    fmt: str,
    width: int,
    height: int,
    stride: int,
    start: int,
    count: int,
    lut8: np.ndarray,
    bit_depth: int = 8,
    quality: int = 100,
    crop: tuple[int, int, int, int] = (0, 0, 0, 0),
    prefix: str = "brow_",
    ext: Optional[str] = None,
    jobs: int = 0,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict:
    """Write frames start..start+count in a Pillow/numpy format. Returns
    {"frames_written", "seconds", "cancelled", "paths"}."""
    from concurrent.futures import ThreadPoolExecutor

    info = get(fmt)
    cx, cy, cw, ch = crop
    cw = cw or (width - cx)
    ch = ch or (height - cy)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = np.memmap(bin_path, dtype=np.uint8, mode="r")
    nframes_file = raw.size // stride
    count = max(0, min(int(count), nframes_file - start))
    frames = raw[: nframes_file * stride].reshape(nframes_file, stride)
    t0 = time.perf_counter()
    lut8 = np.asarray(lut8, dtype=np.uint8)

    def window(i0: int, i1: int) -> np.ndarray:
        px = frames[start + i0 : start + i1, 8 : 8 + width * height].reshape(-1, height, width)
        return lut8[px[:, cy : cy + ch, cx : cx + cw]]

    done = 0
    cancelled = False
    paths: list[str] = []
    if info.key == "npy":
        dtype = np.uint16 if bit_depth == 16 else np.uint8
        path = out / f"{prefix}stack.npy"
        arr = np.lib.format.open_memmap(path, mode="w+", dtype=dtype, shape=(count, ch, cw))
        step = 512
        for i0 in range(0, count, step):
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            i1 = min(count, i0 + step)
            w8 = window(i0, i1)
            arr[i0:i1] = w8.astype(np.uint16) * 257 if dtype is np.uint16 else w8
            done = i1
            if progress:
                progress(done, count)
        arr.flush()
        del arr
        paths.append(str(path))
    elif info.key == "jp2" and _processes_usable():
        # processes: Pillow holds the GIL while it encodes JPEG 2000. A pool
        # whose workers cannot start (no importable __main__) used to wait
        # forever, so any 120 s without progress falls back to threads.
        from concurrent.futures import ProcessPoolExecutor
        from concurrent.futures import TimeoutError as _FutTimeout

        suffix = ext or info.ext
        workers = jobs or os.cpu_count() or 1
        chunk = 32
        args = [(bin_path, str(out), info.key, width, height, stride, start, i0, min(count, i0 + chunk),
                 (cx, cy, cw, ch), lut8.tolist(), prefix, suffix, quality)
                for i0 in range(0, count, chunk)]
        finished = set()
        pool = ProcessPoolExecutor(max_workers=workers)
        try:
            futs = [pool.submit(_proc_chunk, a) for a in args]
            for k, fu in enumerate(futs):
                try:
                    done += fu.result(timeout=120)
                except (_FutTimeout, Exception):  # noqa: BLE001 - broken/stuck pool
                    break
                finished.add(k)
                if progress:
                    progress(done, count)
                if should_cancel is not None and should_cancel():
                    break
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if len(finished) < len(args) and not (should_cancel is not None and should_cancel()):
            for k, a in enumerate(args):  # finish what the pool did not, in this process
                if k in finished:
                    continue
                if should_cancel is not None and should_cancel():
                    break
                done += _proc_chunk(a)
                if progress:
                    progress(done, count)
        cancelled = done < count
    else:
        suffix = ext or info.ext
        workers = jobs or os.cpu_count() or 1
        chunk = 64

        def job(i0: int):
            if should_cancel is not None and should_cancel():
                return 0
            i1 = min(count, i0 + chunk)
            w8 = window(i0, i1)
            for k in range(i1 - i0):
                (out / f"{prefix}{start + i0 + k:05d}{suffix}").write_bytes(_encode(w8[k], info, quality))
            return i1 - i0

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for n in pool.map(job, range(0, count, chunk)):
                done += n
                if progress:
                    progress(done, count)
        cancelled = done < count
    return {"frames_written": done, "seconds": time.perf_counter() - t0,
            "cancelled": cancelled, "paths": paths}


# --------------------------------------------------------------------------
# Quality: what each format actually stores
# --------------------------------------------------------------------------
def read_frame(path: str) -> np.ndarray:
    """Decode one written frame back to an array (any format above), for
    verification. 16-bit containers come back as uint16."""
    p = str(path)
    low = p.lower()
    if low.endswith(".npy"):
        return np.load(p, mmap_mode="r")
    if low.endswith(".pgm"):
        d = open(p, "rb").read()
        parts = d.split(b"\n", 3)
        w, h = map(int, parts[1].split())
        mx = int(parts[2])
        return np.frombuffer(parts[3], ">u2" if mx > 255 else np.uint8).reshape(h, w)
    from PIL import Image

    im = Image.open(p)
    a = np.asarray(im)
    if a.ndim == 3:
        a = a[..., 0]
    return a


def quality_report(expected: np.ndarray, decoded: np.ndarray) -> dict:
    """Exactness and error of one decoded frame against the expected pixels
    (both on the same scale)."""
    e = expected.astype(np.float64)
    d = decoded.astype(np.float64)
    if e.shape != d.shape:
        return {"exact": False, "shape_mismatch": [list(e.shape), list(d.shape)]}
    diff = d - e
    mse = float(np.mean(diff**2))
    peak = 65535.0 if expected.dtype == np.uint16 else 255.0
    return {
        "exact": mse == 0.0,
        "max_abs_error": float(np.max(np.abs(diff))),
        "mean_abs_error": float(np.mean(np.abs(diff))),
        "psnr_db": float("inf") if mse == 0 else float(10 * np.log10(peak**2 / mse)),
    }
