"""Videos as an analysis source (v2.2).

The analysis runner reads frames from a memory-mapped recording. A video is
decoded once, with the same ffmpeg the studio bundles, into a temporary file
of that layout, holding only the frames being analysed, so every module runs
on it unchanged.

What a video cannot give back:
- the camera clock. Time comes from a frame rate: the camera rate opngx
  writes into the videos it exports, else the container rate (the PLAYBACK
  rate, usually not the camera's), or the one you pass.
- exact pixels, unless the codec is lossless (FFV1, GIF of 8-bit grey,
  PNG/raw video). Lossy codecs change pixel values, so a .bin stays the
  right source for measurements.

Colour videos are analysed as luma (ffmpeg's grey conversion).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

VIDEO_EXTS = (".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".gif", ".mpg", ".mpeg", ".wmv", ".mxf")
LOSSLESS_CODECS = ("ffv1", "rawvideo", "png", "apng", "gif", "utvideo", "huffyuv", "ffvhuff", "qtrle", "zlib")


def is_video(path) -> bool:
    return str(path).lower().endswith(VIDEO_EXTS)


@dataclass
class VideoInfo:
    path: str
    width: int  # the picture, without the padding row/column of odd crops
    height: int
    coded_width: int  # as stored in the file
    coded_height: int
    frames: int
    container_fps: float
    camera_fps: Optional[float]  # from opngx's export tag, if any
    codec: str
    start_time: float = 0.0
    tags: dict = field(default_factory=dict)  # opngx export tag, parsed
    pts: list = field(default_factory=list)  # presentation time of each frame, in time_base units, sorted
    time_base: float = 0.0  # seconds per pts unit

    @property
    def lossless(self) -> bool:
        return self.codec.lower() in LOSSLESS_CODECS

    @property
    def fps(self) -> float:
        """The frame rate the time axis uses by default."""
        return self.camera_fps or self.container_fps


def _ffmpeg() -> str:
    from .video import resolve_ffmpeg

    ff = resolve_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg was not found (bundled copy missing and not on PATH); it is needed to read videos")
    return ff


def _popen_kwargs() -> dict:
    from .video import _popen_kwargs as kw

    return kw()


def export_tag(camera_fps: float, width: int, height: int, start: int, stride: int = 1) -> str:
    """The comment opngx writes into the videos it exports, so analysing one
    later gets the camera's time axis and the true picture size back."""
    return f"opngx camera_fps={camera_fps:g} width={int(width)} height={int(height)} start={int(start)} stride={int(stride)}"


def probe_video(path: str) -> VideoInfo:
    path = str(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    ff = _ffmpeg()
    r = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], capture_output=True, **_popen_kwargs())
    txt = r.stderr.decode("utf-8", "replace")
    m = re.search(r"Stream #\d+:\d+[^\n]*?: Video: ([A-Za-z0-9_]+)([^\n]*)", txt)
    if not m:
        raise ValueError(f"no video stream in {os.path.basename(path)}")
    codec, rest = m.group(1), m.group(2)
    sz = re.search(r",\s*(\d+)x(\d+)[\s,\[]", rest + ",")
    if not sz:
        raise ValueError(f"cannot read the picture size of {os.path.basename(path)}")
    cw, chh = int(sz.group(1)), int(sz.group(2))
    fr = re.search(r"([\d.]+)\s*fps", rest) or re.search(r"([\d.]+)\s*tbr", rest)
    container_fps = float(fr.group(1)) if fr else 0.0
    st = re.search(r"start:\s*(-?[\d.]+)", txt)
    tags: dict = {}
    tm = re.search(r"comment\s*:\s*opngx([^\n]*)", txt, re.IGNORECASE)
    if tm:
        for k, v in re.findall(r"(\w+)=([^\s]+)", tm.group(1)):
            tags[k] = v

    def num(k, cast):
        try:
            return cast(tags[k])
        except (KeyError, ValueError):
            return None

    w, h = num("width", int) or cw, num("height", int) or chh
    if not (0 < w <= cw and 0 < h <= chh):  # a tag that does not fit: trust the file
        w, h = cw, chh
    # frame count without decoding: one framecrc line per packet
    r = subprocess.run([ff, "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "framecrc", "-"],
                       capture_output=True, **_popen_kwargs())
    pts: list = []
    tb = 0.0
    for ln in r.stdout.decode("ascii", "replace").splitlines():
        if ln.startswith("#tb"):
            mt = re.search(r"(\d+)/(\d+)", ln)
            if mt and int(mt.group(2)):
                tb = int(mt.group(1)) / int(mt.group(2))
        elif ln and not ln.startswith("#"):
            parts = [x.strip() for x in ln.split(",")]
            try:
                pts.append(int(parts[2]))
            except (IndexError, ValueError):
                pts.append(None)
    frames = len(pts)
    if any(p is None for p in pts):
        pts, tb = [], 0.0
    else:
        pts.sort()  # packets come in decode order; frames in pts order
    if frames == 0:
        raise ValueError(f"{os.path.basename(path)} has no video frames")
    return VideoInfo(path=path, width=w, height=h, coded_width=cw, coded_height=chh, frames=frames,
                     container_fps=container_fps, camera_fps=num("camera_fps", float), codec=codec,
                     start_time=float(st.group(1)) if st else 0.0, tags=tags, pts=pts, time_base=tb)


def video_meta(path: str, fps: Optional[float] = None, info: Optional[VideoInfo] = None):
    """A FootageMetadata for a video: the runner, the crop checks and the
    results take it like a recording's. `fps` overrides the time axis."""
    from .footage import FootageMetadata

    info = info or probe_video(path)
    rate = float(fps) if fps and fps > 0 else float(info.fps or 0.0)
    m = FootageMetadata(bin_path=str(path), width=info.width, height=info.height, num_images=info.frames,
                        framerate=rate if rate > 0 else -1.0, camera_name="video",
                        file_size=os.path.getsize(path), frame_stride=8 + info.width * info.height,
                        capacity_frames=info.frames)
    m.extra = {"source": "video", "video_codec": info.codec, "video_lossless": str(info.lossless).lower(),
               "video_container_fps": f"{info.container_fps:g}",
               "time_axis_fps": f"{rate:g}" if rate > 0 else "",
               "time_axis_from": ("given" if fps and fps > 0 else
                                  "opngx export tag (camera rate)" if info.camera_fps else "container (playback) rate")}
    m.has_processing = False
    return m


def _vf(info_w: int, info_h: int, coded_w: int, coded_h: int, select: Optional[str]) -> list:
    f = []
    if select:
        f.append(f"select='{select}'")
    if (info_w, info_h) != (coded_w, coded_h):  # odd crops were padded right/bottom on export
        # grey FIRST: cropping 4:2:0 video rounds an odd size down to even
        f.append(f"format=gray,crop={info_w}:{info_h}:0:0")
    return ["-vf", ",".join(f)] if f else []


def decode_range(
    info: VideoInfo,
    start: int,
    stride: int,
    n: int,
    out_path: str,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> int:
    """Decode frames start, start+stride, ... (n of them) into `out_path` as
    consecutive records of 8 zero bytes + W*H grey bytes. Returns how many
    frames the video actually delivered."""
    ff = _ffmpeg()
    path = info.path
    sel = None
    if start > 0 or stride > 1:
        sel = f"gte(n\\,{start})*not(mod(n-{start}\\,{stride}))"
    cmd = [ff, "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0"]
    cmd += _vf(info.width, info.height, info.coded_width, info.coded_height, sel)
    cmd += ["-fps_mode", "passthrough", "-frames:v", str(int(n)), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    fsz = info.width * info.height
    hdr = bytes(8)
    got = 0
    errf = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, **_popen_kwargs())
    try:
        with open(out_path, "wb") as out:
            while got < n:
                buf = proc.stdout.read(fsz)
                if not buf or len(buf) < fsz:
                    break
                out.write(hdr)
                out.write(buf)
                got += 1
                if progress is not None and (got % 64 == 0 or got == n):
                    progress(got, n)
                if should_cancel is not None and should_cancel():
                    break
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if proc.stdout:
            proc.stdout.close()
    if got == 0:
        errf.seek(0)
        msg = errf.read().decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffmpeg decoded no frames from {os.path.basename(path)}" + (f": {msg[-400:]}" if msg else ""))
    return got


class VideoFrameReader:
    """FrameReader's interface for a video: one frame on demand (for the
    Analyze tab's preview), picked by its exact timestamp."""

    def __init__(self, path: str, info: Optional[VideoInfo] = None) -> None:
        self.path = str(path)
        self.info = info or probe_video(path)
        self.width, self.height = self.info.width, self.info.height
        self.frames = self.info.frames
        self._cache: dict[int, np.ndarray] = {}

    def raw(self, index: int) -> np.ndarray:
        index = max(0, min(int(index), self.frames - 1))
        a = self._cache.get(index)
        if a is not None:
            return a
        ff = _ffmpeg()
        cmd = [ff, "-nostdin", "-v", "error"]
        pts, tb = self.info.pts, self.info.time_base
        if pts and tb > 0 and len(pts) == self.frames:
            # seek to a second before the frame (fast), then pick it by its
            # exact timestamp: -copyts keeps the file's pts in the filter
            t = pts[index] * tb
            cmd += ["-ss", f"{max(0.0, t - 1.0):.6f}", "-copyts"]
            sel = f"eq(pts\\,{pts[index]})"
        else:
            sel = f"eq(n\\,{index})"  # exact, decodes from the start
        cmd += ["-i", self.path, "-map", "0:v:0"]
        cmd += _vf(self.width, self.height, self.info.coded_width, self.info.coded_height, sel)
        cmd += ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
        r = subprocess.run(cmd, capture_output=True, **_popen_kwargs())
        need = self.width * self.height
        if len(r.stdout) < need:
            raise ValueError(f"cannot decode frame {index} of {os.path.basename(self.path)}")
        a = np.frombuffer(r.stdout[:need], np.uint8).reshape(self.height, self.width)
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[index] = a
        return a

    def gray(self, index: int, crop=None, **_transform) -> np.ndarray:
        """The decoded frame; the curve was applied when the video was made."""
        px = self.raw(index)
        if crop:
            x, y, w, h = crop
            px = px[y : y + h, x : x + w]
        return np.ascontiguousarray(px)

    def close(self) -> None:
        self._cache.clear()
