# opngx v2.0.4 — 3–4× faster extraction, no delay after clicking Extract

**Released:** 2026-10-01 · **ABI:** 5 (unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

A performance release from field reports: "it doesn't use all the cores"
and "there is a delay between clicking Extract and the extraction starting".
Pixels are unchanged: all 250,000 frames of the five project recordings are
still pixel-identical to TimeViewer's exports.

---

## The delay after clicking Extract is gone

**Cause:** the studio exports per-frame timestamps by default. The engine
built that CSV with a **single-threaded pass over every frame header, before
any extraction started**.
- On Linux the kernel's read-ahead hid most of it, but a cold 3.6 GB recording
  still waited 1.3 s for its first frame.
- On Windows, memory-mapped files get far less read-ahead, so the pass meant
  thousands of scattered disk reads. That was seconds on an SSD, and much longer
  on a hard disk or a network drive.

**Fix:** the workers now record each frame's timestamp while they extract
that frame. They already have the header in hand, so this costs no extra I/O.
The CSV is written when they finish and is byte-identical to before. After a
cancel, it lists the frames that were extracted.

| full recording, cold cache, timestamps on | first PNG after |
|---|---:|
| v2.0.0 – 2.0.3 | 1.337 s |
| **v2.0.4** | **0.015 s** |

On a real Windows machine (CI), the packaged studio now writes its first frame
**9–61 ms** after Extract.

## 3–4× faster: compression level 1 by default

Almost all of the CPU time goes to DEFLATE. On this footage the old default
(level 6) bought almost nothing over level 1: the files were 1–2% smaller, at
3–4× the CPU. Measured on all five recordings (5,000 frames each, 16 threads):

| recording | level 1 (new default) | level 6 (old default) | size difference |
|---|---:|---:|---:|
| brow_1.2 | **7379 fps** | 1730 fps | +1.6% |
| brow_1_4 | **5366 fps** | 1743 fps | +1.6% |
| brow_1_6 | **6317 fps** | 1723 fps | +1.8% |
| brow_1_8 | **4958 fps** | 1728 fps | +1.7% |
| brow_2_0 | **6312 fps** | 1752 fps | +1.8% |

A whole 50,000-frame recording now takes **9.7 s instead of 31.1 s**.
- **Studio**, measured inside the packaged app on Linux: 1,160 → **5,114 frames/s**,
  using about 1,500% of 1,600% CPU.
- **Studio on real Windows**, measured in CI: 362 → 905–1,275 frames/s on 4 cores, about 2.5–3.5×.

The level is still adjustable everywhere: the studio's slider, `-l/--level`,
and `level=` in Python.
- `4`: the smallest files of the fast levels, smaller than 6.
- `7`–`12`: smallest files, much slower.

Pixels are identical at every level.

## Storage read-ahead

Mapped-file page faults read 4–64 KB at a time, one thread at a time, which
is far less than an SSD can deliver. Each worker now asks the OS to start
reading the chunk that will be processed one round later:
`PrefetchVirtualMemory` on Windows 8+, looked up at run time, and
`MADV_WILLNEED` on Linux. Storage then gets large, deep read requests.

## Windows: output files are not content-indexed

Output frames are created with `FILE_ATTRIBUTE_NOT_CONTENT_INDEXED`. If the
output folder is inside an indexed location (Documents, Desktop, …), Windows
Search no longer indexes tens of thousands of PNGs alongside the extraction.

If extraction on your machine is still limited by the disk, Windows Defender
scanning every new file is the usual cause. Adding the output folder to its
exclusions helps.

## How the speed is checked

`opngx-studio.exe --selftest-speed` runs the same recording through the
bundled CLI, the in-process API and the studio's Extract button. It reports
frames/s, CPU use and the time to the first frame, plus informational runs
with 2× and 3× more threads than cores. It runs in CI on real Windows, and
fails if the studio falls behind the CLI or takes more than 2 s to write its first frame.

What it showed on the 4-core Windows CI machine at the new speed: every path
runs at about 60% CPU, and extra threads don't help. That machine's disk and
filesystem throughput is the limit, not the engine.

## Verification

- pytest **100/100**. New tests cover:
  - the worker-captured timestamps: exact headers, frame order, a start offset, and a
    cancelled run;
  - the fast default level in the API, CLI, studio and engine.
- Engine suite **46/46** natively and **46/46** with the Windows build (under Wine).
- **AddressSanitizer + UBSan:** the engine suite, 89 Python tests against the
  instrumented library, and end-of-file runs at 1/7/33 threads are all clean.
- All **250,000** frames of the five recordings are pixel-exact against TimeViewer
  at the new default. The timestamp CSVs are byte-identical to v2.0.0's (full range,
  a start offset, and a crop).
- The packaged selftests pass on real Windows in CI (ui / engine / analysis / video / speed).
- The layout audit is clean at 1280×720 – 3840×2160.

## Assets

| File | What |
|---|---|
| `opngx-setup-v2.0.4.exe` | Windows installer: engine + Qt studio + ffmpeg + docs + sample modules |
| `opngx-studio-portable-v2.0.4.exe` | Windows studio, single file, no install |
| `opngx-engine-v2.0.4.exe` | Windows CLI engine only |
| `opngx-2.0.4-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | Python package + C engine, Linux x86_64 |
| `opngx-2.0.4-py3-none-win_amd64.whl` | Python package + C engine, Windows amd64 |
| `opngx-2.0.4.tar.gz` | Python sdist (numpy fallback) |
| `opngx-2.0.4-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.0.4_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
