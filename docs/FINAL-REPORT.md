# opngx — Final Report

**Repo:** https://github.com/Shuvam-Banerji-Seal/opngx
**Version:** 1.7.0 · **License:** MIT · **CI:** green (Linux gcc/clang × libdeflate/zlib-only + native Windows msys2)

## 1. What was built

A production-grade, cross-platform system that extracts PNG frames from
Optronis TimeViewer `.bin` high-speed-camera footage — faster than any
alternative available, provably pixel-exact against the vendor exporter.

| Layer | Tech | Highlights |
|---|---|---|
| Engine (C17) | OpenMP, mmap, libdeflate/zlib, hand-rolled PNG writer | all cores by default; runtime SIMD dispatch (x86-64-v3/v4 clones); LTO |
| Python package | ctypes bindings + numpy fallback | `pip`/`uv` installable; CLI `opngx`; Tk GUI `opngx-ui` |
| Tooling | verify / bench / batch / info subcommands; CI; wiki-in-docs | pixel-exact proof built into the product |

## 2. Reverse-engineered format (docs/FORMAT.md)

* Frame = `[u64 LE timestamp][W×H bytes]`, stride 8+W·H, no global header.
  Proven: frame 0 timestamp equals the XML `TimeMarkerReference`.
* Vendor display transform recovered and **proven**:
  `out = clamp(round_half_up((v+B)·(1+C/50)), 0, 255)` at B=49/C=18 —
  100% of sampled pixels match vendor exports across all five bins.
* Discovered fidelity loss in vendor exports (highlight clipping raw≥139)
  and exposed it as a feature: **raw mode** preserves what the vendor throws away.

## 3. Correctness evidence

* **38 shell gates + 60 pytest tests**, all green on **both** the Linux
  build and the Windows build under **Wine** (cycle 22): synthetic fixtures
  computed independently via PIL, saturation boundaries, 16-bit scaling, gray
  path, Paeth/unfilter edge cases, truncation, jobs determinism, corruption
  detection, zlib-backend round-trip (CRC-checked), start-range parity, batch
  structured tree (layout=format) with JPG decode, spaces & non-ASCII
  (UTF-8) output dirs, Windows backslash+drive-letter paths, **batch quality
  flags**, **ROI crop pixel-exactness + verifier parity**, and **crop
  validation**.

### Cycle 22 — batch correctness audit

A field report ("the whole batch is not getting applied") decomposed into
**three independent defects plus a data-loss bug found by the bug hunt**,
each reproduced before it was fixed:

| Finding | Root cause | Gate |
|---|---|---|
| `reference` mode discarded the user's B/C/G | engine overwrote all three with sidecar values; the preview honoured them, so **the viewer lied about the file** | AR-17 / AR-18 |
| `opngx-engine batch` rejected `--brightness/--contrast/--gamma/--channels/--bit-depth/--jpeg-quality` and hardcoded `gamma = 1.0` | the subcommand had a hand-rolled parser with a fraction of `extract`'s surface | T-22, AR-20 |
| `opngx batch --layout` was an argparse error, and the layout branch imported a non-existent `_run_out_dir` from the Qt module | flags never registered; `getattr` hid the gap until runtime | AR-19 |
| **data loss**: two recordings sharing a `.bin` filename overwrote each other (16 frames extracted, 8 on disk) | output folder keyed on the *filename* instead of the recording *folder* | AR-21, AR-22 |

The new transform rule — *an explicitly supplied value always wins; the
sidecar fills in only the fields left alone* — is implemented in the Python
extractor, the C job creation path **and** the verifier, so extraction and
verification cannot drift apart. It required turning an on/off switch into a
per-field bitmask, because `brightness=0, contrast=0, gamma=1` are both
legitimate defaults *and* legitimate user choices.

* Real-data validation: full 50,000-frame bin → **50,000/50,000 pixel-exact**
  (15.36 GB of scanlines proven equal) plus full-bin verifybin against the
  source bin (no vendor refs needed); subsets of all 5 bins pass.
* Windows build verified under Wine: synthetic + real-data pixel-exact
  (27/27 Linux + 27/27 Wine). Packaged selftests (UI/Engine/Video) green
  on the real Windows runner.
* Batch mother-folder architecture: `<mother>/<recording>/PNG|JPG|BMP|TIF|MP4/`
  — mirrors input `Footages/<recording>/{.bin,.footage}` to output;
  scope-aware Browse (folder vs file) + drag&drop + flat back-compat.

## 4. Performance (Ryzen 7 250, 8C/16T)

| Path | Throughput | vs baseline |
|---|---:|---|
| zlib single-thread (industry default approach) | ~200 fps | 1× |
| libdeflate × 16 threads, RGBA L6 | ~1,360 fps | ~7× |
| grayscale fast path, same quality tier | **~2,245 fps** | ~11× |
| level-1 burst | ~5,300 fps | ~26× |

Full bin (3.84 GB → 50k PNGs): **50 s extract + 21 s verify**.

## 5. GPU honesty statement

GPU detection is reported (`opngx info`). The hot path stays on CPU because
(a) AMD hipCOMP is an unoptimized technology preview per its own release
notes, (b) nvCOMP is CUDA-only, (c) 76 KB frames sit far below GPU viability
thresholds on bandwidth-shared iGPUs. Re-evaluation documented in
docs/BENCHMARKS.md#why-not-gpu.

## 6. Independent audit & remediation

An independent survey agent audited every source file and returned 22
findings. All are fixed and regression-tested, notably:

* **CRITICAL** zlib backend double-wrapped streams (silent corruption in
  zlib-only builds) → raw-deflate rewrite + decode test.
* **CRITICAL** `--backend zlib` aborted on libdeflate builds → honored everywhere.
* HIGH CRC-table data race, Windows DLL exporting nothing, UAF on callback
  exceptions, wrong frame indexing for `start>0` in the fallback engine.
* CI now covers the zlib-only build and a native Windows job — both legs
  caught additional defects during bring-up.

## 7. Remaining known limitations

* Wiki git repo requires one manual web-UI page creation (GitHub has no API);
  content ships in `docs/` meanwhile.
* Transform formula verified only at B=49/C=18/G=1 operating point; other
  settings emit an explicit fidelity warning.
* Byte-level file identity with the vendor exporter is impossible across
  zlib builds (different DEFLATE encodings); pixel equality is the criterion.
