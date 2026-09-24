# opngx v1.7.0 — batch correctness, ROI crop, batch window

**Released:** 2026-09-24 · **ABI:** 5 · **License:** MIT
**Developer:** Shuvam Banerji Seal

This release fixes three separate defects that made batch runs ignore the
settings on screen, adds region-of-interest cropping end-to-end, and adds
the dedicated batch window.

---

## Fixes

### 1. `reference` mode silently discarded your brightness/contrast/gamma

`reference` is the studio's default quality mode. In that mode the engine
overwrote the three transform values with the ones stored in each
recording's `.footage` sidecar — so typing `gamma = 2.0` and pressing
Extract produced `gamma = 1.0` output, while the frame viewer (which
honoured the field) showed the gamma-ed result. **The preview did not
match the file.**

The same substitution existed in three places and all three are fixed:
`Extractor.extract`, `opngx_job_create` (C) and `opngx_verify_bin`.

**New rule:** a transform you supply is always used. The sidecar value is
used only for the fields you leave alone. The CLI exposes this explicitly:

```bash
# each of these applies to the WHOLE batch
opngx batch Footages/ -o out/ --mode custom --brightness 20 --contrast 30 --gamma 2.0
opngx-engine batch --in-dir Footages/ --out-root out/ --gamma 2.0
opngx batch Footages/ -o out/ --sidecar-transform   # force the vendor curve
```

`reference` mode with no transform still reproduces the vendor curve
exactly, so the pixel-exact guarantee is unchanged.

### 2. `opngx-engine batch` rejected every quality flag

The standalone C `batch` subcommand accepted only `--in-dir`, `--out-root`,
`--prefix`, `--jobs`, `--level`, `--mode`, `--format`, `--layout`,
`--timestamps` and `--metadata`. `--brightness`, `--contrast`, `--gamma`,
`--channels`, `--bit-depth` and `--jpeg-quality` were all "unknown option",
and the per-bin parameter block hardcoded `p.gamma = 1.0`. A batch run
therefore *could not* apply the settings the studio displays.

`batch` now mirrors `extract`'s quality surface exactly, and the T-22 gate
proves it by byte-comparing a batch run against a single extract with the
same B/C/G.

### 3. The Python CLI's `batch` was missing flags and imported Qt

`opngx batch --layout format` failed with "unrecognized arguments" because
`--layout` and `--format` were never registered — yet `run_one()` went on
to read `args.layout` through `getattr`. The layout branch also imported
`_run_out_dir` from the Qt module, a name that does not exist (the helper
is `opngx.layout.run_out_dir`), so a CLI command depended on PySide6.
Both fixed; the CLI now imports nothing from the UI, and a batch over a
folder with no `.bin` files returns non-zero instead of quietly succeeding.

### 4. Data loss: same-named recordings overwrote each other

**Found by the bug hunt, not reported.** Batch output folders were keyed on
the `.bin` *filename*. Cameras are routinely dumped as
`<root>/<camera>/recording.bin`, so every recording collapsed into one
folder and each run overwrote the previous one frame for frame — 16 frames
extracted, 8 on disk, with no warning.

In the mother-folder architecture the recording **folder** is the identity,
so that is what is used now. `opngx batch` additionally refuses to start
when two recordings would still land in the same folder, naming the
offending paths instead of destroying output.

### 5. Test-suite hygiene

`test_audit_regressions.py` carried two copies of AR-14 and AR-15; Python
silently kept the last, so the first bodies were dead code — and the dead
AR-15 was itself broken (it toggled a radio button that was already
checked, so the scope switch under test never fired). AR-16 now fails the
build on any duplicate top-level test.

---

## New: region-of-interest crop

```bash
opngx extract recording.bin -o roi/ --crop 100,80,512,384
opngx batch  Footages/     -o out/ --crop 100,80,512,384   # every recording
```

```python
opngx.extract("recording.bin", "roi/", crop=(100, 80, 512, 384))
opngx.verify_against_bin("recording.bin", "roi/", crop=(100, 80, 512, 384))
```

A crop is a **pure pixel selection — no resampling, no interpolation**.
Output pixel `(x, y)` is the LUT-mapped source pixel
`(crop_x + x, crop_y + y)`, so a cropped frame is bit-identical to the
matching rectangle of an uncropped one. `W` or `H` of `0` means "to the
frame edge", which is what the UI emits for a box dragged to the border.

Everything agrees on the window, so nothing can silently disagree:
the engine, the Python fallback, the frame viewer, MP4 rendering,
`metadata.json` (which records `crop` and `output_width/height`) and
`verifybin` (which re-derives the same window — a gate proves that
verifying a cropped run *without* `--crop` correctly fails).

Invalid rectangles are rejected with a crop-specific diagnostic rather
than a generic non-zero exit.

## New: batch window

`Batch window…` in the studio opens a dedicated surface with **one card
per recording**, each showing:

* a real decoded frame from the middle of that recording (not a placeholder)
* encoded output size — cropped size when a crop is set
* frame count, effective fps, and the folder the frames will land in
* the crop currently in force
* its own status line and progress bar
* `Crop…` (per recording or for all) and `Preview` (loads it into the main viewer)

Settings changed in the main window — brightness, contrast, gamma, mode,
format, bit depth, channels, jobs, level, sidecar exports — are applied to
**every** recording in the batch, which was the behaviour the field report
was missing. Cancel is honoured per recording and a failing recording no
longer aborts the rest: failures are collected and reported at the end.

## New: crop editor

`Crop…` opens a picker over a real decoded frame. Drag a rectangle, or type
exact `x/y/w/h`; values are clamped to the frame and snapped to whole
pixels; `Full frame` and `Centre 50%` are one click away. A live preview
shows the selected window through the current transform. Apply it to this
recording only, or to every recording in the batch.

The main viewer displays the cropped window, and the status line reports
the output size, so the preview cannot lie about the output.

## Logo

A scalable logo suite (`assets/logo/`) ships with a vector master, PNGs at
16 → 1024 px, a multi-resolution `.ico`, and wordmarks. It is wired into the
app window, the Windows installer resources and the PyInstaller spec, and
replaces the generic executable icon.

---

## Compatibility

* **ABI 4 → 5** (`opngx_params` gained `use_sidecar_transform` and four crop
  fields). The ctypes mirror and the `opngx_abi_version()` handshake ship in
  the same commit, so a stale `.so`/`.dll` is rejected with a clear message
  rather than corrupting memory.
* `reference`-mode output is **unchanged** whenever no explicit transform is
  supplied — the pixel-exact guarantee against vendor exports still holds
  and is still covered by T-1.
* The batch output **folder name** changes only in the collision case, where
  the old behaviour destroyed data.

## Verification

| Suite | Result |
|---|---|
| `tests/test_engine.sh` (Linux, gcc) | **38/38** |
| `tests/test_engine.sh` (Windows build under Wine) | **38/38** |
| `python/tests` (pytest) | **60/60** |

New gates: **T-22** (batch honours every quality flag) · **T-23** (crop
pixel-exact + verifybin parity + identity case) · **T-24** (crop validation)
· **AR-16** (no duplicate tests) · **AR-17/18** (reference-mode transform
semantics, both directions) · **AR-19** (CLI flags registered, no Qt import)
· **AR-20** (engine batch flag parity, no hardcoded gamma) · **AR-21/22**
(no output-folder collision, end-to-end) · **AR-23** (crop parity native vs
fallback) · **AR-24** (batch window + crop editor offscreen, incl. a real
extraction).
