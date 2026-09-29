# opngx v2.0.0 — analysis modules: motion tracking, Brownian/trap analysis, write your own

**Released:** 2026-09-29 · **ABI:** 5 (struct unchanged; new exports `opngx_track`, `opngx_hist256`) · **License:** MIT
**Developer:** Shuvam Banerji Seal

opngx now turns a recording into **measurements**, not only images. The
studio grew from one window into four workspaces — **Extract · Analyze ·
Editor · Docs** — with eight colour themes, a real code/text editor, an
in-app documentation system and a crop editor worthy of the name. The core
analysis runs in C, validated against a numpy reference, and was put
through AddressSanitizer, UBSan and fuzzing.

Everything from 1.9 keeps working: same ABI, CLI, output tree, and
pixel-exact extraction.

---

## Analysis modules

A module turns frames into a table: one row per frame, plus summary values
and extra tables. Modules are **plain Python files** that you can switch in and out
in the studio, run from the CLI, or call from Python:

```bash
opngx analyze recording.bin -m motion_tracking -o trajectory.csv
opngx analyze Footages/ --batch -m brownian_motion -p brownian_motion.pixel_size_um=0.1 -o Results/
opngx modules            # list · show · template · validate · dir
```

Data files are **CSV** (with `# key: value` metadata lines), **JSON**,
**NPZ** or **TSV**. Every file includes the camera clock (`timestamp_raw`)
and `time_s`, so a trajectory is always timed by the frame headers, not by
an assumed frame rate.

### Motion tracking (the first module)

This module follows the bright feature through the recording. In this project's footage that feature is a
sphere imaged as a **ring**, brighter on its lower rim, so the default `auto`
method recognises a ring and fits a circle to the rim's intensity **ridge**
(48 rays, prominence-weighted). A plain intensity centroid would be pulled
~5 px toward the bright side of the rim.

| measured on synthetic ground truth | bias | RMS |
|---|---|---|
| ring, default (ridge-refined circle) | (0.000, +0.025) px | **0.044 px** |
| ring, mask-only circle fit | (0.001, +0.222) px | 0.236 px |
| ring, intensity centroid | (0.00, +8.53) px | 8.53 px |
| spot, default (centroid) | (0.000, +0.001) px | **0.049 px** |

On all five real 50,000-frame recordings it tracks **100%** of frames, with a
radius scatter of 0.07 px and a median frame-to-frame step of 0.11 px.
Positions are always full-frame pixels, whatever crop you analyse; a crop
that doesn't clip the search window gives **bit-identical** positions.

### Brownian motion & optical-trap analysis

Built for this data: a bead in a laser beam. The module runs motion tracking in the same pass,
then reports:
- drift;
- the MSD, giving D, α and the localisation noise;
- the power spectrum, fitted with the exact sampled-Ornstein–Uhlenbeck spectrum
  (a plain Lorentzian over-estimated f_c by 14% in simulation);
- an autocorrelation estimator;
- trap stiffness, by equipartition (raw and noise-corrected) and from the PSD;
- step statistics.

It also writes MSD, PSD and step-histogram tables, plotted on log axes in
the studio.

**Validation on simulations** (sampled OU at 500 Hz, 50,000 frames):
- the corner frequency is within 2–6% by PSD, ACF and MSD;
- D is within 1–4%, and the localisation noise within 2%;
- stiffness is within 0.4% by equipartition;
- free diffusion gives α = 0.995.

The module **will not silently report a trap that isn't there**: it warns when
the step distribution isn't Gaussian, when the estimators disagree, or when
the spectrum has narrow lines. On this project's recordings it finds lines
at **≈38.8 Hz and ≈98/103 Hz** in every recording (periodic forcing such as
vibration, a pump or electrical pickup), which are excluded from the fit. It also flags
non-Gaussian steps in y.

### Luminosity and contrast

Two more built-in modules:
- **Luminosity**, per frame: mean, std, min, max, integrated, saturated fraction; plus drift and flicker.
- **Contrast**, per frame: Michelson (robust), RMS, Weber.

Both are computed from exact per-frame histograms, which run in C.

### Write your own

- **API:** subclass `Module`, declare `params` and `columns`, and implement
  `process(frames, ctx)` on batches of frames. The optional pieces:
  - `begin` / `finish` hooks;
  - `requires` to build on another module's finished table;
  - extra tables;
  - a frame overlay.
- **Isolation:** a broken module file is listed with its error; it never takes the app down.
- **Documentation:** the whole API is documented in `docs/ANALYSIS.md`, and in the
  studio as a reference generated from the live code.

## Speed: the core analysis runs in C

The tracker's hot path (search, threshold, circle fit, ridge refinement) and the
histograms are new C exports of the engine library (`src/analysis.c`). They're
single-threaded per call; the Python runner spreads batches over all
cores, and ctypes releases the GIL during each call.

| 50,000-frame recording, 3 modules in one pass | time |
|---|---|
| numpy implementation | 23.1 s |
| **C kernels** | **6.8 s** (3.4×) |

The two paths agree to **1.4×10⁻⁷ px** on rings, spots, noise, flat and tiny
frames, small windows and crop offsets (test AN-10). Getting there meant
compiling `analysis.c` without FMA contraction and making the ridge search
tie-proof: a last-bit difference in `cos()` used to flip ties in
degenerate windows. `OPNGX_ANALYSIS_BACKEND=python` forces the numpy path.

## Studio

- **Analyze tab:**
  - switch modules in and out, with parameter forms and one pass for all ticked modules;
  - run on one recording or a whole batch;
  - see the tracked point and trajectory on the frame;
  - plot vs time (independent axes), as an x–y trajectory, or log-log for the extra tables;
  - data table, summary with warnings, log;
  - export CSV / JSON / NPZ / TSV, one result or all.
- **Editor tab:** a real editor for modules (Python) and docs (Markdown).
  - Tabs, highlighting, line numbers, bracket matching.
  - Find/replace (case, word, regex, replace-all as one undo step), go to line.
  - Comment toggle, block indent, duplicate line, auto-indent, auto-close.
  - Completion of Python keywords, the analysis API and words in the file; zoom.
  - Validate (dry run on synthetic frames, error line highlighted), and test on the loaded recording.
  - *Save & use*.
- **Docs tab:**
  - the shipped guides and release notes;
  - an **API reference generated from the code**;
  - a **reference page for every module** (built-in or yours);
  - **your own Markdown docs**;
  - full-text search.
- **Themes** (View → Theme): Midnight, Catppuccin Latte / Frappé / Macchiato /
  Mocha, Tokyo Night, Tokyo Day, Cappuccino, plus a **custom accent colour**.
  Switching is live, remembered, and applies to plots, overlays and code colours too.
- **Crop editor:**
  - zoom (wheel, Fit, 1:1, 4×) and pan (right/middle drag), with a pixel grid when zoomed in;
  - scrub to any frame;
  - aspect locks and size snapping (2 px, MP4-friendly, up to 32 px);
  - auto-crop **around the bright spot** (using the real tracker, so it centres on a ring) or
    **around the tracked path**;
  - auto levels (display only);
  - undo/redo, arrow-key nudging, named presets, live region stats.
- **Frame viewer:** zoom and pan everywhere, with a pixel grid from 6×.

## UI quality

- **A layout audit** (`opngx/ui/audit.py`) checks every tab and dialog for overlapping
  widgets, widgets outside their parent, and clipped button/label text. It runs at
  1280×720, 1366×768, 1920×1080, 2560×1440 and 3840×2160 across the themes.
  It found and fixed:
  - the ◀/▶ buttons 5 px too narrow;
  - "Verify vs source bin" clipped at ≤768p (the action bar is now two rows);
  - an editor path label cut 400 px short (it now elides in the middle);
  - cramped button grids in the Editor and Docs panes;
  - an invisible slider groove in some themes.
- The editor opens with the code, not the console, taking the space. Docs
  render in a proportional font, and release notes are grouped newest first.

## Reliability

- **AddressSanitizer + UBSan:**
  - the whole engine suite runs clean under both (46/46);
  - so do 64 Python tests against the instrumented library;
  - 3,000 fuzzed calls of the new C kernels (random sizes 1×1…90×120, windows, blocks,
    thresholds, negative and huge crop origins) report nothing.
- **Found and fixed:**
  - undefined behaviour in the vendored JPEG encoder (a signed left shift). The patch is
    proven output-neutral: the SHA-256 of 70 JPEGs is identical before and after;
  - a GPU-detection buffer that truncated device signatures, so duplicate
    GPUs were never recognised;
  - a lazily initialised shared table that was a data race.
- **Crash reports:** uncaught errors on the UI thread or a worker thread are
  shown in a dialog and written with a full traceback to `crash.log`, and
  native crashes dump every thread's stack there (`faulthandler`).
  *Help → Open log / crash-report folder* opens it.
- **Windows text encoding:** found by the packaged selftest running inside
  the real `.exe`, which is where a user would have hit it.
  - Module templates are now pure ASCII: the em dash was written as cp1252 and the
    module then failed to import.
  - The selftest log, CSV and JSON writers use UTF-8 explicitly.

## Smaller download

The Windows studio `.exe` shrinks from **124 MB to 70 MB**:
- ffmpeg was bundled **twice** (88 MB each), and one copy is gone;
- the software-OpenGL fallback, Qt Quick/QML/PDF/Network libraries, Tcl/Tk and PIL's AVIF codec are
  gone too; nothing loads them.

All packaged selftests pass inside the compact build.

## Verification

- pytest **85/85**: new AN-1…AN-17 cover accuracy, runner, native parity, Brownian
  physics, spectral lines, registry, CLI, the studio's Analyze/Editor workflow,
  crop tools, docs sync, encoding, crash logging and themes.
- Engine suite **46/46**, also under ASan + UBSan.
- The layout audit is clean at every tested resolution and theme.
- Packaged selftests (ui / engine / batch / video / **analysis**) pass in the
  Windows `.exe` under Wine. CI runs them on real Windows too.

## Assets

| File | What |
|---|---|
| `opngx-setup-v2.0.0.exe` | Windows installer: engine + Qt studio + ffmpeg + docs, Start-menu shortcuts, uninstaller |
| `opngx-studio-portable-v2.0.0.exe` | Windows studio, single file, no install |
| `opngx-engine-v2.0.0.exe` | Windows CLI engine only |
| `opngx-2.0.0-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.0.0_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
