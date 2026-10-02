# opngx v2.1.0 — more formats and codecs, five new analysis modules, a fixed Windows installer, a new look

**Released:** 2026-10-02 · **ABI:** 5 (new exports `opngx_focus`, `opngx_blobs`; struct unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

> **If you installed v2.0.x with `opngx-setup.exe`, please check your user PATH.**
> A bug in that installer (fixed here, details below) could **replace** the
> user PATH with only the opngx folder. Folders that other programs had added to
> it (Python, Git, …) may be missing.
>
> To check, press **Win+R**, run `rundll32 sysdm.cpl,EditEnvironmentVariables`
> and look at *Path* under "User variables". Re-add anything that's missing.
> Installing v2.1.0 does not change existing entries. The system PATH was never
> touched.

Pixels are unchanged: every format that existed before writes the same bytes,
and PNG stays pixel-identical to TimeViewer's exports.

---

## More output formats, each one measured

- **New image formats:**
  - **PGM** (Netpbm, 8 or 16 bit) and **16-bit TIFF**, written by the C engine;
  - **lossless WebP**, **JPEG 2000** and a **single-file NumPy stack** (`.npy`,
    `np.load(p, mmap_mode="r")` opens 50,000 frames instantly), written through
    Pillow / numpy on all cores.
- **New video codecs**, with the ffmpeg that ships with the studio: **H.265, VP9,
  AV1, FFV1, ProRes 422 HQ, Motion-JPEG, GIF**, and **H.264 on the GPU** (NVIDIA /
  Intel / AMD, tried for real before it is offered). **FFV1 is lossless**: every
  frame decodes to exactly the extracted pixels.
- **Every lossless output is proven bit-exact**, on 1,000 real frames and in the
  test suite, by decoding each file with an independent reader. Lossy outputs are
  listed with their measured error (JPEG q90: max 19 levels, 39.8 dB). The new
  guide **[OUTPUTS.md](https://github.com/Shuvam-Banerji-Seal/opngx/blob/main/docs/OUTPUTS.md)**
  has the tables and which output to use for what.
- **`opngx formats`** lists every format and codec, whether it works on this
  computer, and what it keeps. **`opngx video -c ffv1`** picks a codec.

## Five new analysis modules (validated against ground truth)

| module | measures | validated |
|---|---|---|
| **focus** | sharpness: Laplacian variance, Tenengrad, normalised variance (C kernel) | monotonic with blur; C = numpy |
| **drift** | stage / chamber drift by phase correlation with DFT upsampling | 0.06 px rms on synthetic drift |
| **particles** | blob count, areas, largest blob (C kernel, automatic Otsu threshold) | exact counts and areas; C = numpy |
| **flicker** | illumination spectrum and its lines | 37 Hz / 2.0 % → 37.0 Hz / 1.99 % |
| **roi_stats** | mean/std/min/max in up to 16 rectangles you give | equal to direct numpy |

On this project's recordings, **flicker** finds the 50 Hz and ≈100 Hz mains lines
(about 0.01 % of the brightness) and **drift** shows a very stable stage (0.017 px
jitter).

New module API: `ctx.first(n)` gives modules the first frames of the run, for a
reference image.

## Analysis fixes (from a bug hunt; every one reproduced, then tested)

- **PSD stiffness was biased high.** The power-spectrum fit weighted each bin by
  the *measured* (noisy) spectrum, so D came out 7.5 % low at the default 16
  segments and 30 % low at 4, and the PSD trap stiffness that much too high. It
  now reweights with the fitted model: D is within 1 % at 4, 16 and 64 segments
  on simulated optical-trap data.
- **Modules could corrupt each other.** All modules of a run received the same
  frame array, so one that modified it in place silently changed every other
  module's input. Frames are now read-only (also in Validate's dry run).
- **Ragged `finish()` tables are now an error at the module.** A table with
  columns of the wrong length used to crash the save or silently truncate it.
- **Saving results:**
  - numpy booleans in a summary made every save format fail;
  - JSON reloads lost integer types and the plot settings;
  - NPZ failed for a column named `file` and mis-read table names containing `__`;
  - TSV dropped the extra tables (MSD, PSD, …) and wrote `nan`.

  All fixed. CSV times now keep 10 significant digits (6 quantised long
  high-rate recordings to 1 ms).
- **The dry run and the real run disagreed:**
  - an attribute a module set on `ctx` in `begin()` crashed the real run but
    passed Validate;
  - a module reading real metadata (e.g. exposure) failed Validate but worked
    for real.

  Both now behave the same.
- **Module names:**
  - a broken module file could hide a working module with the same name;
  - Validate did not warn when your module's name was already taken (it then
    silently never ran).
- **Parameters:**
  - NaN or infinity passed every range check;
  - "47.9" became 47 without a word;
  - a numeric drop-down (e.g. particles' connectivity) showed the wrong value.
- **The one-sided PSD** left its last bin at half level for odd segment lengths.

## Windows

- **The installer is rewritten**, in Unicode throughout:
  - **PATH:** the user PATH is never replaced (see the note at the top). It is
    read whole, its type is kept, and only the exact opngx entry is added or
    removed. v2.0 also matched any entry *containing* `\opngx`, e.g. a
    `D:\opngx-dev` folder.
  - **Uninstall** now works: it ran an option the engine does not have.
    `Settings → Apps → opngx studio → Uninstall` removes the program files,
    shortcuts, the PATH entry and the registry entry. Your frames, results and
    modules stay.
  - **Shortcuts** start the studio, not the console engine.
  - **Profile folders with non-ASCII names** (`C:\Users\José`) work.
  - **Installing while opngx runs** asks you to close it, instead of failing with
    "Payload extraction failed".
  - **CI tests all of this on real Windows** on every build: PATH kept, shortcut
    target, install and uninstall.
- **No more console windows.** Verify and video export started console programs
  (the engine, ffmpeg) that flashed a console window and died if it was closed.
- **Errors you can read:**
  - a failing video export showed "Broken pipe" instead of ffmpeg's actual
    message;
  - Verify crashed on non-ASCII folder names;
  - a start-up failure of the packaged studio vanished silently, and is now
    shown in a message box and written to `startup-error.log`.
- **Video export is a tab, no longer a dialog.** Closing the old dialog left
  ffmpeg encoding unseen, and the main Cancel could not stop it. Batch windows
  that were closed or replaced kept extracting, and quitting mid-run cut files
  off. Now Cancel/Esc stops everything, and quitting asks first.
- **Display scaling:** Auto now respects Windows' own scaling. A 4K screen at
  150 % was enlarged a second time (to ~200 %), and a 1080p laptop at 150 % got
  135 %. The layout now fits a 1280×672 work area; the audit is clean on every tab.
- **The exe:**
  - the window and taskbar icon now show (the file was looked up in the wrong
    place), and the studio has its own taskbar identity;
  - dead Qt plugins whose libraries were never bundled are gone;
  - a JPEG 2000 export from a script without an importable main module waited
    forever. It now falls back to threads.

## A new look

- **The logo** is redesigned: a green six-blade iris with a tracked particle on
  its orbit. It is drawn from one geometry in code, so the app icon can't go
  missing.
- **It animates:**
  - on the new start-up splash screen;
  - on the Start tab;
  - in the header while work is running.
- **Vector icons:** 50 icons drawn for opngx (no third-party set) replace
  emoji and symbol glyphs that some Windows fonts showed as boxes. They stay
  sharp at any scaling and take the theme's colours, including when you switch
  theme.
- **Seven tabs:**
  - **Start** (new): what opngx does, the workflow, which format to choose,
    recent recordings;
  - **Extract**;
  - **Video** (new);
  - **Analyze**;
  - **Editor**;
  - **Docs**;
  - **System** (new): the computer, engine and ffmpeg, a speed test, a format
    check and a copyable report.
- **Shortcuts:** Ctrl+O, Ctrl+E, Esc, Ctrl+1…7.

## Documentation

- **New:** [OUTPUTS.md](https://github.com/Shuvam-Banerji-Seal/opngx/blob/main/docs/OUTPUTS.md),
  every format and codec, measured.
- **Updated:** ANALYSIS.md (the five new modules, with their validation),
  STUDIO.md (the new tabs and shortcuts) and a rewritten README with current
  screenshots and numbers.

## Verification

- **Tests:** pytest **108/108**, also with deprecation warnings as errors. Pillow 13
  (due 2026-10-15) removes an argument opngx used; it no longer does.
- **Engine suite** **46/46**, natively and with the Windows build.
- **AddressSanitizer + UBSan:** the new C kernels (`opngx_focus`, `opngx_blobs`)
  are clean on degenerate and real sizes.
- **Exactness:**
  - all 250,000 frames of the five recordings are still pixel-exact against
    TimeViewer;
  - every lossless format is bit-exact on the engine and the fallback path;
  - FFV1 and GIF videos are bit-exact.
- **Packaged-studio selftests on real Windows (CI):** UI, engine, analysis, batch
  (newly added to CI), **every video codec**, speed (with a start-latency limit)
  and the installer test.

## Assets

| File | What |
|---|---|
| `opngx-setup-v2.1.0.exe` | Windows installer: studio, engine, ffmpeg, docs, sample modules; uninstaller |
| `opngx-studio-portable-v2.1.0.exe` | Windows studio, single file, no install |
| `opngx-engine-v2.1.0.exe` | Windows CLI engine only |
| `opngx-2.1.0-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | Python package + C engine, Linux x86_64 |
| `opngx-2.1.0-py3-none-win_amd64.whl` | Python package + C engine, Windows amd64 |
| `opngx-2.1.0.tar.gz` | Python sdist (numpy fallback) |
| `opngx-2.1.0-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.1.0_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
