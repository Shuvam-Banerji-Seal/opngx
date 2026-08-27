# opngx

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
| in-app frame viewer + verification | ✗ | ✗ | ✓ |
| per-frame timestamps + metadata JSON | ✗ | ✗ | ✓ |
| pixel-exact verification tool | ✗ | manual | built-in |
| runs anywhere (Intel/AMD/ARM, any OS) | ✗ | ✓ | ✓ |

The reverse-engineered format and the proven transform are documented in
[`docs/FORMAT.md`](docs/FORMAT.md); measured performance in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

## Install

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

# standalone C binary (no python needed)
./build/opngx-engine batch --in-dir sbs/bin/ --out-root out_root/ --layout format -j 16

# GUI — opngx studio (Qt)
opngx-ui          # black / coffee-green theme, frame viewer,
                   # video rendering, drag & drop, live progress
                   # Batch: click "Batch folder" → Browse now opens a
                   # FOLDER picker (select the mother folder above).
                   # Output mirrors it: <out>/<recording>/PNG|JPG|BMP|TIF|MP4/
                   # Also: drag & drop a folder → Batch, a .bin → Single.

Requires PySide6 for the Qt edition ('pip install "opngx[qt]"');
falls back to a Tkinter UI when absent.

# Video — straight from a .bin, no intermediate files
opngx video recording.bin -o clip.mp4 --fps 30 --crf 18 \
    --start 0 --frames 500 -m reference
```

Python API:

```python
import opngx

meta = opngx.probe("recording.bin")             # geometry, fps, settings
st = opngx.extract("recording.bin", "frames/", mode="raw", jobs=0,
                   timestamps=True, progress=lambda d,t: print(f"{d}/{t}"))
rep = opngx.verify("reference_dir/", "frames/") # pixel-exact check
print(st, rep, sep="\n")
```

## Quality modes

| mode | what you get |
|---|---|
| `reference` *(default)* | byte-for-byte the vendor display transform — verified pixel-exact against sample exports |
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
