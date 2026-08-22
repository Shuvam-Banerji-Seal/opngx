"""High-level extraction API with progress reporting and cancellation."""

from __future__ import annotations

import ctypes
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ._engine import (
    OpngxParams,
    OpngxStats,
    BACKEND_AUTO,
    BACKEND_LIBDEFLATE,
    BACKEND_ZLIB,
    MODE_CUSTOM,
    MODE_RAW,
    load_library,
)
from .footage import FootageMetadata, probe, read_timestamps
from .quality import QualityMode


@dataclass
class ExtractStats:
    frames_written: int
    frames_total: int
    bytes_written: int
    seconds: float
    mib_per_s_in: float
    frames_per_s: float
    backend: str
    cancelled: bool = False

    def __str__(self) -> str:
        return (
            f"{self.frames_written}/{self.frames_total} frames in "
            f"{self.seconds:.2f}s | {self.frames_per_s:.0f} fps | "
            f"{self.mib_per_s_in:.1f} MiB/s | {self.backend}"
        )


class Extractor:
    """Extract PNGs from an Optronis .bin.

    Uses the native engine when available; falls back to a numpy/zlib engine.
    """

    def __init__(self, bin_path: str | Path,
                 footage_path: str | Path | None = None,
                 *, width: int = 0, height: int = 0):
        self.meta: FootageMetadata = probe(bin_path, footage_path)
        # manual geometry override — for recordings without a .footage
        # sidecar the user supplies width/height (remembered by the UI)
        if width and height:
            self.meta.width = int(width)
            self.meta.height = int(height)
            self.meta.frame_stride = 8 + self.meta.width * self.meta.height
            self.meta.capacity_frames = (
                self.meta.file_size // self.meta.frame_stride)

    # ------------------------------------------------------------------ #
    def extract(
        self,
        out_dir: str | Path,
        *,
        mode: str | QualityMode = QualityMode.REFERENCE,
        brightness: Optional[float] = None,
        contrast: Optional[float] = None,
        gamma: Optional[float] = None,
        bit_depth: int = 8,
        channels: int = 6,  # 6 RGBA or 0 grayscale fast path
        fmt: str = "png",   # png | bmp | tif | jpg
        jpeg_quality: int = 90,
        backend: str = "auto",  # auto | libdeflate | zlib
        jobs: int = 0,
        level: int = 6,
        prefix: str = "brow_",
        ext: str = ".Png",
        start: int = 0,
        frames: Optional[int] = None,
        export_timestamps: bool = False,
        export_metadata: bool = False,
        progress: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> ExtractStats:
        mode = QualityMode(mode)
        if mode is QualityMode.REFERENCE and not self.meta.has_processing:
            raise ValueError("reference mode requires a .footage sidecar")
        if self.meta.width == 0 or self.meta.height == 0:
            raise ValueError("unknown geometry; provide a .footage sidecar")

        # Resolve transform defaults ONCE so native and fallback paths
        # always produce identical pixels for the same call (audit #13).
        if mode is QualityMode.RAW:
            brightness = contrast = 0.0
            gamma = 1.0
        elif mode is QualityMode.CUSTOM:
            brightness = brightness if brightness is not None else 0.0
            contrast = contrast if contrast is not None else 0.0
            gamma = gamma if gamma is not None else 1.0
        else:  # REFERENCE
            brightness = self.meta.brightness
            contrast = self.meta.contrast
            gamma = self.meta.gamma

        lib = load_library()
        if lib is not None:
            return self._run_native(
                lib,
                out_dir,
                mode,
                brightness,
                contrast,
                gamma,
                bit_depth,
                channels,
                fmt,
                jpeg_quality,
                backend,
                jobs,
                level,
                prefix,
                ext,
                start,
                frames,
                export_timestamps,
                export_metadata,
                progress,
                should_cancel,
            )
        return self._run_fallback(
            out_dir,
            mode,
            brightness,
            contrast,
            gamma,
            bit_depth,
            channels,
            backend,
            fmt,
            jpeg_quality,
            jobs,
            prefix,
            ext,
            start,
            frames,
            export_timestamps,
            export_metadata,
            progress,
            should_cancel,
        )

    # ------------------------------------------------------------------ #
    def _run_native(
        self,
        lib,
        out_dir,
        mode,
        brightness,
        contrast,
        gamma,
        bit_depth,
        channels,
        fmt,
        jpeg_quality,
        backend,
        jobs,
        level,
        prefix,
        ext,
        start,
        frames,
        export_timestamps,
        export_metadata,
        progress,
        should_cancel,
    ) -> ExtractStats:
        p = OpngxParams()
        p.bin_path = self.meta.bin_path.encode()
        p.footage_path = (self.meta.footage_path or "").encode() or None
        p.width = self.meta.width
        p.height = self.meta.height
        p.num_frames = -1
        p.frame_stride = -1
        p.mode = {"reference": 0, "raw": 1, "custom": 2}[mode.value]
        p.brightness = brightness
        p.contrast = contrast
        p.gamma = gamma
        p.bit_depth = bit_depth
        p.channels = channels
        p.format = {"png": 0, "bmp": 1, "tif": 2, "tiff": 2,
                    "jpg": 3, "jpeg": 3}.get(str(fmt).lower(), 0)
        p.jpeg_quality = jpeg_quality
        if p.format != 0:
            p.bit_depth = min(p.bit_depth, 8)   # 16-bit container is PNG-only
        p.out_dir = str(out_dir).encode()
        p.prefix = prefix.encode()
        p.ext = ("" if (ext == ".Png" and str(fmt).lower() != "png")
                 else ext.encode())
        p.jobs = jobs or os.cpu_count() or 1
        p.level = level
        p.backend = {"auto": BACKEND_AUTO, "libdeflate": BACKEND_LIBDEFLATE,
                     "zlib": BACKEND_ZLIB}.get(backend, BACKEND_AUTO)
        p.export_timestamps = int(export_timestamps)
        p.export_metadata = int(export_metadata)
        p.verbose = 0

        err = ctypes.create_string_buffer(512)
        job = lib.opngx_job_create(ctypes.byref(p), err, len(err))
        if not job:
            raise RuntimeError(f"engine rejected job: {err.value.decode()}")

        try:
            total = lib.opngx_progress_total(job)
            if start or frames is not None:
                total = lib.opngx__set_range(
                    job, start, -1 if frames is None else frames
                )
                if total < 0:
                    raise ValueError("invalid frame range")

            # Run the engine on a worker thread so this thread can stream
            # progress and forward cancellations. ctypes releases the GIL for
            # every native call, so concurrent polling is safe.
            import threading

            holder: dict[str, int] = {}

            def runner() -> None:
                holder["rc"] = lib.opngx_job_run(job)

            t = threading.Thread(target=runner, name="opngx-engine", daemon=True)
            t.start()
            try:
                while t.is_alive():
                    t.join(timeout=0.1)
                    if progress:
                        progress(
                            lib.opngx_progress_done(job),
                            lib.opngx_progress_total(job),
                        )
                    if should_cancel is not None and should_cancel():
                        lib.opngx_cancel(job)
            except BaseException:
                # never free the job while the engine thread still runs:
                # request a clean stop, wait, then re-raise on this thread
                lib.opngx_cancel(job)
                t.join(timeout=5.0)
                raise
            if progress:
                progress(lib.opngx_progress_done(job), total)

            rc = holder.get("rc", -1)
            stats_ptr = lib.opngx_job_stats(job)
            st = stats_ptr.contents if stats_ptr else None
            result = ExtractStats(
                frames_written=st.frames_written if st else 0,
                frames_total=st.frames_total if st else total,
                bytes_written=st.bytes_written if st else 0,
                seconds=st.seconds if st else 0.0,
                mib_per_s_in=st.mib_per_s_in if st else 0.0,
                frames_per_s=st.frames_per_s if st else 0.0,
                backend=(st.backend_used.decode().strip("\x00") if st else "native"),
            )
            if rc == 2:
                result.cancelled = True
            elif rc != 0:
                raise RuntimeError(
                    f"native run failed: {err.value.decode() or 'unknown'}"
                )
            return result
        finally:
            lib.opngx_job_free(job)

    # ------------------------------------------------------------------ #
    def _run_fallback(
        self,
        out_dir,
        mode,
        brightness,
        contrast,
        gamma,
        bit_depth,
        channels,
        backend,
        fmt,
        jpeg_quality,
        jobs,
        prefix,
        ext,
        start,
        frames,
        export_timestamps,
        export_metadata,
        progress,
        should_cancel,
    ) -> ExtractStats:
        from . import _fallback

        b = (
            brightness
            if brightness is not None
            else (self.meta.brightness if mode is QualityMode.REFERENCE else 0.0)
        )
        c = (
            contrast
            if contrast is not None
            else (self.meta.contrast if mode is QualityMode.REFERENCE else 0.0)
        )
        g = gamma if gamma is not None else self.meta.gamma
        if mode is QualityMode.RAW:
            b = c = 0.0
            g = 1.0

        n = frames if frames is not None else self.meta.capacity_frames - start
        n = max(0, min(n, self.meta.capacity_frames - start))
        t0 = time.perf_counter()

        done = [0]

        def cb(k: int) -> None:
            done[0] = k
            if progress:
                progress(k, n)

        res = _fallback.extract_frames(
            self.meta.bin_path,
            str(out_dir),
            self.meta.width,
            self.meta.height,
            n,
            self.meta.frame_stride,
            prefix,
            ext,
            b,
            c,
            g,
            bit_depth,
            jobs,
            progress=cb,
            cancelled=should_cancel,
        )

        dt = time.perf_counter() - t0
        written = res["frames_written"]
        if export_timestamps:
            ts = read_timestamps(self.meta.bin_path, self.meta, start, written)
            import csv

            with open(Path(out_dir) / f"{prefix}timestamps.csv", "w", newline="") as f:
                wcsv = csv.writer(f)
                wcsv.writerow(["frame_index", "timestamp_raw", "timestamp_hex"])
                for i, t in enumerate(ts):
                    wcsv.writerow([start + i, int(t), f"0x{int(t):016X}"])
        if export_metadata:
            meta = dict(self.meta.to_dict())
            meta.update(engine="python-fallback", frames_extracted=written)
            with open(Path(out_dir) / "metadata.json", "w") as f:
                json.dump(meta, f, indent=2)

        return ExtractStats(
            frames_written=written,
            frames_total=n,
            bytes_written=written * (8 + self.meta.pixels_per_frame),
            seconds=dt,
            mib_per_s_in=(written * (8 + self.meta.pixels_per_frame))
            / 1048576
            / max(dt, 1e-9),
            frames_per_s=written / max(dt, 1e-9),
            backend=res["backend"],
        )


def extract(bin_path: str | Path, out_dir: str | Path, **kwargs) -> ExtractStats:
    """Convenience one-shot wrapper: Extractor(bin).extract(out, ...)."""
    return Extractor(bin_path).extract(out_dir, **kwargs)
