"""Flicker - the spectrum of the illumination.

Takes the mean brightness of every frame and computes its power spectrum
(Welch, timed by the frame timestamps). Mains-powered lamps flicker at
twice the mains frequency (100 / 120 Hz, aliased if the camera is slower),
LED drivers at their PWM frequency; this module finds those lines and how
strong they are, so you can tell illumination artefacts from real signal.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis import stats as st
from opngx.analysis.base import Column, Module, Param
from opngx.analysis.builtin.brownian import _spectral_peaks, _welch


class Flicker(Module):
    name = "flicker"
    title = "Flicker (illumination spectrum)"
    description = ("Power spectrum of the mean frame brightness: finds lamp / LED / mains flicker lines and "
                   "their strength.")
    version = "1.0"
    author = "opngx"
    params = [
        Param("segments", int, 8, "Welch segments (more = smoother, coarser)", min=1, max=1024),
        Param("peak_ratio", float, 8.0, "a line must exceed the local median by this factor", min=2.0, max=1000.0),
    ]
    columns = [
        Column("mean", "mean brightness of the frame", "DN"),
        Column("deviation_pct", "difference from the run mean", "%"),
    ]
    plot = ("deviation_pct",)
    table_plots = {"spectrum": {"x": "freq_hz", "y": ["power"], "log": True}}

    def process(self, frames, ctx):
        mean, _std = st.mean_std(st.histograms(frames))
        return {"mean": mean}

    def finish(self, table, ctx):
        m = table["mean"].astype(np.float64)
        mu = float(m.mean()) if len(m) else 0.0
        table["deviation_pct"] = 100.0 * (m - mu) / mu if mu else np.zeros_like(m)
        t = table["time_s"]
        if len(m) < 32 or len(t) < 2:
            return table
        dt = float(np.median(np.diff(t)))
        if dt <= 0:
            return table
        fs = 1.0 / dt
        f, p = _welch(m - mu, fs, ctx.params["segments"])
        if not len(f):
            return table
        ctx.tables["spectrum"] = {"freq_hz": f, "power": p}
        ctx.table_units["spectrum"] = {"freq_hz": "Hz", "power": "DN²/Hz"}
        _mask, lines = _spectral_peaks(f, p, ratio=ctx.params["peak_ratio"])
        df = f[1] - f[0] if len(f) > 1 else 0.0
        out = []
        for fr, ratio in lines:
            i = int(round(fr / df)) if df else 0
            amp = float(np.sqrt(2 * p[i] * df * 1.5)) if df else 0.0  # Hann ENBW 1.5 bins
            out.append({"freq_hz": round(fr, 3), "ratio": round(ratio, 1),
                        "amplitude_pct": round(100 * amp / mu, 3) if mu else None})
        ctx.summary.update(sample_rate_hz=fs, rms_pct=float(np.std(table["deviation_pct"])),
                           lines=out, dominant_hz=(max(out, key=lambda d: d["ratio"])["freq_hz"] if out else None))
        return table
