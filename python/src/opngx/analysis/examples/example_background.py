"""Background subtraction - an opngx sample module using begin().

Builds a static background (the per-pixel median of frames sampled from
the whole recording) once, then reports for every frame how much it
deviates from that background: the residual's standard deviation and its
largest positive excursion (e.g. a particle on a still scene).

Shows: begin() with ctx.sample(n) and ctx.state, parameters with choices.
"""

import numpy as np

from opngx.analysis import Column, Module, Param


class ExampleBackground(Module):
    name = "example_background"
    title = "Example: background subtraction"
    description = "Residual after removing a median background."
    version = "1.0"
    author = "opngx sample"
    params = [
        Param("samples", int, 64, "frames sampled to build the background", min=3, max=1000),
        Param("statistic", str, "median", "how the background is formed", choices=("median", "mean")),
    ]
    columns = [
        Column("residual_std", "std of (frame - background)", "DN"),
        Column("residual_max", "largest (frame - background)", "DN"),
    ]
    plot = ("residual_std", "residual_max")

    def begin(self, ctx):
        s = ctx.sample(ctx.params["samples"]).astype(np.float32)
        bg = np.median(s, axis=0) if ctx.params["statistic"] == "median" else s.mean(axis=0)
        ctx.state["background"] = bg        # shared read-only by every batch

    def process(self, frames, ctx):
        r = frames.astype(np.float32) - ctx.state["background"]
        k = len(r)
        r = r.reshape(k, -1)
        return {"residual_std": r.std(axis=1), "residual_max": r.max(axis=1)}
