# opngx v2.1.1: extracted frames always in recording order, never mixed

**Released:** 2026-10-18 · **ABI:** 5 (new optional export `opngx_job_allow_mixed`; struct unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

> **Analysing a folder of extracted frames could give different results from
> run to run.** Three causes, all fixed here:
>
> 1. **Names past frame 99,999 sorted out of order.** Names were zero-padded to
>    5 digits. Frame 100,000 became `brow_100000.Png`, which a plain name sort
>    (`sorted(glob(...))`, `ls`, MATLAB `dir`) puts between `brow_10000.Png`
>    and `brow_10001.Png`.
> 2. **File dates were out of order.** Frames are written on all cores at once,
>    so "sort by date modified" mixed them up.
> 3. **Folders could silently mix runs.** Extracting a second recording, or the
>    same recording with another curve, crop or format, into a folder that
>    already held frames overwrote some and left the rest. The folder then held
>    two sequences under one numbering.
>
> **Re-extract any folder that may hold more than one run, or a recording longer
> than 100,000 frames, into an empty folder.** Pixel values were always correct.
> Only the order and the mixing were wrong.

## Frame names: one width per recording, any length

The frame number is zero-padded to `max(5, digits of the last possible frame
index)`, taken from the `.bin` size:

| frames in the recording | names |
|---|---|
| up to 100,000 | `brow_00000.Png` … `brow_99999.Png` (TimeViewer's 5 digits, unchanged) |
| 100,001 – 1,000,000 | `brow_000000.Png` … (6 digits) |
| 1,000,001 – 10,000,000 | 7 digits, and so on with no limit |

The width is the same for every frame and for every partial or resumed run of a
recording, so **name order is frame order** in every tool. The C engine, the
numpy fallback and the Pillow formats (WebP, JPEG 2000) use the same rule and
write identical names.

## File dates in frame order

Frame *i* of a run gets the modification time `start + i` milliseconds, on Linux
and Windows. "Sort by date" now gives frame order as well.

## One folder, one sequence

Every run writes a hidden `.opngx-run` file in its output folder. The file
records the recording (first timestamp, frame count, size) and the settings
(curve, bit depth, channels, format, quality, crop, naming). A later run into
that folder is allowed if both match, as when you re-run or extend the same
extraction. Otherwise:

- **Studio** (Extract and the batch window): asks whether to **use a new folder**
  (`…_2`) or **delete the old frames**. It deletes only the earlier opngx run's
  frames and files; anything else in the folder stays.
- **CLI / Python:** refuses with a message that names the folder and the source.
  `--allow-mixed` (CLI) or `allow_mixed=True` (`opngx.extract`) overrides this.
  `opngx.MixedOutputError` is raised in Python.

The engine and the Python paths write the same record, so a folder started by
one is continued by the other.

## Other fixes

- The numpy fallback no longer crashes when started from stdin or `python -c`
  (Python 3.14's forkserver could not start its worker processes). It now uses
  threads there, as JPEG 2000 already did.
- No more Pillow deprecation warning from the fallback's TIFF/BMP/JPEG writer.

## About the new recordings (B45 / C12 / G1.75)

The `water_engine` recordings were saved with brightness 45, contrast 12 and
gamma 1.75. opngx's pixel exactness is verified against TimeViewer for its
standard settings (B49 / C18 / G1), so the engine warns that this curve is
unverified. Use the `raw` mode for measurements. It writes the sensor values
untouched and does not depend on the curve.

## Verification

- **pytest 119/119** on 16 workers, deprecation warnings as errors, three
  consecutive runs. New tests:
  - names and dates in frame order across the 100,000-frame boundary (native,
    fallback, WebP);
  - the width rule for 10 to 1,000,001 frames, with the native names equal to
    the fallback names;
  - the folder guard on the native and fallback paths;
  - the studio's new-folder / delete-old-frames choice.
- **Engine suite 46/46** natively, with the Windows build under Wine, and under
  AddressSanitizer + UBSan.
- **Real data:** `engine_10s` (more than 100,000 frames) extracts with 6-digit
  names, and name order, date order and timestamp order are all the same on
  the engine, fallback and WebP paths.

## Assets

| File | What |
|---|---|
| `opngx-setup-v2.1.1.exe` | Windows installer: studio, engine, ffmpeg, docs, sample modules; uninstaller |
| `opngx-studio-portable-v2.1.1.exe` | Windows studio, single file, no install |
| `opngx-engine-v2.1.1.exe` | Windows CLI engine only |
| `opngx-2.1.1-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | Python package + C engine, Linux x86_64 |
| `opngx-2.1.1-py3-none-win_amd64.whl` | Python package + C engine, Windows amd64 |
| `opngx-2.1.1.tar.gz` | Python sdist (numpy fallback) |
| `opngx-2.1.1-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.1.1_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
