# opngx v1.8.0 — crop that works, project-file settings in every batch, a pixel-exact viewer

**Released:** 2026-09-28 · **ABI:** 5 (unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

v1.7.0 introduced cropping and the batch window. The field report on it
was "so many issues with cropping", plus "gamma and contrast settings not
getting applied to batches, and not getting extracted from the project
files". Both reports were accurate. This release fixes **every defect we
could reproduce** (each one reproduced first, then pinned by a regression
gate). It also rebuilds the frame viewer and makes the preview and export
paths faster.

Upgrading is drop-in: same ABI, same CLI flags (plus a few new ones), same
output tree.

---

## Brightness / contrast / gamma

### Settings are now read from each recording's `.footage`
The B/C/G fields in the studio were hard-coded to 49 / 18 / 1 at start-up
and **never loaded from the project file**. In `reference` mode those
fixed numbers were then sent to the engine as explicit values, so:

* a recording saved with any other processing settings was extracted
  with the wrong curve, and
* in a batch, one set of numbers was forced onto every recording. No
  recording ever used its own project settings.

Now `reference` means *"each recording's own `.footage` values"*:

* probing a recording fills the fields from its `.footage`;
* a batch sends no explicit values, so every recording resolves its own;
* each batch card shows the exact B/C/G that recording will get.

Editing a field switches to `custom` (one curve for all recordings), and
the log says so. Switching back to `reference` restores the file's values.

### The batch window now uses the current settings
The batch window copied the studio's settings **once, when it opened**.
A gamma or contrast change made afterwards never reached *Extract all*.
The window now reads the live settings when a run starts, and its cards
re-render whenever a quality control changes.

### Decimal commas in `.footage`
TimeViewer on a decimal-comma Windows locale writes `<Gamma>1,5</Gamma>`.
The Python reader crashed on it (`could not convert string to float`),
and the C engine silently read it as `1`. Both now read `1.5`.

## Crop

| Defect in v1.7.0 | Now |
|---|---|
| Crop dialog **W/H boxes were stuck at the full frame** (spin-box arguments in the wrong order), so a typed size was ignored | W/H accept any value from 1 to the frame size |
| The drag rectangle **did not match the image**: mouse positions were mapped as if the frame were drawn unscaled at the top-left | one geometry drives drawing and mouse mapping; a drag lands on exactly the pixels it covers |
| A fresh editor **could not draw at all**: every press inside the default full-frame selection became a no-op "move" | drag to draw; drag inside to move; drag an edge or corner to resize |
| The "selection" was dimmed like the rest of the frame | the area outside the crop is dimmed, the crop stays bright |
| **Cancel applied the crop anyway**, to *every* recording, since "apply to all" was on by default | Cancel changes nothing; "apply to all" is off by default in the batch window |
| "Apply to all" pushed a crop onto recordings it did not fit, which then failed during extraction | recordings the crop doesn't fit are skipped and listed |
| `--crop X,Y,0,0` was documented as "to the frame edge" but the engine rejected it | `0` means "to the edge" in the engine, verifier, Python API and studio |
| Python fallback engine: crop ignored `crop_y` and read sheared rows (broadcast crash for RGBA) | pixel-identical to the native engine |
| Small crops (e.g. 17×9) exported as **BMP/TIFF/JPG failed every frame** (output buffer sized for PNG only) | all formats, any crop size |
| MP4 render **failed for any odd crop width/height** (H.264 4:2:0 needs even sizes), i.e. half of all hand-drawn crops | one black row/column of padding; every selected pixel is kept |
| A crop left over from a larger recording was silently clamped in the viewer, then rejected at extraction | a crop that doesn't fit is cleared on probe, with a log line |
| *Verify vs source bin* used the **current** crop, not the one the folder was extracted with | it reads the crop from the run's `metadata.json` |

## Frame viewer & UI

The viewer was a `QLabel` holding a pre-scaled pixmap. It is now a
dedicated widget:

* **re-fits on every resize** (before, it kept the old size until you
  scrubbed);
* **pixel-exact enlargement**: whole-pixel steps with no smoothing, so
  each sensor pixel is a crisp square. Small 256×300 frames used to be
  blurred. It is also HiDPI-aware;
* it no longer holds the splitter open, and it is now a resizable pane
  in the right-hand splitter (before, it sat outside the splitter at its
  minimum height while the info table and log took the space);
* **pixel readout** on hover: position, raw sensor value and output
  value;
* **show crop in context** toggle: the full frame with the crop outlined,
  or exactly the pixels that will be written.

Also fixed: the frame counter was clipped off the card edge; there was a
white bar under the settings panel and behind the batch cards (Qt scroll
areas paint the platform window colour); batch cards now show
`256 × 300 → 64 × 48 px` instead of only the cropped size. In the
main-window batch, one failing recording no longer aborts the rest.

## Performance (measured on this release's real 256×300 footage)

| Path | v1.7.0 | v1.8.0 |
|---|---|---|
| Viewer frame decode (random frames, custom curve) | 0.61 ms | **0.074 ms** (8.2×): one memory-mapped reader and a LUT cache, instead of reopening the multi-GB file for every frame |
| MP4 feed with a crop (200×240, one thread) | 9.8 k fps | **17.3 k fps** (1.8×): one contiguous gather and one LUT pass per chunk, instead of a Python slice per row |
| Scrubbing | every slider step decoded synchronously | steps are coalesced; only the latest position is drawn |
| Opening the batch window | recordings probed one after another | probed concurrently |

The extraction engine's throughput is unchanged. Deflate remains ~99% of
the cost.

## Other fixes

* Python fallback engine ignored `start`, `format`, `channels` and
  `jpeg_quality`: it always started at frame 0 and always wrote RGBA PNG.
* `Extractor.extract(fmt="bmp"|"tif"|"jpg")` with the default extension
  raised `TypeError` on the native path (a `str` was assigned to a C
  `char*` field).
* `opngx video` now takes `--brightness/--contrast/--gamma/--crop`, and
  `--footage` is honoured (it used to be parsed and then ignored).
* `metadata.json` timestamp statistics now describe the extracted range
  rather than always starting at frame 0.

## Test gates that were passing for the wrong reason

* **T-24** (crop validation, engine suite): each check read the exit
  status of a shell *assignment*, which is always 0, so all three gates
  passed unconditionally. They are rewritten, and two more cases were
  added.
* **AR-23** (fallback crop parity): the test patched
  `_engine.load_library`, but the extractor imports that name directly.
  The native engine ran on both sides of the comparison and the broken
  fallback was never exercised. It now patches the right name and
  asserts the fallback actually ran.

New gates: **T-25** (0 = to the edge; tiny crops in BMP/TIFF/JPG),
**AR-25** (fallback = native across crop/start/format/channels),
**AR-26**, **AR-27** (decimal comma), **AR-28** (each recording's own
`.footage` curve in a batch; live batch settings), **AR-29** (crop
editor mouse mapping, typed sizes, Cancel, fit-aware apply-to-all).
Against the v1.7.0 sources the new Python gates fail: the fallback
broadcast crash, the `'18,5'` ValueError, and the missing studio
settings logic (AR-28 fails at the API level).

## Verification

* engine suite **46/46** on Linux and under Wine (Windows build);
* pytest **65/65**;
* packaged selftests (ui / engine / batch / video) pass on Linux and
  inside the Windows `.exe` under Wine;
* real footage: `reference` output is pixel-exact against the vendor
  PNGs; a cropped custom-gamma batch over all 5 recordings passes
  `verifybin`; the studio's own batch path (C 30, γ 0.7, 97×113 crop,
  start 1234) is pixel-exact on all 5.

## Assets

| File | What |
|---|---|
| `opngx-setup-v1.8.0.exe` | Windows installer: engine + Qt studio + ffmpeg + docs, Start-menu shortcuts, uninstaller |
| `opngx-studio-portable-v1.8.0.exe` | Windows studio, single file, no install |
| `opngx-engine-v1.8.0.exe` | Windows CLI engine only |
| `opngx-1.8.0-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_1.8.0_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |

The assets were built by the Release workflow on GitHub's Windows and
Linux runners from the tagged commit. They were then re-downloaded and
checked: every checksum matches, and the four packaged selftests
(ui / engine / batch / video) pass inside the portable `.exe`.
