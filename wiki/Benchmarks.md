# Benchmarks

Reference machine: AMD Ryzen 7 250 (8C/16T, AVX-512), 14 GiB DDR5, NVMe, Linux, libdeflate 1.25.
Workload: `brow_1_2.bin` — 3.84 GB, 50 000 frames, 256×300. Reproduce with:

```bash
./build/opngx-engine bench --bin <file>.bin --frames 4000 -j 16 -l 6
bash tests/test_engine.sh
```

## Threading (RGBA, level 6)

| jobs | fps |
|---:|---:|
| 1 | 204 |
| 4 | 770 |
| 8 | 1159 |
| 16 | ~1400 |

## Deflate level sweep (16 jobs)

| backend | level | fps | notes |
|---|---:|---:|---|
| libdeflate | 1 | ~5300 | burst |
| libdeflate | 3 | ~2300 | throughput sweet spot |
| libdeflate | **6** | **~1360** | default, vendor-like sizes |
| zlib | 6 | ~560 | fallback backend |

## Grayscale fast path (`--channels gray`)

| mode | fps | size/frame |
|---|---:|---:|
| rgba | 882 | 56 KB |
| gray | **2245** | 36 KB |

Pixels identical; only the container differs.

## Why not GPU?

Deflate dominates runtime and has no production ROCm library (hipCOMP is an unoptimized preview; nvCOMP is CUDA-only). 76 KB frames sit far below GPU viability thresholds on a bandwidth-shared iGPU. Details: [docs/BENCHMARKS.md](https://github.com/Shuvam-Banerji-Seal/opngx/blob/main/docs/BENCHMARKS.md).
