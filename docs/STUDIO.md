# opngx studio — user guide (v2.1)

The studio has seven tabs: **Start · Extract · Video · Analyze · Editor · Docs ·
System** (Ctrl+1…Ctrl+7). Press **F1** for the field guide of every control.

| shortcut | does |
|---|---|
| Ctrl+O | open a recording |
| Ctrl+E | extract |
| Esc | cancel what is running (extraction, video, …) |
| Ctrl+1 … Ctrl+7 | switch tab |
| F11 | full screen |

The logo in the top-left corner animates while work is running.

## Start
What opngx does, the three steps of a session, a table of which output format to
choose (and what each one keeps), your recent recordings (double-click to open)
and the shortcuts. The first start opens here; later starts open the tab you
used last.

## Extract
This tab turns a recording into one image per frame. Choose one `.bin` or a batch
mother folder, set the quality mode (reference = each recording's own `.footage`
curve, raw, or custom), the format, and optionally a **crop**. Then click Extract.
*Verify* proves that the output is pixel-exact.

**Formats** (see the *Output formats* guide for measurements): PNG (default,
TimeViewer-identical), TIFF and PGM (8 or 16 bit), BMP, lossless WebP, JPEG 2000,
a single-file **NumPy stack**, and lossy JPEG. The *quality* slider applies to
JPEG (40–100) and WebP (100 = lossless, lower = lossy); the other formats are
lossless and have no quality setting. The *level* slider is the PNG compression
effort: 1 (default) is the fastest, and every level gives the same pixels.

## Video
One video file from the loaded recording, with the bundled ffmpeg:
- **Codecs:** H.264 (plays everywhere), H.265, VP9, AV1, **FFV1 (lossless,
  bit-exact)**, ProRes 422 HQ, Motion-JPEG, GIF (lossless for this footage), and
  H.264 on the graphics card when one is available. Codecs that do not work on this
  computer are greyed out.
- **Settings:** the quality control follows the codec (CRF, q or QP); *real time*
  sets the frame rate from the camera's timestamps.
- **Crop and curve:** the crop and the transform come from the Extract tab.
- **Proof:** after an FFV1 or GIF render, *Check the last video is bit-exact* decodes
  every frame and compares it with the extracted pixels.
- **Stopping:** the main Cancel (Esc) and this tab's Stop both stop a render.

The frame viewer is pixel-exact: **wheel** zooms, **right- or middle-drag** pans, and a
**right double-click** fits the frame again. From 6× up a pixel grid appears.
Hovering shows the pixel's raw and output value.

## Crop editor (Crop…)
- Drag to draw a region, drag inside it to move it, and drag an edge or corner to resize it.
- **Wheel** zooms, **right-drag** pans, and the *Fit*, *1:1* and *4×* buttons set the zoom.
- **Arrows** nudge by 1 px (Shift: 10 px); Alt+arrows resize.
- **Ctrl+Z / Ctrl+Y** undo and redo.
- **Frame slider:** pick the frame you crop over.
- **Aspect lock** (1:1, 4:3, 16:9, 3:2) and **snap** to multiples of 2 (MP4-friendly), 4, 8, 16 or 32 px.
- **Around bright spot:** centre the region on the brightest feature.
- **Around tracked path:** the bounding box of the latest motion-tracking result, plus a margin.
- **Auto levels:** stretches the display contrast only.
- **Presets:** name and save crops you reuse.

The crop always selects pixels; it never resamples.

## Batch window (Batch window…)
- **Recordings:** a card per recording; click one to preview it.
- **Preview:** the selected recording with its own scrubber.
- **Compare:** every recording at the same point in its timeline.
- **Progress & log.**

Every pane can be collapsed (▾), popped out into its own window (⧉), made full screen
(⛶, Esc returns), or hidden (✕, restore it from View). **F11** makes the whole
window full screen and **F10** the preview pane.

## Analyze
Run analysis modules, such as motion tracking, Brownian/trap analysis, luminosity,
contrast, or your own. Tick modules to switch them in, set their parameters, and run
them on the loaded recording or on the whole batch. The result shows:
- the tracked point and trajectory on the frame;
- plots vs time or x–y, and log-log plots for the extra tables (MSD, PSD, steps);
- the data table, the summary, with warnings when a model doesn't fit, and the log.

**Export data file…** writes CSV, JSON, NPZ or TSV. See *Analysis modules* in these
docs.

## Editor
This is a text editor for **modules** (Python) and **docs** (Markdown), with a tab per file.

| key | action |
|---|---|
| Ctrl+S | save |
| Ctrl+F / Ctrl+H | find / replace (case, whole word, regex, replace all) |
| F3 / Shift+F3 | next / previous match |
| Ctrl+G | go to line |
| Ctrl+/ | toggle comment |
| Tab / Shift+Tab | indent / outdent (the whole selection) |
| Ctrl+D | duplicate line |
| Ctrl+Space | complete (Python keywords, the analysis API, words in the file) |
| Ctrl+wheel, Ctrl+= / Ctrl+- | zoom |
| F5 / F6 | validate the module / test it on the loaded recording |
| Ctrl+W | close the tab |

*New module…* starts from a working template, and *Duplicate* makes an editable copy of a
built-in. *Save & use* validates the module and makes it available in Analyze.

**Sample modules.** On first start the studio copies four sample modules, a README and a
sample doc into your (empty) modules and docs folders. They appear under *My modules* and
*My docs*. Each one shows a different part of the API:

| sample | shows |
|---|---|
| `example_bright_area` | params, columns, a frame overlay |
| `example_frame_difference` | state between batches (`parallel = False`), a summary |
| `example_background` | `begin()` with `ctx.sample()`, a parameter with choices |
| `example_track_speed` | `requires` (builds on `motion_tracking`), an extra table |

They're copied once and never overwrite your files. *Restore samples* brings back any you
deleted.

## Docs
Every piece of documentation is in one place:
- the guides shipped with opngx;
- the **API reference**, generated from the installed code;
- a reference page for **every module**, generated from its declared parameters and columns;
- **your own documents:** any Markdown file in your docs folder (*New doc…*).

The search box searches all of them.

## System
- **The computer:** processor, cores, memory, graphics, and every screen with its
  scaling.
- **The engine:** the library and CLI the studio loaded, and whether analysis runs in C.
- **ffmpeg:** the build and version, and which codecs work.
- **Your folders.**
- **Copy report:** puts it all on the clipboard for a bug report.
- **Speed test:** extracts a synthetic recording and shows frames/s, CPU use and the
  time to the first frame.
- **Format check:** writes the loaded recording in every image format, reads each
  file back and reports whether it is bit-exact.

## Look & feel
- **View → Theme:** Midnight, Catppuccin Latte / Frappé / Macchiato / Mocha, Tokyo Night,
  Tokyo Day, Cappuccino, or a **custom accent colour**.
- **View → Interface scale:** 80–200%, or Auto. Auto fits the monitor from 720p to 4K
  and respects Windows' own display scaling (125/150/175 %): it never enlarges
  what Windows already enlarged.
- **View → Full screen** (F11).

Your choices are remembered.

## When something goes wrong
Uncaught errors are shown in a dialog and written, with a full traceback, to
`crash.log` in the settings folder. A native crash also dumps every thread's stack
there. *Help → Open log / crash-report folder* opens it.

| folder | Linux / macOS | Windows |
|---|---|---|
| modules | `~/.config/opngx/modules` | `%APPDATA%\opngx\modules` |
| docs | `~/.config/opngx/docs` | `%APPDATA%\opngx\docs` |
| crash log | `~/.config/opngx/crash.log` | `%APPDATA%\opngx\crash.log` |
