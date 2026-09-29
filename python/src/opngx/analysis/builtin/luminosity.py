"""Luminosity over time — how bright each frame (or its crop) is.

Useful for laser power drift, flicker, illumination stability, and as the
simplest possible example of a module: every statistic is one vectorised
reduction over the batch.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis import stats as st
from opngx.analysis.base import Column, Module, Param


class Luminosity(Module):
    name = "luminosity"
    title = "Luminosity over time"
    description = (
        "Mean, spread, extremes and integrated intensity of every frame "
        "(or of the crop), plus the fraction of pixels at or above a "
        "saturation level."
    )
    version = "1.0"
    author = "opngx"
    params = [
        Param("saturation", int, 255, "a pixel at or above this value counts as saturated", min=1, max=255),
        Param("above", int, 0, "also report the fraction of pixels above this value (0 = off)", min=0, max=255),
    ]
    columns = [
        Column("mean", "mean pixel value", "DN"),
        Column("std", "standard deviation of pixel values", "DN"),
        Column("min", "darkest pixel", "DN"),
        Column("max", "brightest pixel", "DN"),
        Column("integrated", "sum of all pixel values", "DN"),
        Column("saturated_frac", "fraction of pixels >= saturation", ""),
        Column("above_frac", "fraction of pixels > `above` (when enabled)", ""),
    ]
    plot = ("mean", "max")

    def process(self, frames, ctx):
        # one histogram per frame gives every statistic exactly
        h = st.histograms(frames)
        mean, std = st.mean_std(h)
        lo, hi = st.extremes(h)
        out = {
            "mean": mean,
            "std": std,
            "min": lo,
            "max": hi,
            "integrated": (h @ np.arange(256, dtype=np.int64)),
            "saturated_frac": st.fraction_at_or_above(h, ctx.params["saturation"]),
        }
        if ctx.params["above"] > 0:
            out["above_frac"] = st.fraction_at_or_above(h, ctx.params["above"] + 1)
        return out

    def finish(self, table, ctx):
        m = table["mean"]
        if len(m):
            ctx.summary.update(
                mean=float(m.mean()),
                mean_min=float(m.min()),
                mean_max=float(m.max()),
                drift_pct=float(100.0 * (m[-1] - m[0]) / m[0]) if m[0] else 0.0,
                flicker_rms_pct=float(100.0 * m.std() / m.mean()) if m.mean() else 0.0,
            )
        return table
