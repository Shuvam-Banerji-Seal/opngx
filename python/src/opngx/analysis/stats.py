"""Fast per-frame statistics for 8-bit frames (v1.10).

One 256-bin histogram per frame gives mean, variance, extremes and any
percentile exactly, from a single integer pass — ~10x cheaper than float64
reductions plus np.percentile on 256x300 frames (measured: 24 ms vs 250 ms
for a 256-frame batch). Modules are free to use these helpers.
"""

from __future__ import annotations

import numpy as np

_V = np.arange(256, dtype=np.float64)


def histograms(frames: np.ndarray) -> np.ndarray:
    """(k, ...) uint8 -> (k, 256) int64 counts per frame."""
    k = len(frames)
    flat = frames.reshape(k, -1)
    if flat.dtype != np.uint8:
        raise TypeError("histograms() needs uint8 frames")
    from opngx.analysis import native

    h = native.hist256(flat)  # C kernel when available (releases the GIL)
    if h is not None:
        return h
    return np.stack([np.bincount(r, minlength=256) for r in flat]) if k else np.zeros((0, 256), np.int64)


def mean_std(h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = h.sum(1).astype(np.float64)
    mean = (h @ _V) / n
    var = np.maximum((h @ (_V * _V)) / n - mean * mean, 0.0)
    return mean, np.sqrt(var)


def extremes(h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nz = h > 0
    lo = nz.argmax(1)
    hi = 255 - nz[:, ::-1].argmax(1)
    return lo.astype(np.int32), hi.astype(np.int32)


def percentile(h: np.ndarray, q: float) -> np.ndarray:
    """Nearest-rank percentile (0..100) per frame, from histograms."""
    c = np.cumsum(h, axis=1)
    n = c[:, -1:]
    rank = np.ceil(q / 100.0 * n).clip(1, None)
    return (c >= rank).argmax(1).astype(np.float64)


def fraction_at_or_above(h: np.ndarray, level: int) -> np.ndarray:
    level = int(np.clip(level, 0, 256))
    return h[:, level:].sum(1) / h.sum(1)


def otsu(h: np.ndarray) -> int:
    """Otsu's threshold of a 256-bin histogram: the level that best separates
    two classes (maximum between-class variance). Pixels > level are 'on'."""
    h = np.asarray(h, np.float64)
    tot = h.sum()
    if tot <= 0:
        return 128
    p = h / tot
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        sb = (mu_t * omega - mu) ** 2 / (omega * (1 - omega))
    sb[~np.isfinite(sb)] = -1
    return int(np.argmax(sb))
