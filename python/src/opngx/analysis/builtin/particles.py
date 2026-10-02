"""Particles - count and size the blobs in every frame.

A pixel belongs to a blob when it is brighter than the threshold (or
darker, for dark particles on a bright background); touching pixels form
one blob (8- or 4-connected). Blobs smaller than `min_area` are ignored
(noise). Per frame: how many blobs, their total / mean / largest area and
where the largest one is. The labelling runs in C (src/analysis.c,
opngx_blobs); an identical numpy version is used without the engine.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis import native
from opngx.analysis import stats as st
from opngx.analysis.base import Column, Module, Param


def _blobs_numpy(frames: np.ndarray, thr: int, dark: bool, min_area: int, conn8: bool) -> dict:
    """Reference implementation (same two-pass union-find as the C kernel)."""
    k, h, w = frames.shape
    res = {n: np.zeros(k) for n in ("total_area", "mean_area", "max_area")}
    res["cx"] = np.full(k, np.nan)
    res["cy"] = np.full(k, np.nan)
    res["count"] = np.zeros(k, np.int32)
    for f in range(k):
        on = frames[f] < thr if dark else frames[f] > thr
        lab = np.zeros((h, w), np.int64)
        par = [0]

        def find(a):
            while par[a] != a:
                par[a] = par[par[a]]
                a = par[a]
            return a

        nxt = 1
        for y in range(h):
            row = on[y]
            for x in np.flatnonzero(row):
                nb = []
                if x > 0 and lab[y, x - 1]:
                    nb.append(lab[y, x - 1])
                if y > 0 and lab[y - 1, x]:
                    nb.append(lab[y - 1, x])
                if conn8 and y > 0:
                    if x > 0 and lab[y - 1, x - 1]:
                        nb.append(lab[y - 1, x - 1])
                    if x + 1 < w and lab[y - 1, x + 1]:
                        nb.append(lab[y - 1, x + 1])
                if not nb:
                    par.append(nxt)
                    lab[y, x] = nxt
                    nxt += 1
                else:
                    m = min(nb)
                    lab[y, x] = m
                    for b in nb:
                        ra, rb = find(m), find(b)
                        if ra < rb:
                            par[rb] = ra
                        elif rb < ra:
                            par[ra] = rb
        if nxt == 1:
            continue
        roots = np.array([find(i) for i in range(nxt)])
        r = roots[lab]
        sel = lab > 0
        area = np.bincount(r[sel], minlength=nxt)
        ys, xs = np.nonzero(sel)
        sx = np.bincount(r[sel], weights=xs, minlength=nxt)
        sy = np.bincount(r[sel], weights=ys, minlength=nxt)
        ok = (np.arange(nxt) == roots) & (area >= max(1, min_area))
        ok[0] = False
        n = int(ok.sum())
        res["count"][f] = n
        if n:
            tot = int(area[ok].sum())
            idx = np.flatnonzero(ok)
            best = idx[np.argmax(area[idx])]  # first (lowest label) of the largest
            res["total_area"][f] = tot
            res["mean_area"][f] = tot / n
            res["max_area"][f] = area[best]
            res["cx"][f] = sx[best] / area[best]
            res["cy"][f] = sy[best] / area[best]
    return res


class Particles(Module):
    name = "particles"
    title = "Particles (blob count and size)"
    description = (
        "Counts the bright (or dark) blobs in every frame and measures their area; reports where "
        "the largest one is. For particle suspensions, debris, bubbles or spots."
    )
    version = "1.0"
    author = "opngx"
    params = [
        Param("threshold", int, 0, "pixel level separating particles from background (0 = automatic, Otsu)",
              min=0, max=255),
        Param("dark", bool, False, "particles are DARKER than the background"),
        Param("min_area", int, 4, "ignore blobs smaller than this (pixels)", min=1, max=1000000),
        Param("connectivity", int, 8, "8 = diagonal neighbours touch, 4 = only edges", choices=(4, 8)),
    ]
    columns = [
        Column("count", "number of blobs", ""),
        Column("total_area", "area of all blobs", "px"),
        Column("mean_area", "mean blob area", "px"),
        Column("max_area", "area of the largest blob", "px"),
        Column("largest_x", "centre of the largest blob (full-frame)", "px"),
        Column("largest_y", "centre of the largest blob (full-frame)", "px"),
        Column("threshold_used", "threshold applied", "DN"),
    ]
    plot = ("count", "mean_area")
    overlay = {"x": "largest_x", "y": "largest_y"}

    def begin(self, ctx):
        thr = int(ctx.params["threshold"])
        if thr == 0:  # Otsu on frames sampled across the whole range
            h = np.bincount(ctx.sample(32).reshape(-1), minlength=256).astype(np.float64)
            thr = st.otsu(h)
        ctx.state["thr"] = thr

    def process(self, frames, ctx):
        thr = ctx.state["thr"]
        args = (thr, ctx.params["dark"], ctx.params["min_area"], ctx.params["connectivity"] == 8)
        r = native.blobs(frames, *args)
        if r is None:
            r = _blobs_numpy(frames, *args)
        ox, oy = ctx.origin
        return {
            "count": r["count"].astype(np.int32),
            "total_area": r["total_area"],
            "mean_area": r["mean_area"],
            "max_area": r["max_area"],
            "largest_x": r["cx"] + ox,
            "largest_y": r["cy"] + oy,
            "threshold_used": np.full(len(frames), thr, np.int32),
        }

    def finish(self, table, ctx):
        c = table["count"]
        if len(c):
            ctx.summary.update(threshold=int(ctx.state["thr"]), mean_count=float(c.mean()),
                               max_count=int(c.max()), frames_with_particles=int((c > 0).sum()))
        return table
