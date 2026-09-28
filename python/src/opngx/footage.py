"""Footage metadata model and .footage XML parsing."""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Frame header: 8-byte little-endian timestamp precedes every frame's pixels.
FRAME_HEADER_BYTES = 8


@dataclass
class FootageMetadata:
    """Parsed view of an Optronis TimeViewer footage pair (.bin + .footage)."""

    bin_path: str = ""
    footage_path: Optional[str] = None
    width: int = 0
    height: int = 0
    num_images: int = -1  # from XML; -1 unknown
    framerate: float = -1.0
    framerate_real: float = -1.0  # achieved capture rate (vendor tag)
    exposure_us: float = -1.0
    time_marker_reference: int = -1
    camera_name: str = ""
    brightness: float = 0.0
    contrast: float = 0.0
    gamma: float = 1.0
    has_processing: bool = False
    file_size: int = 0
    frame_stride: int = 0  # bytes per frame incl. timestamp header
    capacity_frames: int = 0  # frames that fit in the file
    verified_operating_point: bool = False  # B=49 C=18 G=1 (pixel-exact proven)
    extra: dict[str, str] = field(default_factory=dict)  # every other scalar tag
    # O(1) clock sample from the first/last frame headers (ticks; the
    # verified operating point uses 1 µs ticks — hence the _us suffix)
    first_tick: int = -1
    last_tick: int = -1
    span_s: float | None = None
    effective_fps_us: float | None = None
    frames_match: bool | None = None  # XML NumberOfImages == frames on disk

    @property
    def pixels_per_frame(self) -> int:
        return self.width * self.height

    def to_dict(self) -> dict:
        return asdict(self)


def _collect_extras(root) -> dict[str, str]:
    """Every scalar tag as 'Path/To/Tag' → text (deduped, known top-level
    scalars kept under their bare tag so old consumers keep working)."""
    known_top = {
        "ResolutionX",
        "ResolutionY",
        "NumberOfImages",
        "Framerate",
        "Exposure",
        "TimeMarkerReference",
        "Brightness",
        "Contrast",
        "Gamma",
    }
    out: dict[str, str] = {}

    def walk(elem, prefix: str) -> None:
        for child in elem:
            path = f"{prefix}{child.tag}"
            if len(child) == 0 and child.text and child.text.strip():
                if "/" not in path and child.tag in known_top:
                    continue
                key = child.tag if "/" not in path else path
                out.setdefault(key, child.text.strip())
            walk(child, path + "/")

    walk(root, "")
    return out


def _num(text: Optional[str], default: float) -> float:
    """Parse a vendor number. TimeViewer on a decimal-comma Windows locale
    writes "1,5" — float() raised on that and the whole probe failed, while
    the C engine read it as 1 (cycle 23). Both now read 1.5."""
    if text is None:
        return default
    s = text.strip().replace(",", ".")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _sidecar_for(bin_path: Path) -> Optional[Path]:
    cand = bin_path.with_suffix(".footage")
    return cand if cand.exists() else None


def probe(
    bin_path: str | Path, footage_path: str | Path | None = None
) -> FootageMetadata:
    """Inspect a .bin (and its optional .footage sidecar) without extracting."""
    bp = Path(bin_path)
    if not bp.exists():
        raise FileNotFoundError(f"no such bin: {bp}")
    fp = Path(footage_path) if footage_path else _sidecar_for(bp)

    meta = FootageMetadata(bin_path=str(bp), footage_path=str(fp) if fp else None)
    meta.file_size = bp.stat().st_size

    if fp is not None:
        root = ET.parse(fp).getroot()
        text = lambda xp: root.findtext(xp, default=None)  # noqa: E731

        meta.width = int(text(".//ResolutionX") or 0)
        meta.height = int(text(".//ResolutionY") or 0)
        ni = text(".//NumberOfImages")
        meta.num_images = int(ni) if ni else -1
        meta.framerate = _num(text(".//Framerate"), -1.0)
        meta.framerate_real = _num(text(".//FramerateReal"), -1.0)
        meta.exposure_us = _num(text(".//Exposure"), -1.0)
        tmr = text(".//TimeMarkerReference")
        meta.time_marker_reference = int(tmr) if tmr else -1
        name = text(".//Camera/Name") or ""
        meta.camera_name = name.strip()

        proc = root.find("SettingsProcessing")
        if proc is not None:
            meta.has_processing = True
            meta.brightness = _num(proc.findtext("Brightness"), 0.0)
            meta.contrast = _num(proc.findtext("Contrast"), 0.0)
            g = _num(proc.findtext("Gamma"), 1.0)
            meta.gamma = g if g > 0 else 1.0  # same guard as footage.c

        # capture every remaining scalar so nothing the vendor stored is lost
        known = {
            "ResolutionX",
            "ResolutionY",
            "NumberOfImages",
            "Framerate",
            "Exposure",
            "TimeMarkerReference",
            "Brightness",
            "Contrast",
            "Gamma",
        }
        for elem in root.iter():
            if len(elem) == 0 and elem.text and elem.text.strip():
                tag = elem.tag
                if tag in known:
                    continue
                meta.extra[tag] = elem.text.strip()

    if meta.width and meta.height:
        meta.frame_stride = FRAME_HEADER_BYTES + meta.pixels_per_frame
        meta.capacity_frames = meta.file_size // meta.frame_stride
        meta.verified_operating_point = (
            meta.brightness == 49.0 and meta.contrast == 18.0 and meta.gamma == 1.0
        )
        if meta.num_images > 0:
            meta.frames_match = meta.num_images == meta.capacity_frames
        # O(1) clock sample: read just the first and last frame headers
        try:
            with open(bp, "rb") as fh:
                meta.first_tick = int.from_bytes(fh.read(8), "little")
                if meta.capacity_frames > 1:
                    fh.seek((meta.capacity_frames - 1) * meta.frame_stride)
                    meta.last_tick = int.from_bytes(fh.read(8), "little")
            if meta.last_tick >= meta.first_tick > 0 and meta.capacity_frames > 1:
                ticks = meta.last_tick - meta.first_tick
                meta.span_s = ticks / 1e6  # ticks are µs at the verified point
                meta.effective_fps_us = (meta.capacity_frames - 1) / meta.span_s
        except OSError:
            pass
    return meta


def read_timestamps(
    bin_path: str | Path,
    meta: FootageMetadata,
    start: int = 0,
    count: int | None = None,
) -> "np.ndarray":  # noqa: F821
    """Read per-frame u64 LE timestamps without decoding pixels."""
    import numpy as np

    n = count if count is not None else meta.capacity_frames - start
    n = max(0, min(n, meta.capacity_frames - start))
    out = np.empty(n, dtype=np.uint64)
    stride = meta.frame_stride
    if stride <= 8:
        raise ValueError("bad frame stride")
    with open(bin_path, "rb") as f:
        f.seek(start * stride)
        chunk = 65536
        done = 0
        while done < n:
            take = min(chunk, n - done)
            buf = f.read(take * stride)
            if len(buf) < take * stride:
                raise IOError("unexpected EOF reading timestamps")
            # timestamps live in the first 8 bytes of every frame; use a
            # strided view instead of copying per-frame slices
            out[done : done + take] = np.ndarray(
                (take,), dtype="<u8", buffer=buf, strides=(stride,)
            )
            done += take
    return out
