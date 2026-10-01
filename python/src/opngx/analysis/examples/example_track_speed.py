"""Track speed - an opngx sample module that BUILDS ON another module.

Takes the trajectory from the built-in `motion_tracking` module and turns
it into velocity and speed, plus an extra table with the speed
distribution. Set `pixel_size_um` to get physical units.

Shows: `requires` (the runner runs motion_tracking in the same pass and
hands you its finished table in ctx.inputs), an empty process(), derived
columns in finish(), an extra table and its default plot.
"""

import numpy as np

from opngx.analysis import Column, Module, Param


class ExampleTrackSpeed(Module):
    name = "example_track_speed"
    title = "Example: track speed"
    description = "Velocity, speed and speed histogram from motion tracking."
    version = "1.0"
    author = "opngx sample"
    requires = ("motion_tracking",)
    params = [
        Param("pixel_size_um", float, 0.0, "um per pixel (0 = report in pixels)", min=0.0),
        Param("bins", int, 40, "bins of the speed histogram", min=5, max=500),
    ]
    columns = [
        Column("vx", "velocity x", "units/s"),
        Column("vy", "velocity y", "units/s"),
        Column("speed", "|velocity|", "units/s"),
    ]
    plot = ("speed",)
    table_plots = {"speed_hist": {"x": "speed", "y": ["count"], "log": False}}

    def process(self, frames, ctx):
        return {}                           # everything happens in finish()

    def finish(self, table, ctx):
        tr = ctx.inputs["motion_tracking"]
        ok = tr["found"].astype(bool)
        x = np.where(ok, tr["x"], np.nan).astype(np.float64)
        y = np.where(ok, tr["y"], np.nan).astype(np.float64)
        t = tr["time_s"].astype(np.float64)
        scale = ctx.params["pixel_size_um"] or 1.0
        if len(t) > 1:
            vx = np.gradient(x, t) * scale
            vy = np.gradient(y, t) * scale
        else:
            vx = vy = np.full(len(t), np.nan)
        sp = np.hypot(vx, vy)
        table.update(vx=vx, vy=vy, speed=sp)
        good = sp[np.isfinite(sp)]
        if len(good):
            cnt, edges = np.histogram(good, bins=ctx.params["bins"])
            ctx.tables["speed_hist"] = {"speed": 0.5 * (edges[:-1] + edges[1:]), "count": cnt}
            ctx.summary["mean_speed"] = float(good.mean())
            ctx.summary["unit"] = "um/s" if ctx.params["pixel_size_um"] else "px/s"
        return table
