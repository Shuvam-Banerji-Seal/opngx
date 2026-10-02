"""Video rendering — stream LUT-mapped frames straight into ffmpeg.

No intermediate files: decoded+transformed grayscale frames are piped to
ffmpeg's rawvideo input and encoded with one of the codecs in `CODECS`
(H.264, H.265, VP9, AV1, lossless FFV1, ProRes, MJPEG, GIF, or a GPU
H.264 encoder). The ffmpeg used is the one bundled with the studio, else
one on PATH.
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


def _popen_kwargs() -> dict:
    """No console window for ffmpeg when started from the windowed studio."""
    from ._proc import no_window

    return no_window()


# --------------------------------------------------------------------------
# Codecs (v2.1). Each entry: container, encoder, whether it is lossless for
# 8-bit grey input, the quality knob (name, default, range, better-is) and a
# function building the encoder arguments for a quality value.
# --------------------------------------------------------------------------
def _even_pad(cw: int, ch: int) -> list:
    # 4:2:0 codecs need even sizes: pad ONE black row/column, never trim
    return ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:black"] if (cw % 2 or ch % 2) else []


CODECS: dict[str, dict[str, Any]] = {
    "h264": dict(label="H.264 MP4 (plays everywhere)", ext=".mp4", encoder="libx264", lossless=False,
                 knob=("CRF", 18, 0, 51, "lower"),
                 args=lambda q, cw, ch, preset: _even_pad(cw, ch) + ["-c:v", "libx264", "-preset", preset, "-crf", str(q),
                                                                     "-pix_fmt", "yuv420p", "-movflags", "+faststart"]),
    "h265": dict(label="H.265/HEVC MP4 (about half the size of H.264)", ext=".mp4", encoder="libx265", lossless=False,
                 knob=("CRF", 22, 0, 51, "lower"),
                 args=lambda q, cw, ch, preset: _even_pad(cw, ch) + ["-c:v", "libx265", "-preset", preset, "-crf", str(q),
                                                                     "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
                                                                     "-x265-params", "log-level=error", "-movflags", "+faststart"]),
    "vp9": dict(label="VP9 WebM (open, for the web)", ext=".webm", encoder="libvpx-vp9", lossless=False,
                knob=("CRF", 30, 0, 63, "lower"),
                args=lambda q, cw, ch, preset: _even_pad(cw, ch) + ["-c:v", "libvpx-vp9", "-crf", str(q), "-b:v", "0",
                                                                    "-row-mt", "1", "-deadline", "good", "-cpu-used", "2",
                                                                    "-pix_fmt", "yuv420p"]),
    "av1": dict(label="AV1 MKV (smallest, slow to encode)", ext=".mkv", encoder="libaom-av1", lossless=False,
                knob=("CRF", 30, 0, 63, "lower"),
                args=lambda q, cw, ch, preset: _even_pad(cw, ch) + ["-c:v", "libaom-av1", "-crf", str(q), "-b:v", "0",
                                                                    "-cpu-used", "6", "-row-mt", "1", "-pix_fmt", "yuv420p"]),
    "ffv1": dict(label="FFV1 MKV (lossless, bit-exact archive)", ext=".mkv", encoder="ffv1", lossless=True,
                 knob=None,
                 args=lambda q, cw, ch, preset: ["-c:v", "ffv1", "-level", "3", "-g", "1", "-slices", "16",
                                                 "-slicecrc", "1", "-pix_fmt", "gray"]),
    "prores": dict(label="ProRes 422 HQ MOV (video editors)", ext=".mov", encoder="prores_ks", lossless=False,
                   knob=None,
                   args=lambda q, cw, ch, preset: _even_pad(cw, ch) + ["-c:v", "prores_ks", "-profile:v", "3",
                                                                       "-pix_fmt", "yuv422p10le", "-vendor", "apl0"]),
    "mjpeg": dict(label="Motion-JPEG AVI (frame-accurate, old software)", ext=".avi", encoder="mjpeg", lossless=False,
                  knob=("q", 2, 2, 31, "lower"),
                  args=lambda q, cw, ch, preset: ["-c:v", "mjpeg", "-q:v", str(q), "-pix_fmt", "yuvj444p"]),
    "gif": dict(label="Animated GIF (slides, chat; 256 greys)", ext=".gif", encoder="gif", lossless=True,
                knob=None,
                args=lambda q, cw, ch, preset: ["-c:v", "gif", "-pix_fmt", "gray", "-loop", "0"]),
    "h264_gpu": dict(label="H.264 MP4 on the GPU (NVIDIA / Intel / AMD)", ext=".mp4", encoder=None, lossless=False,
                     knob=("QP", 20, 0, 51, "lower"), args=None),
}

_GPU_ENCODERS = ("h264_nvenc", "h264_qsv", "h264_amf", "h264_mf")
_ENC_CACHE: dict = {}


def _encoder_works(enc: str) -> bool:
    """Encode 8 tiny frames with `enc` to /dev/null: listed encoders can
    still fail (no GPU, no driver), so test them for real, once."""
    if enc in _ENC_CACHE:
        return _ENC_CACHE[enc]
    ff = resolve_ffmpeg()
    ok = False
    if ff:
        try:
            r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "color=gray:s=256x256:d=0.3", "-frames:v", "8", "-c:v", enc, "-f", "null", "-"],
                               capture_output=True, timeout=30, **_popen_kwargs())
            ok = r.returncode == 0
        except Exception:  # noqa: BLE001
            ok = False
    _ENC_CACHE[enc] = ok
    return ok


def gpu_encoder() -> Optional[str]:
    """The first working hardware H.264 encoder, or None."""
    for enc in _GPU_ENCODERS:
        if _encoder_works(enc):
            return enc
    return None


def available_codecs() -> dict[str, bool]:
    """{codec key: usable with this ffmpeg}. Encoders are probed once."""
    out = {}
    for key, c in CODECS.items():
        out[key] = gpu_encoder() is not None if key == "h264_gpu" else _encoder_works(c["encoder"])
    return out


def codec_args(codec: str, quality: Optional[int], cw: int, ch: int, preset: str = "medium") -> list:
    c = CODECS[codec]
    if codec == "h264_gpu":
        enc = gpu_encoder()
        if not enc:
            raise RuntimeError("no working GPU H.264 encoder (NVENC / Quick Sync / AMF / MediaFoundation)")
        q = c["knob"][1] if quality is None else int(quality)
        rc = {"h264_nvenc": ["-rc", "constqp", "-qp", str(q)], "h264_qsv": ["-global_quality", str(q)],
              "h264_amf": ["-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q)], "h264_mf": ["-quality", "100"]}[enc]
        return _even_pad(cw, ch) + ["-c:v", enc] + rc + ["-pix_fmt", "yuv420p" if enc != "h264_qsv" else "nv12",
                                                       "-movflags", "+faststart"]
    q = None if c["knob"] is None else (c["knob"][1] if quality is None else int(quality))
    return c["args"](q, cw, ch, preset)


def decode_video_gray(path: str, width: int, height: int) -> "Any":
    """Decode a video back to (frames, height, width) uint8 grey with the
    same ffmpeg - used to prove the lossless codecs are bit-exact."""
    import numpy as np

    ff = resolve_ffmpeg()
    r = subprocess.run([ff, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True, check=True, **_popen_kwargs())
    a = np.frombuffer(r.stdout, np.uint8)
    return a.reshape(-1, height, width)


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
    crf: Optional[int] = None,
    preset: str = "medium",
    codec: str = "h264",
    crop: Optional[tuple[int, int, int, int]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    footage: Optional[str] = None,
) -> dict:
    """Render a range of frames into a video with the same verified
    transform as image extraction. `codec` is a key of CODECS (default
    H.264); `crf` is that codec's quality value (CRF, q or QP - see the
    codec's knob), None = its default. Returns stats."""
    if codec not in CODECS:
        raise ValueError(f"unknown codec '{codec}' (choose from {', '.join(CODECS)})")
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
    # 4:2:0 codecs need even dimensions; a hand-dragged crop is odd half the
    # time and ffmpeg refused it outright (cycle 23): codec_args pads ONE
    # black column/row rather than trimming, so every selected pixel is kept.
    cmd += codec_args(codec, crf, cw, ch, preset) + [str(out)]
    # stderr goes to a temp file: a PIPE nobody reads until the end blocks
    # ffmpeg (and so this writer) once it holds ~64 KB of messages
    import tempfile as _tf

    errf = _tf.TemporaryFile()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errf, **_popen_kwargs())

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
        pipe_broken = False
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
                    try:
                        for blob in pieces:
                            proc.stdin.write(blob)
                            written += 1
                    except (BrokenPipeError, OSError):
                        # ffmpeg exited early (bad output path/container,
                        # read-only folder...): stop feeding and report ITS
                        # message below instead of "Broken pipe" /
                        # "[Errno 22] Invalid argument"
                        pipe_broken = True
                if pipe_broken:
                    break
                if progress:
                    progress(min(written, n), n)
                if should_cancel is not None and should_cancel():
                    cancelled = True
                    break
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001 - the pipe may already be broken
            pass
        # no timeout: slow codecs (AV1, VP9) legitimately need minutes to
        # flush after the last frame; the old 60 s limit raised mid-flush
        rc = proc.wait()

    dt = time.perf_counter() - t0
    out_path = Path(out)
    cancelled = bool(should_cancel and should_cancel())
    if (
        rc != 0
        or not out_path.exists()
        or (out_path.stat().st_size == 0 and not cancelled)
    ):
        errf.seek(0)
        err = errf.read().decode(errors="replace")[-800:]
        raise RuntimeError(
            f"ffmpeg failed (rc={rc}, frames={written}): {err or 'no output produced'}"
        )
    return {
        "frames_written": written,
        "seconds": dt,
        "output": str(out),
        "cancelled": cancelled,
        "fps_effective": written / max(dt, 1e-9),
        "codec": codec,
        "lossless": bool(CODECS[codec]["lossless"]),
    }
