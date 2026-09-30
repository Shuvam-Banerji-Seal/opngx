# opngx

<img src="assets/logo/wordmark.png" alt="opngx" width="360">

**Ultra-fast, pixel-exact extraction of Optronis TimeViewer `.bin` high-speed-camera footage to PNG — all CPU cores by default, GPU-aware, CLI + GUI + Python library.**

```
3.84 GB .bin ──▶ 50 000 PNGs in ~50 s  (16 threads, RGBA)
                 every frame verified pixel-exact against vendor exports
```

## Why opngx

| | vendor exporter | naive Python | **opngx** |
|---|---|---|---|
| throughput (RGBA) | slow, GUI-only | ~30 fps | **880–1400 fps** |
| raw/lossless mode (no highlight clipping) | ✗ | ✗ | ✓ |
| grayscale fast path (2.5× faster) | ✗ | ✗ | ✓ |
| direct MP4 render from .bin | ✗ | manual | ✓ |
| region-of-interest crop (pixel-exact) | ✗ | manual | ✓ |
| batch window with a preview per recording | ✗ | ✗ | ✓ |
| in-app frame viewer + verification | ✗ | ✗ | ✓ |
| per-frame timestamps + metadata JSON | ✗ | ✗ | ✓ |
| **motion tracking → trajectory data file** (sub-pixel, C kernel) | ✗ | manual | ✓ |
| **Brownian / optical-trap analysis** (MSD, PSD, stiffness) | ✗ | manual | ✓ |
| **write your own analysis modules in the app** (editor + docs) | ✗ | ✗ | ✓ |
| pixel-exact verification tool | ✗ | manual | built-in |
| runs anywhere (Intel/AMD/ARM, any OS) | ✗ | ✓ | ✓ |


## New in 2.0 — analysis modules

opngx turns recordings into **time-series data** as well as images, through
switchable **analysis modules** (plain Python, with C kernels on the hot path):

* **motion tracking** — the bright spot or ring's sub-pixel trajectory per frame
  (0.044 px RMS on a ring, 0.049 px on a spot, vs synthetic ground truth), ring
  radius, velocity, timed by the camera's frame clock; a 50 000-frame recording in ~7 s;
* **Brownian motion & trap analysis** — drift, MSD (D, α, localisation noise),
  power spectrum with corner frequency, trap stiffness, step statistics, and
  explicit warnings when the data is *not* a thermally driven trapped bead
  (it finds the 38.8 / 98 / 103 Hz lines in this project's recordings);
* **luminosity** and **contrast** over time;
* **your own** — the studio's **Editor** tab (tabs, find/replace, completion,
  validate, test on a recording) and the `Module` API
  ([`docs/ANALYSIS.md`](docs/ANALYSIS.md)); docs of every module are generated.

```bash
opngx analyze recording.bin -m motion_tracking -o trajectory.csv
opngx analyze Footages/ --batch -m brownian_motion -p brownian_motion.pixel_size_um=0.1 -o Results/
```

The studio has four tabs — **Extract · Analyze · Editor · Docs** — eight themes
(Midnight, Catppuccin Latte/Frappé/Macchiato/Mocha, Tokyo Night/Day,
Cappuccino, plus a custom accent), a zoomable pixel-exact viewer, a full crop editor,
and scales itself from 720p to 4K. See [`docs/STUDIO.md`](docs/STUDIO.md).

The reverse-engineered format and the proven transform are documented in
[`docs/FORMAT.md`](docs/FORMAT.md); measured performance in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

## Install

**Windows:** run `opngx-setup-v2.0.1.exe` from the
[latest release](https://github.com/Shuvam-Banerji-Seal/opngx/releases/latest)
(engine, studio, ffmpeg and docs, with Start-menu shortcuts), or use the portable
`opngx-studio-portable-v2.0.1.exe`.

**Python package (Linux x86_64 / Windows amd64, Python ≥ 3.9):** the release
wheels include the compiled C engine, so there's nothing to build:

```bash
pip install https://github.com/Shuvam-Banerji-Seal/opngx/releases/download/v2.0.1/opngx-2.0.1-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
pip install "opngx[qt] @ https://github.com/Shuvam-Banerji-Seal/opngx/releases/download/v2.0.1/opngx-2.0.1-py3-none-win_amd64.whl"   # + studio
```

The Linux wheel runs on any distro with glibc ≥ 2.17 (CentOS 7 and newer). On glibc < 2.28,
pip picks an older NumPy that still ships wheels there. The sdist
(`opngx-2.0.1.tar.gz`) installs anywhere, with the numpy fallback.

**From source:**

```bash
# engine (C17 + OpenMP; libdeflate recommended, zlib fallback)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j

# python package (wraps the C engine via ctypes; numpy fallback included)
cd python && uv sync --all-extras      # adds `opngx` and `opngx-ui` commands
source .venv/bin/activate              # or prefix with `uv run`
```

No `-march=native` is used: one binary runs on any x86-64 (Intel or AMD, any
generation) and ARM64, and automatically upgrades its SIMD kernels
(AVX-512 → AVX2 → baseline) at runtime.

## Quick start

```bash
# CLI (python front-end)
opngx info   recording.bin                      # metadata, GPUs, CPUs
opngx extract recording.bin -o frames/          # vendor-identical PNGs
opngx extract recording.bin -o frames/ \
    --mode raw --bit-depth 16 --timestamps --metadata -j $(nproc)
opngx verify reference_dir/ frames/ --subset    # pixel-exact proof
opngx verifybin --bin recording.bin frames/     # prove vs source, no refs needed
opngx verify ref_dir/ frames/ --json            # machine-readable report

# batch: mother folder → structured output tree
# input mother folder layout (one sub-folder per recording):
#   Footages/
#     SQ_100_s1/  SQ_100_s1.bin  SQ_100_s1.footage
#     SQ_100_s2/  SQ_100_s2.bin  SQ_100_s2.footage
opngx batch Footages/ -o FramesOut/ --layout format --format png -j 16
# → FramesOut/SQ_100_s1/PNG/*.Png
# → FramesOut/SQ_100_s2/PNG/*.Png
# Every quality flag `extract` accepts works here too, and applies to the
# WHOLE batch:
opngx batch Footages/ -o FramesOut/ --mode custom \
    --brightness 20 --contrast 30 --gamma 2.0 --channels gray
# …and so does a crop, for every recording at once:
opngx batch Footages/ -o FramesOut/ --crop 100,80,512,384

# standalone C binary (no python needed)
./build/opngx-engine batch --in-dir sbs/bin/ --out-root out_root/ \
    --layout format -j 16 --mode custom --gamma 2.0 --crop 0,0,256,256

# GUI — opngx studio (Qt)
opngx-ui          # black / coffee-green theme, frame viewer,
                   # video rendering, drag & drop, live progress
                   # Batch: click "Batch folder" → Browse now opens a
                   # FOLDER picker (select the mother folder above).
                   # Output mirrors it: <out>/<recording>/PNG|JPG|BMP|TIF|MP4/
                   # Also: drag & drop a folder → Batch, a .bin → Single.
                   # "Batch window…" is a multi-pane window: a card per
                   # recording, a large Preview of the selected one (own
                   # scrubber, crop overlay, pixel readout), Compare (every
                   # recording side by side at the same point in time) and
                   # Progress & log. Each pane collapses (▾), pops out into
                   # its own window (⧉), goes full screen (⛶, Esc to return)
                   # or hides (✕, back via View). F11 = whole window full
                   # screen, F10 = Preview full screen. Layout is remembered.
                   # The settings above apply to every recording.
                   # The UI scales itself to the monitor (720p .. 4K);
                   # override in View → Interface scale.
                   # "Crop…" opens a picker: drag to draw, drag inside to
                   # move, drag an edge/corner to resize (or type x/y/w/h),
                   # then apply it to this recording or every one it fits.
                   # Cropping selects pixels, never resamples, so it is
                   # pixel-exact and verifybin agrees.
                   # Reference mode: each recording uses the B/C/G from
                   # its OWN .footage (shown on its batch card). Editing a
                   # value switches to custom = one curve for all.

# Region of interest — pure pixel selection, no resampling
opngx extract recording.bin -o frames/ --crop 100,80,512,384
# output is 512x384; pixel (x,y) == LUT(source[crop_x+x, crop_y+y])
# W or H of 0 means "to the frame edge": --crop 100,80,0,0

Requires PySide6 for the Qt edition ('pip install "opngx[qt]"');
falls back to a Tkinter UI when absent.

# Video — straight from a .bin, no intermediate files
opngx video recording.bin -o clip.mp4 --fps 30 --crf 18 \
    --start 0 --frames 500 -m reference
# v1.8: same curve and crop options as extract (odd crop sizes are padded
# by one black row/column, since H.264 needs even dimensions)
opngx video recording.bin -o roi.mp4 -m custom --gamma 1.6 --crop 17,23,151,201
```

Python API:

```python
import opngx

meta = opngx.probe("recording.bin")             # geometry, fps, settings
st = opngx.extract("recording.bin", "frames/", mode="raw", jobs=0,
                   timestamps=True, progress=lambda d,t: print(f"{d}/{t}"))

# v1.7: crop a region, and/or override the vendor transform
st = opngx.extract("recording.bin", "roi/", mode="custom",
                   brightness=20, contrast=30, gamma=2.0,
                   crop=(100, 80, 512, 384))

rep = opngx.verify("reference_dir/", "frames/") # pixel-exact check
rep = opngx.verify_against_bin("recording.bin", "roi/", crop=(100,80,512,384))
print(st, rep, sep="\n")
```

## Quality modes

| mode | what you get |
|---|---|
| `reference` *(default)* | byte-for-byte the vendor display transform — verified pixel-exact against sample exports. Brightness/contrast/gamma come from **each recording's own `.footage`** (decimal commas such as `1,5` are understood) |
| `raw` | identity LUT — sensor-faithful; preserves highlights the vendor export clips at raw ≥ 139 |
| `custom` | your brightness/contrast/gamma |

Add `--bit-depth 16` for a 16-bit container (values ×257) and
`--channels gray` for the colortype-0 fast path (identical pixels, 2.5× faster,
36% smaller). Optional upscaling is deliberately **not** silently applied:
resampling creates no new information and would break verifiability.

## How it uses your hardware

* **All cores, always on**: an OpenMP pool consumes frames dynamically
  (`OMP_PROC_BIND=close` set automatically when unset).
* **GPU**: detected and reported (`opngx info`). Compression — the actual
  bottleneck — has no production ROCm library (hipCOMP is an unoptimized
  preview; nvCOMP is CUDA-only), so the hot path stays on the SIMD-dispatched
  CPU where it is measurably fastest for 76 KB frames. See
  [benchmarks](docs/BENCHMARKS.md#why-not-gpu).

## Verification guarantee

`opngx verify` decodes both directories' PNG streams, reconstructs rows through
the full PNG filter pipeline (None/Sub/Up/Average/Paeth) and compares decoded
pixels — proving equality independent of encoder, zlib build, or container
layout. The full 50 000-frame reference set passes with zero mismatches.

## Development

```bash
bash tests/test_engine.sh            # 16 end-to-end + edge-case gates
(cd python && uv sync --all-extras && uv run pytest tests -q)
./build/opngx-engine bench --bin X.bin --frames 4000 -j 16
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the wiki for format internals,
ABI notes, and tuning guides.

## License

MIT — see [LICENSE](LICENSE).
