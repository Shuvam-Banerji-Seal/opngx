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
pip install ./python          # adds `opngx` and `opngx-ui` commands
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

# standalone C binary (no python needed)
./build/opngx-engine batch sbs/bin/ -o out_root/ -j 16

# GUI
opngx-ui
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
python -m pytest python/tests -q     # 12 package tests
./build/opngx-engine bench --bin X.bin --frames 4000 -j 16
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the wiki for format internals,
ABI notes, and tuning guides.

## License

MIT — see [LICENSE](LICENSE).
