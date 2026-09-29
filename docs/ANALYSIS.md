# Analysis modules (v1.10)

opngx can turn a recording into **time-series data** as well as images.
An *analysis module* reads frames and produces one row per frame; the
first one, **motion tracking**, follows the bright spot or ring in the
frame and writes its trajectory. Modules are plain Python files. The
studio lets you switch them in and out, run them, look at the result, export
the data file, and write your own.

- [Using modules](#using-modules) (studio, command line, Python)
- [Built-in modules](#built-in-modules)
- [The data file](#the-data-file)
- [Writing a module](#writing-a-module)

---

## Using modules

### In the studio

**Analyze** tab:

1. Load a recording in **Extract** (or choose a batch folder).
2. Tick the modules you want switched in. Select one to edit its
   parameters; values are remembered.
3. Choose the scope: the loaded recording, or every recording in the batch
   folder. Choose the frame range (start, count, every Nth frame), and whether to
   analyse only the **crop** (region of interest). Choose the input: raw sensor
   values (right for measurement) or the display curve (B/C/G).
4. **Run selected** runs the highlighted module. **Run all ticked** runs every
   ticked module in *one* pass over the frames.
5. Inspect the result:
   - the frame with the tracked position, ring and trajectory drawn on it;
     scrub through it with the slider;
   - a plot, either **vs time** (two quantities on independent axes) or
     **trajectory (x–y)** at equal aspect. Hover to read values; click to
     jump to that frame;
   - the **Data** table, the **Summary**, and the **Log**.
6. **Export data file…** writes CSV, JSON, NPZ or TSV. **Export all…**
   writes every result. With *also write data files* ticked, results are
   saved automatically to `<output>/<recording>/ANALYSIS/<module>.<fmt>`,
   next to the extracted `PNG/` folder.

**Module editor** tab: *New module…* (starts from a working template),
*Duplicate as my module* (copy a built-in and change it),
*Validate* (F5: load and dry-run on synthetic frames), and *Test on
recording* (F6: the first 500 frames of the loaded recording). *Save & use*
saves the module and it appears in the Analyze tab. Errors are shown with
the offending line highlighted.

### Command line

```bash
opngx modules                               # list (built-in + yours)
opngx modules show motion_tracking          # parameters and columns
opngx modules template my_probe             # new module from the template
opngx modules validate ~/.config/opngx/modules/my_probe.py
opngx modules dir                           # where your modules live

# one recording, one module -> one file
opngx analyze rec.bin -m motion_tracking -o trajectory.csv
opngx analyze rec.bin -m motion_tracking -p method=circle -p pixel_size_um=1.2 \
      --start 1000 --frames 5000 --stride 2 --crop 100,20,120,120 -o traj.json

# several modules, a whole batch folder -> <out>/<recording>/ANALYSIS/<module>.csv
opngx analyze Footages/ --batch -m motion_tracking -m luminosity \
      -p motion_tracking.window=40 -o Results/ --format csv
```

`-p KEY=VALUE` sets a parameter. With several modules, write
`-p MODULE.KEY=VALUE`. A misspelt parameter is an error, never silently
ignored.

### Python

```python
import opngx.analysis as oa

run = oa.analyze("rec.bin", ["motion_tracking", "luminosity"],
                 params={"motion_tracking": {"method": "circle"}},
                 start=0, count=None, stride=1, crop=None, source="raw")
traj = run["motion_tracking"]
traj.columns["x"], traj.columns["y"], traj.columns["time_s"]   # numpy arrays
traj.summary                   # method used, mean/std, path length, radius, …
traj.save("trajectory.csv")    # .csv .json .npz .tsv
back = oa.load_result("trajectory.npz")
```

---

## Built-in modules

### `motion_tracking`: trajectory of a spot or ring

Each frame is processed in three steps. All three are vectorised over batches of frames, and
batches run in parallel.

1. **Locate.** Find the brightest `locate_block`² block. Block sums ignore
   single hot pixels. The block grid is aligned to full-frame coordinates, so
   cropping never moves the search.
2. **Window.** Take a `window`² region around it and threshold it at
   `median + threshold·(peak − median)`, which adapts to exposure frame by frame.
3. **Refine** to sub-pixel precision with one of these methods:

   | `method` | for | how |
   |---|---|---|
   | `circle` | a sphere imaged as a bright **ring** (this project's footage) | circle fit to the above-threshold pixels, then (with `refine`) re-fitted to the rim's intensity **ridge** along 48 rays: the sub-pixel radius of peak intensity on each ray, prominence-weighted |
   | `centroid` | a solid **spot** (Gaussian laser point) | intensity-weighted centroid of (I − threshold)⁺ |
   | `peak` | anything | brightest pixel + 3-point parabolic interpolation |
   | `auto` *(default)* | — | decides **once** from frames sampled over the whole range: a dark centre inside the fitted circle means `circle`, otherwise `centroid`. The whole trajectory uses one estimator. |

The ridge fit exists because the real rings are brighter on one side. A fit
to the thresholded mask follows the rim's *thickness* and is pulled toward
the bright side. The ridge position doesn't depend on brightness.

**Measured accuracy** (synthetic ground truth rendered 5× supersampled, noise
σ = 3 DN, dark specks; the ring has a 12 px radius and a rim that's 57%
brighter at the bottom, like the footage):

| feature, method | bias (x, y) | RMS error |
|---|---|---|
| ring, `circle` (ridge-refined, default) | (−0.000, +0.025) px | **0.044 px** |
| ring, `circle` without `refine` | (+0.001, +0.222) px | 0.236 px |
| ring, `centroid` | (−0.002, +8.53) px | 8.53 px |
| spot, `centroid` (default for spots) | (−0.000, +0.001) px | **0.049 px** |

These figures are pinned by test AN-1. On this project's five 50,000-frame recordings the tracker
found the ring in 100% of frames. Radius scatter is 0.07 px, median
frame-to-frame step 0.11 px, and throughput is about 3,000–4,500 frames/s,
so a whole recording takes 11–17 s.

**Output columns:**
- `x`, `y`: centre in full-frame pixels (x = column, y = row, pixel centres at integers).
- `radius`: ring radius.
- `peak`: brightest value in the window.
- `area`: pixels above threshold.
- `found`: 1 if the frame was tracked, 0 if lost.
- `fit_rms`: residual of the circle fit.
- `vx`, `vy`, `speed`: velocity, by central differences on the camera clock.
- `disp`: distance from the first tracked position.
- `x_um`, `y_um`, `speed_um_s`: the same in µm, only with `pixel_size_um` > 0.

**Summary:** method used, found %, mean/std/range of x and y, path length,
net displacement, median step, mean speed, duration, and radius mean/std.

**Parameters:** `method`, `target` (bright/dark), `window`, `threshold`,
`min_pixels`, `locate_block`, `refine`, `pixel_size_um`.

### `luminosity`: brightness over time

Per frame: `mean`, `std`, `min`, `max`, `integrated`, `saturated_frac` (≥
`saturation`) and, optionally, `above_frac`. The summary gives drift % and
flicker RMS %. All statistics come from one exact 256-bin histogram per frame.

### `contrast`: contrast over time

Per frame:
- Michelson: (Imax − Imin)/(Imax + Imin). With `robust`, the 1st/99th
  nearest-rank percentiles replace the extremes, so one hot pixel cannot
  dominate.
- RMS: std/mean.
- Weber: (Imax − Imean)/Imean.

---

## The data file

Every result has these columns first:
- `frame`: absolute frame index.
- `timestamp_raw`: the camera clock from the frame header.
- `time_s`: seconds since the first analysed frame. It comes from the frame-header clock (µs ticks at the verified
  operating point); the nominal frame rate is used only if the clock isn't
  monotonic. `run.time_source` says which.

The module's own columns follow.

| format | contents |
|---|---|
| **CSV** | `# key: value` header lines (module, recording, params, summary, units), then a normal CSV table. Read it with `pandas.read_csv(path, comment="#")`. |
| **JSON** | `{"format": "opngx-analysis/1", "module", "params", "recording", "run", "summary", "columns": [{key, unit, help}], "data": {column: [...]}}` |
| **NPZ** | one array per column plus `_metadata` (the JSON above without `data`). `oa.load_result()` reads it back. |
| **TSV** | a bare table, for spreadsheets. |

---

## Writing a module

A module is a `.py` file in your modules folder. Find it with
`opngx modules dir`; it's usually `~/.config/opngx/modules`, or
`%APPDATA%\opngx\modules` on Windows. You can override it with
`OPNGX_MODULES_DIR`, and add more folders with `OPNGX_MODULES_PATH`.

```python
import numpy as np
from opngx.analysis import Column, Module, Param


class RingBrightness(Module):
    name = "ring_brightness"          # unique id: lowercase, digits, _
    title = "Ring brightness"
    description = "Mean value of the pixels above a threshold."
    version = "1.0"
    params = [Param("threshold", int, 140, "pixels above this count", min=0, max=255)]
    columns = [Column("rim_mean", "mean of bright pixels", "DN"),
               Column("rim_px", "number of bright pixels", "px")]
    plot = ("rim_mean",)              # the studio's default plot

    def process(self, frames, ctx):
        # frames: (k, h, w) uint8, one BATCH, already cropped
        k = len(frames)
        flat = frames.reshape(k, -1)
        mask = flat > ctx.params["threshold"]
        n = mask.sum(1)
        s = (flat * mask).sum(1)
        return {"rim_mean": np.where(n > 0, s / np.maximum(n, 1), np.nan), "rim_px": n}
```

These rules let the runner parallelise your module and check its output:

- `process(frames, ctx)` returns a dict of 1-D numeric arrays, one value per
  frame. A scalar is broadcast.
- Batches may run in parallel and in any order. If your module needs state
  that carries across batches, set `parallel = False`; batches then arrive
  strictly in order.
- `begin(ctx)` runs once, before the first batch. `ctx.sample(n)` returns `n` frames
  spread over the range, which is useful for a background or a calibration. `finish(table,
  ctx)` runs once with every column; add derived columns there, and put
  scalar results in `ctx.summary`.
- `ctx` also provides:
  - `params`: resolved and validated parameter values;
  - `meta`: the recording's metadata;
  - `crop`, `origin`: add `origin` to window coordinates to report full-frame positions;
  - `frame_index`, `timestamp_raw`: for this batch;
  - `state`: a dict for your own use;
  - `log(msg)`.
- `overlay = {"x": col, "y": col, "r": col}` makes the studio draw those
  columns on the frame, and `trajectory = True` makes the x–y plot the
  default.
- Fast helpers for 8-bit frames are in `opngx.analysis.stats`: per-frame
  histograms, mean/std, extremes, percentiles.

A file that fails to import, or whose class breaks these rules, is listed as
broken with its error. It never takes the app or the other modules down.
A module can't reuse a built-in's name.

**Why Python?** Modules can be written, edited and reloaded inside the app,
with no compiler, and numpy's vectorised kernels run at C speed on batches of
frames (the built-ins reach thousands of frames per second). If you need
native code, a module can still call a compiled library through `ctypes`.
