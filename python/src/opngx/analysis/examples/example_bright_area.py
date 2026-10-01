"""Bright area - an opngx sample module (the simplest kind).

Counts the pixels above a threshold in every frame and reports the
intensity-weighted centre of those pixels. Shows: params, columns, a
frame overlay, and a vectorised process() over a BATCH of frames.

This file was copied into your modules folder by opngx. Edit it freely:
the original stays inside the app, and opngx never overwrites your copy.
"""

import numpy as np

from opngx.analysis import Column, Module, Param


class ExampleBrightArea(Module):
    name = "example_bright_area"
    title = "Example: bright area"
    description = "Pixels above a threshold and their weighted centre."
    version = "1.0"
    author = "opngx sample"
    params = [
        Param("threshold", int, 128, "pixels brighter than this count", min=0, max=255),
    ]
    columns = [
        Column("area_px", "pixels above the threshold", "px"),
        Column("cx", "weighted centre x (full-frame pixels)", "px"),
        Column("cy", "weighted centre y (full-frame pixels)", "px"),
    ]
    plot = ("area_px",)
    trajectory = True                       # offer an x-y plot of cx/cy
    overlay = {"x": "cx", "y": "cy"}        # draw the centre on the frame

    def process(self, frames, ctx):
        # frames: (k, h, w) uint8, already cropped to the analysed region
        k, h, w = frames.shape
        f = frames.astype(np.float32)
        wgt = np.where(f > ctx.params["threshold"], f, 0.0)
        tot = wgt.sum(axis=(1, 2))
        yy = np.arange(h, dtype=np.float32)
        xx = np.arange(w, dtype=np.float32)
        safe = np.where(tot > 0, tot, 1.0)
        cx = (wgt.sum(axis=1) * xx).sum(axis=1) / safe
        cy = (wgt.sum(axis=2) * yy).sum(axis=1) / safe
        ox, oy = ctx.origin                 # crop offset -> full-frame coords
        return {
            "area_px": (wgt > 0).sum(axis=(1, 2)),
            "cx": np.where(tot > 0, cx + ox, np.nan),
            "cy": np.where(tot > 0, cy + oy, np.nan),
        }
