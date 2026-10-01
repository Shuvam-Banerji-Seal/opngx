# opngx v2.0.3 — Windows studio: module editor fixed, sample modules shipped, full-speed extraction

**Released:** 2026-10-01 · **ABI:** 5 (unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

A fix release for the **Windows studio**, from field reports on v2.0.x.
Extracted pixels are unchanged: every format and option gives byte-identical
output to v1.7.0 – v2.0.2, and PNGs stay pixel-identical to TimeViewer's.

---

## The module editor works in the Windows app

**Symptom:** clicking a built-in module in the Editor did nothing, and the
modules folder was empty.

**Cause:** the packaged `.exe` contains compiled code only. A built-in
module's file path points to a `.py` source that was never bundled, so the
Editor found no file and silently opened nothing. Duplicate (the way to
start from a built-in) failed the same way.

**Fix:** the built-in modules' sources are now bundled exactly where the
app looks for them. A packaged selftest on real Windows checks that every
built-in module's source exists.

## Sample modules and docs ship with the app

On first start the studio copies samples into your (empty) folders:
`%APPDATA%\opngx\modules` and `%APPDATA%\opngx\docs` on Windows, and
`~/.config/opngx/…` on Linux.

| sample module | shows |
|---|---|
| `example_bright_area` | params, columns, a frame overlay |
| `example_frame_difference` | state between batches (`parallel = False`), a summary |
| `example_background` | `begin()` with `ctx.sample()`, a parameter with choices |
| `example_track_speed` | `requires` (builds on `motion_tracking`), an extra table with its plot |

The folder also gets a `README.md` explaining each sample, and the docs folder
gets a sample doc for your own notes. All samples run on real recordings and
pass **Validate**.

- **Copied once.** They never overwrite your files, and a sample you delete
  stays deleted. **Editor → Restore samples** brings back only the missing ones.
- **Docs tab:** the app now bundles **every** guide (`STUDIO.md` was missing
  from v2.0.0–2.0.2) and all release notes. The build collects them by glob,
  so a new document can't be left out again.
- **From Python:** `opngx.analysis.seed_examples()` copies the samples, and
  `opngx.analysis.examples_dir()` holds the originals.

## Extraction runs at full speed on Windows

On a real Windows machine (the CI runner), the packaged studio used **368% of
400% CPU** on 4 cores. That's 323 frames/s, 116% of the bundled CLI. It was
not falling back to slow Python code. Two Windows-specific problems were
fixed in the engine anyway.

- **Power throttling.** Windows 10/11 "power throttling" (EcoQoS) slows the
  threads of a program whose window isn't in front, running them at low clocks
  or on efficiency cores. On a laptop, switching to another window during a long
  extraction made it look as if opngx had stopped using the CPU's full
  power. While an extraction runs, the engine now:
  - opts its process and every worker thread out of that throttling;
  - keeps the PC from sleeping;
  - restores the Windows defaults when it finishes.

  These APIs are looked up at run time, so older Windows versions simply skip them.
- **More than 64 threads crashed.** Windows can wait on at most 64 threads at
  once. With more than 65 workers, the engine's wait failed immediately and
  freed memory the workers were still using. The released v2.0.2 engine wrote 151 of 2,000
  frames at `-j 100` and then crashed. Waits are now chunked: 2,000 of 2,000 frames,
  pixel-exact.
- **Processor groups.** The thread count now covers all processor groups
  (`GetSystemInfo` saw at most 64 logical CPUs), and workers are spread across
  groups on machines with more than 64 logical CPUs.

**New packaged selftest:** `opngx-studio.exe --selftest-speed` times the same
recording three ways: the bundled CLI, the in-process API, and the studio's
Extract button. It reports frames/s, CPU use, threads and the DLL that
loaded. It runs in CI on real Windows, and fails if the studio falls behind
the CLI.

Writing many small PNGs also depends on the disk. If Windows Defender scans
every new file, adding the output folder to its exclusions can speed up large
runs noticeably.

## Is the smaller `.exe` missing anything?

No. It went from 133 MB (v1.9.0) to 74 MB, and the difference is only these unused pieces:

- a **second copy of ffmpeg** (88 MB uncompressed); the one the studio uses is still bundled;
- the software-OpenGL fallback, which the widgets UI never uses;
- the Qt Quick/QML/PDF/Network libraries and PySide's duplicate OpenSSL;
- Tcl/Tk (the old Tk UI isn't shipped) and PIL's AVIF codec.

Everything extraction needs is still there: the C engine DLL, the engine CLI,
Python's own OpenSSL/hashlib, numpy and Pillow. This release adds the module
sources, samples and docs the app had been missing.

## Also fixed

- **16-bit RGBA PNGs on the Python fallback.** The pure-Python fallback (used only
  when the C engine can't load) crashed on 16-bit RGBA PNGs and would have written
  alpha 255 of 65,535. Every PNG variant from the fallback (8/16-bit, RGBA/grey, with or
  without crop) now carries exactly the C engine's samples. A test compares the raw
  data directly, because PIL reduces 16-bit to 8 bits when it decodes.

## Verification

- pytest **98/98**:
  - AN-19 checks seeding (once, never overwrites, Restore puts back only what's missing);
  - AN-20 runs the four samples on a recording;
  - AN-21 checks the exe bundles sources, samples and docs;
  - a new fallback/native PNG parity test covers 8 variants.
- Engine suite **46/46** natively and **46/46** with the new Windows build.
- The Windows build is pixel-exact against TimeViewer at 16 and 100 threads.
- Packaged selftests on real Windows in CI (ui / engine / analysis with the new editor and
  samples checks / video / **speed**), plus the wheels and sdist install-tests.
- Layout audit clean at 1280×720 – 3840×2160 with the new Editor button.

## Assets

| File | What |
|---|---|
| `opngx-setup-v2.0.3.exe` | Windows installer: engine + Qt studio + ffmpeg + docs + sample modules |
| `opngx-studio-portable-v2.0.3.exe` | Windows studio, single file, no install |
| `opngx-engine-v2.0.3.exe` | Windows CLI engine only |
| `opngx-2.0.3-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | Python package + C engine, Linux x86_64 |
| `opngx-2.0.3-py3-none-win_amd64.whl` | Python package + C engine, Windows amd64 |
| `opngx-2.0.3.tar.gz` | Python sdist (numpy fallback) |
| `opngx-2.0.3-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.0.3_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
