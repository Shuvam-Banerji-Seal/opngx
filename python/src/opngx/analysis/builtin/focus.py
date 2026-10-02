"""Focus / sharpness - how sharp every frame is.

Three standard focus measures, each larger when the image is sharper:
the variance of the Laplacian (fine detail), the Tenengrad (Sobel gradient
energy, robust to noise) and the normalised variance (contrast relative to
brightness). Watch them over time to catch the sample drifting out of the
focal plane (z-drift), vibration blur, or a refocus during the recording.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis.base import Column, Module, Param


def focus_measures(frames: np.ndarray) -> dict[str, np.ndarray]:
    f = frames.astype(np.float64)  # same precision as the C kernel
    k = len(f)
    flat = f.reshape(k, -1)
    mean = flat.mean(1)
    normvar = np.where(mean > 0, flat.var(1) / np.maximum(mean, 1e-9), 0.0)
    if f.shape[1] < 3 or f.shape[2] < 3:  # no interior: no gradients, but a variance
        z = np.zeros(k)
        return {"laplacian_var": z, "tenengrad": z, "norm_variance": normvar}
    c = f[:, 1:-1, 1:-1]
    lap = f[:, :-2, 1:-1] + f[:, 2:, 1:-1] + f[:, 1:-1, :-2] + f[:, 1:-1, 2:] - 4 * c
    gx = (f[:, :-2, 2:] + 2 * f[:, 1:-1, 2:] + f[:, 2:, 2:]) - (f[:, :-2, :-2] + 2 * f[:, 1:-1, :-2] + f[:, 2:, :-2])
    gy = (f[:, 2:, :-2] + 2 * f[:, 2:, 1:-1] + f[:, 2:, 2:]) - (f[:, :-2, :-2] + 2 * f[:, :-2, 1:-1] + f[:, :-2, 2:])
    return {
        "laplacian_var": lap.reshape(k, -1).var(1),
        "tenengrad": (gx * gx + gy * gy).reshape(k, -1).mean(1),
        "norm_variance": normvar,
    }


class Focus(Module):
    name = "focus"
    title = "Focus / sharpness"
    description = ("Variance of the Laplacian, Tenengrad and normalised variance of every frame: "
                   "detects defocus, z-drift and motion blur.")
    version = "1.0"
    author = "opngx"
    params = [
        Param("drop_warn_pct", float, 30.0,
              "warn when the sharpness falls this much below its median", min=1.0, max=99.0),
    ]
    columns = [
        Column("laplacian_var", "variance of the Laplacian (fine detail)", "DN²"),
        Column("tenengrad", "mean squared Sobel gradient", "DN²"),
        Column("norm_variance", "pixel variance / mean", "DN"),
        Column("relative", "Laplacian variance / its median over the run", ""),
    ]
    plot = ("relative",)

    def process(self, frames, ctx):
        from opngx.analysis import native

        r = native.focus(frames)  # C kernel (src/analysis.c, opngx_focus)
        return r if r is not None else focus_measures(frames)

    def finish(self, table, ctx):
        lv = table["laplacian_var"]
        med = float(np.median(lv)) if len(lv) else 0.0
        table["relative"] = lv / med if med > 0 else np.zeros_like(lv)
        if len(lv):
            rel = table["relative"]
            drop = ctx.params["drop_warn_pct"] / 100.0
            low = rel < (1 - drop)
            ctx.summary.update(median_laplacian_var=med, min_relative=float(rel.min()),
                               frames_out_of_focus=int(low.sum()),
                               sharpest_frame=int(table["frame"][int(np.argmax(lv))]))
            if low.any():
                ctx.summary["warnings"] = [f"{int(low.sum())} frame(s) are more than "
                                           f"{ctx.params['drop_warn_pct']:.0f}% less sharp than usual "
                                           "(defocus, z-drift or motion blur)"]
        return table
