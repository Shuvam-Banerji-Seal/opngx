"""Contrast over time — how much structure each frame (or crop) shows.

Three standard measures, so the right one is available for the question:
* Michelson   (Imax − Imin) / (Imax + Imin) — fringes / periodic patterns;
  `robust` uses the 1st/99th (nearest-rank) percentiles instead of the extremes, so a
  single hot or dead pixel cannot dominate.
* RMS         std / mean — general image contrast.
* Weber       (Imax − Imean) / Imean — a small bright feature on a
  uniform background.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis import stats as st
from opngx.analysis.base import Column, Module, Param


class Contrast(Module):
    name = "contrast"
    title = "Contrast over time"
    description = "Michelson, RMS and Weber contrast of every frame (or of the crop)."
    version = "1.0"
    author = "opngx"
    params = [
        Param("robust", bool, True, "use 1st/99th percentiles instead of min/max for Michelson"),
    ]
    columns = [
        Column("michelson", "(Imax − Imin) / (Imax + Imin)", ""),
        Column("rms", "std / mean", ""),
        Column("weber", "(Imax − Imean) / Imean", ""),
        Column("i_low", "low level used (min or 1st percentile)", "DN"),
        Column("i_high", "high level used (max or 99th percentile)", "DN"),
    ]
    plot = ("michelson", "rms")

    def process(self, frames, ctx):
        h = st.histograms(frames)
        mean, std = st.mean_std(h)
        mn, mx = st.extremes(h)
        if ctx.params["robust"]:
            lo, hi = st.percentile(h, 1), st.percentile(h, 99)
        else:
            lo, hi = mn.astype(np.float64), mx.astype(np.float64)
        den = hi + lo
        safe = np.where(den > 0, den, 1)
        safe_mean = np.where(mean > 0, mean, 1)
        return {
            "michelson": np.where(den > 0, (hi - lo) / safe, 0.0),
            "rms": np.where(mean > 0, std / safe_mean, 0.0),
            "weber": np.where(mean > 0, (mx - mean) / safe_mean, 0.0),
            "i_low": lo,
            "i_high": hi,
        }

    def finish(self, table, ctx):
        m = table["michelson"]
        if len(m):
            ctx.summary.update(
                michelson_mean=float(m.mean()),
                michelson_std=float(m.std()),
                rms_mean=float(table["rms"].mean()),
            )
        return table
