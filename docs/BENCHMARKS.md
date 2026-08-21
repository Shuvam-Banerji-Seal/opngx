# Benchmarks

All numbers measured on the reference machine:

| Component | Detail |
|---|---|
| CPU | AMD Ryzen 7 250 — 8C/16T Zen 4-class, up to 5.13 GHz, AVX-512 |
| RAM | 14 GiB DDR5 (single SO-DIMM channel pair) |
| SSD | NVMe (system disk) |
| GPU | AMD Radeon 780M iGPU (gfx1103), ROCm 7.2 present |
| OS | Linux, gcc 16.2, libdeflate 1.25 |

Workload: `brow_1_2.bin` — 3.84 GB, 50 000 frames, 256×300, vendor-equivalent
RGBA output unless noted. "fps" = frames/s; "in" = input bytes consumed.

## Scaling with threads (RGBA, level 6, libdeflate)

| jobs | fps | MiB/s in |
|---:|---:|---:|
| 1 | 204 | 15.0 |
| 2 | 462 | 33.9 |
| 4 | 770 | 56.4 |
| 8 | 1159 | 85.0 |
| 16 | 1359–1400 | 99.5+ |

Scaling to 8 physical cores is near-ideal for the memory stages; deflate's
hash-table working sets share L3, and SMT adds ~25–35% on top.

## Deflate level sweep (RGBA, 16 jobs, real footage)

| backend | level | fps | notes |
|---|---:|---:|---|
| libdeflate | 1 | ~5300 | fastest; ≈ same size as L6 on this footage |
| libdeflate | 2 | ~2700 | |
| libdeflate | 3 | ~2300 | sweet spot for throughput |
| libdeflate | **6** | **~1360** | default; size parity with vendor export (~56 KB/frame) |
| libdeflate | 9 | ~266 | smallest files (~49 KB/frame) |
| zlib | 6 | ~560 | 2.4× slower than libdeflate at same level |

**Rule of thumb:** `--level 6` reproduces vendor-like sizes; drop to
`--level 2` when speed matters more than a few % of file size.

## Grayscale fast path (`--channels gray`, level 6, 16 jobs, 4000 frames)

| mode | fps | size/frame | note |
|---|---:|---:|---|
| rgba | 882 | 56 KB | colortype 6, matches vendor container |
| gray | **2245** | 36 KB | colortype 0; pixels identical, 2.5× faster |

Gray mode compresses 77 KB instead of 307 KB per frame — deflate dominates
runtime, hence the near-linear win. Pixels are provably identical; only the
container differs (verified by cross-layout verification).

## Full-bin production run

```
brow_1_2.bin → 50 000 PNGs, RGBA, level 6, 16 jobs:
  extract : 50.5 s   (990 fps sustained incl. sidecar exports)
  verify  : 20.9 s   (50 000/50 000 files pixel-exact, 15.36 GB scanlines)
```

## Why not GPU?

The Radeon 780M (and iGPUs generally) shares system DDR5 bandwidth with the
CPU. Deflate — the bottleneck — has no mature ROCm implementation:
AMD's hipCOMP is an early-access preview whose own release notes state AMD
implementations are *experimental and not performance-optimized*;
NVIDIA's nvCOMP is CUDA-only. For 76 KB frames, kernel-launch and transfer
overheads exceed compute time. The pixel-transform stage (<1% of runtime) was
therefore kept on the SIMD-dispatched CPU path, which auto-selects AVX-512/
AVX2/base via GCC target_clones at runtime — no `-march=native` needed.
GPU detection is reported by `opngx info`; re-evaluate if hipCOMP matures or
on discrete-GPU NVIDIA systems where nvCOMP could offload larger tiles.

Reproduce any table:

```bash
./build/opngx-engine bench --bin <file>.bin --frames 4000 -j 16 -l 6 [--backend zlib]
bash tests/test_engine.sh          # correctness gates used before timing
```
