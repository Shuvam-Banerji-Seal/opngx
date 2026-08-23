"""Timestamp analysis — surface the timing information hidden in every frame
header of an Optronis recording.

The u64 header is a camera-clock counter; at the verified operating point
(500 fps nominal, ~2000 ticks/frame) one tick is one microsecond. Gaps in
the delta sequence reveal dropped/irregular frames that pixel data alone
cannot show.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .footage import FootageMetadata, read_timestamps


def analyze_timestamps(
    bin_path: str | Path,
    meta: FootageMetadata,
    start: int = 0,
    count: int | None = None,
) -> dict:
    """Compute timing statistics for a frame range.

    Returns a JSON-friendly dict: counts, span, effective fps, delta stats,
    gap list (index + delta), non-monotonic count, inferred tick period.
    """
    import numpy as np

    ts = read_timestamps(bin_path, meta, start=start, count=count)
    n = int(ts.size)
    if n == 0:
        raise ValueError("empty frame range")

    deltas = np.diff(ts.astype(np.int64))
    med = float(np.median(deltas)) if n > 1 else 0.0

    # infer tick period from the sidecar's achieved framerate when available
    fps_real = meta.framerate if meta.framerate and meta.framerate > 0 else None
    tick_s: Optional[float] = None
    if fps_real and med > 0:
        tick_s = 1.0 / (fps_real * med)

    gap_mask = deltas > (med * 1.5) if med > 0 else deltas > 0
    gap_positions = np.flatnonzero(gap_mask)
    gaps = [
        {"frame": start + int(i) + 1, "delta_ticks": int(deltas[i])}
        for i in gap_positions[:20]
    ]
    nonmono = int(np.count_nonzero(deltas <= 0))

    span_ticks = float(int(ts[-1]) - int(ts[0]))
    out: dict = {
        "frames": n,
        "start_index": start,
        "first_tick": int(ts[0]),
        "last_tick": int(ts[-1]),
        "span_ticks": span_ticks,
        "delta_min": int(deltas.min()) if n > 1 else 0,
        "delta_median": med,
        "delta_max": int(deltas.max()) if n > 1 else 0,
        "tick_period_s": tick_s,
        "span_s": span_ticks * tick_s if tick_s else None,
        "effective_fps": (n - 1) / (span_ticks * tick_s)
        if tick_s and span_ticks > 0
        else None,
        "nominal_fps": fps_real,
        "gaps_gt_1p5x_median": int(gap_positions.size),
        "gap_examples": gaps,
        "non_monotonic": nonmono,
        "monotonic": nonmono == 0 and bool((deltas > 0).all()) if n > 1 else True,
    }
    return out
