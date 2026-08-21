"""Pure-Python/numpy extraction engine — portable fallback.

Used when libopngx.so is unavailable. Produces byte-identical PNG pixel data
to the native engine; slower because deflate runs single-threaded via zlib.
Parallelism via a process pool over frame batches.
"""

from __future__ import annotations

import os
import struct
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from .quality import build_lut


def _adler32(data: bytes) -> int:
    return zlib.adler32(data) & 0xFFFFFFFF


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _chunk(typ: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + typ
        + payload
        + struct.pack(">I", _crc32(typ + payload))
    )


def encode_png(pixels: np.ndarray, bit_depth: int = 8, channels: int = 6) -> bytes:
    """Assemble a PNG file.

    pixels: (h, w, 4) uint8 for RGBA, or an (h, w) uint8 grayscale matrix
    when channels == 0.
    Matches the vendor container layout: IHDR, sRGB, gAMA, pHYs, IDAT, IEND,
    all-zero row filters.
    """
    h, w = pixels.shape[:2]
    gray = channels == 0

    if bit_depth == 16:
        bd = 16
        if gray:
            v16 = pixels.astype(np.uint16) * 257
            rawbytes = v16.view("<u2").astype(">u2").tobytes()
            stride_len = w * 2
        else:
            up = pixels.astype(np.uint16)
            up[..., :3] *= 257
            # repack each channel pair little->big endian
            pairs = up.reshape(h, w * 4, 2).view("<u2")
            rawbytes = pairs.astype(">u2").tobytes()
            stride_len = w * 8
    else:
        bd = 8
        if gray:
            rawbytes = np.ascontiguousarray(pixels).tobytes()
            stride_len = w
        else:
            rawbytes = np.ascontiguousarray(pixels).tobytes()
            stride_len = w * 4

    scan = np.zeros((h, stride_len + 1), dtype=np.uint8)
    scan[:, 1:] = np.frombuffer(rawbytes, dtype=np.uint8).reshape(h, stride_len)
    idat = zlib.compress(scan.tobytes(), 6)

    ihdr = struct.pack(">IIBBBBB", w, h, bd, 0 if gray else 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", ihdr),
            _chunk(b"sRGB", b"\x00"),
            _chunk(b"gAMA", struct.pack(">I", 45455)),
            _chunk(b"pHYs", struct.pack(">IIB", 3779, 3779, 1)),
            _chunk(
                b"IDAT",
                b"\x78\x5e" + idat[2:-4] + struct.pack(">I", _adler32(scan.tobytes())),
            ),
            _chunk(b"IEND", b""),
        ]
    )


def _render_frame(args):
    (
        bin_path,
        frame_index,
        start,
        stride,
        w,
        h,
        brightness,
        contrast,
        gamma,
        bit_depth,
        channels,
        fmt,
        jpeg_quality,
    ) = args
    ext = {"png": ".Png", "bmp": ".bmp", "tif": ".tif", "jpg": ".jpg"}[fmt]
    absolute = start + frame_index
    lut = build_lut(brightness, contrast, gamma)
    with open(bin_path, "rb") as f:
        f.seek(absolute * stride + 8)
        gray = np.frombuffer(f.read(w * h), dtype=np.uint8).reshape(h, w)
    mapped = lut[gray]
    if fmt != "png":
        from io import BytesIO
        from PIL import Image as PILImage
        im = PILImage.fromarray(mapped, mode="L")
        buf = BytesIO()
        if fmt == "jpg":
            im.convert("RGB").save(buf, format="JPEG", quality=jpeg_quality)
        elif fmt == "bmp":
            im.save(buf, format="BMP")
        else:
            im.save(buf, format="TIFF")
        return absolute, (ext, buf.getvalue())
    if channels == 0:
        return absolute, (".Png", encode_png(mapped, bit_depth, channels=0))
    rgba = np.empty((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = mapped
    rgba[..., 1] = mapped
    rgba[..., 2] = mapped
    rgba[..., 3] = 255
    return absolute, (".Png", encode_png(rgba, bit_depth, channels=6))


def extract_frames(
    bin_path: str,
    out_dir: str,
    width: int,
    height: int,
    num_frames: int,
    stride: int,
    prefix: str,
    ext: str,
    brightness: float,
    contrast: float,
    gamma: float,
    bit_depth: int = 8,
    jobs: int = 0,
    channels: int = 6,
    start: int = 0,
    fmt: str = "png",
    jpeg_quality: int = 90,
    progress=None,
    cancelled=None,
) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jobs = jobs or os.cpu_count() or 1
    done = 0
    args = [
        (
            str(bin_path),
            i,
            start,
            stride,
            width,
            height,
            brightness,
            contrast,
            gamma,
            bit_depth,
            channels,
            fmt,
            jpeg_quality,
        )
        for i in range(num_frames)
    ]
    if jobs > 1 and num_frames > 32:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            for frame_index, (fext, blob) in ex.map(_render_frame, args,
                                                    chunksize=16):
                (out / f"{prefix}{frame_index:05d}{fext}").write_bytes(blob)
                done += 1
                if progress:
                    progress(done)
                if cancelled is not None and cancelled():
                    break
    else:
        for a in args:
            frame_index, (fext, blob) = _render_frame(a)
            (out / f"{prefix}{frame_index:05d}{fext}").write_bytes(blob)
            done += 1
            if progress:
                progress(done)
            if cancelled is not None and cancelled():
                break
    return {"frames_written": done, "backend": "python-fallback"}
