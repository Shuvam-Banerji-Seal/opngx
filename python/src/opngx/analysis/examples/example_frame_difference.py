"""Frame difference - an opngx sample module with STATE between batches.

Measures how much each frame differs from the previous one ("motion
energy"): the mean absolute difference and the fraction of pixels that
changed by more than a tolerance. Useful to find when something moves,
flickers or the camera shakes.

Shows: `parallel = False` (batches arrive in order, so the last frame of
one batch can be kept for the next), instance state, and finish() adding
a summary.
"""

import numpy as np

from opngx.analysis import Column, Module, Param


class ExampleFrameDifference(Module):
    name = "example_frame_difference"
    title = "Example: frame difference"
    description = "Change between consecutive frames (motion energy)."
    version = "1.0"
    author = "opngx sample"
    parallel = False                        # needs the previous frame
    params = [
        Param("tolerance", int, 8, "a pixel 'changed' if it moved by more than this", min=0, max=255),
    ]
    columns = [
        Column("mean_abs_diff", "mean |frame - previous frame|", "DN"),
        Column("changed_frac", "fraction of pixels that changed", ""),
    ]
    plot = ("mean_abs_diff",)

    def begin(self, ctx):
        self.prev = None                    # last frame of the previous batch

    def process(self, frames, ctx):
        f = frames.astype(np.int16)
        prev = f[:1] if self.prev is None else self.prev[None]
        before = np.concatenate([prev, f[:-1]])   # each frame's predecessor
        d = np.abs(f - before)
        self.prev = f[-1]
        k = len(f)
        return {
            "mean_abs_diff": d.reshape(k, -1).mean(axis=1),
            "changed_frac": (d > ctx.params["tolerance"]).reshape(k, -1).mean(axis=1),
        }

    def finish(self, table, ctx):
        m = table["mean_abs_diff"][1:]      # frame 0 has no predecessor
        if len(m):
            ctx.summary["mean_motion_energy"] = float(m.mean())
            ctx.summary["busiest_frame"] = int(table["frame"][1 + int(np.argmax(m))])
        return table
