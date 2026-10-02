"""ROI statistics - brightness inside your own rectangles.

Give one or more rectangles in full-frame pixels, `x,y,w,h` separated by
semicolons, e.g. `10,10,40,40; 200,150,32,32`. For each region and frame:
mean, standard deviation, minimum and maximum. Typical uses: a reference
region next to the particle (background / illumination), several wells or
channels, a detector region.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis.base import Column, Module, Param


def parse_regions(text: str) -> list[tuple[int, int, int, int]]:
    out = []
    for part in str(text).replace("\n", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        vals = [int(float(v)) for v in part.replace(" ", ",").split(",") if v.strip()]
        if len(vals) != 4 or vals[2] <= 0 or vals[3] <= 0:
            raise ValueError(f"region '{part}' must be x,y,w,h with w,h > 0")
        out.append(tuple(vals))
    if not out:
        raise ValueError("give at least one region as x,y,w,h")
    if len(out) > 16:
        raise ValueError("at most 16 regions")
    return out


class RoiStats(Module):
    name = "roi_stats"
    title = "ROI statistics"
    description = "Mean, std, min and max inside up to 16 rectangles of your choice, frame by frame."
    version = "1.0"
    author = "opngx"
    params = [
        Param("regions", str, "0,0,32,32", "rectangles x,y,w,h in full-frame pixels, separated by ';'"),
    ]
    columns = [
        Column("r1_mean", "mean inside region 1 (r2_..., r3_... for more regions)", "DN"),
        Column("r1_std", "standard deviation inside region 1", "DN"),
        Column("r1_min", "darkest pixel in region 1", "DN"),
        Column("r1_max", "brightest pixel in region 1", "DN"),
    ]
    plot = ("r1_mean",)

    def begin(self, ctx):
        ox, oy = ctx.origin
        boxes = []
        for i, (x, y, w, h) in enumerate(parse_regions(ctx.params["regions"]), start=1):
            x0, y0 = max(0, x - ox), max(0, y - oy)
            x1, y1 = min(ctx.width, x - ox + w), min(ctx.height, y - oy + h)
            if x1 <= x0 or y1 <= y0:
                raise ValueError(f"region {i} ({x},{y},{w},{h}) lies outside the analysed area")
            boxes.append((i, x0, y0, x1, y1))
        ctx.state["boxes"] = boxes
        ctx.summary["regions"] = [f"r{i}: x {x0 + ox}..{x1 + ox - 1}, y {y0 + oy}..{y1 + oy - 1}"
                                  for i, x0, y0, x1, y1 in boxes]

    def process(self, frames, ctx):
        out = {}
        k = len(frames)
        for i, x0, y0, x1, y1 in ctx.state["boxes"]:
            r = frames[:, y0:y1, x0:x1].reshape(k, -1)
            rf = r.astype(np.float64)
            out[f"r{i}_mean"] = rf.mean(1)
            out[f"r{i}_std"] = rf.std(1)
            out[f"r{i}_min"] = r.min(1).astype(np.int32)
            out[f"r{i}_max"] = r.max(1).astype(np.int32)
        return out
