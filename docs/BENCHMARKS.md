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

## Re-measured v1.5.0 (brow_1_4.bin, 4000-frame windows)

Engine changes since the tables above (dead per-job scratch removal, by-name
verifier) moved real numbers; per-bin content also shifts results:

| config | v1.4 docs (brow_1_2) | v1.5.0 measured (brow_1_4) |
|---|---:|---:|
| RGBA L6 j16 | ~1360–1400 fps | **2046 fps** |
| RGBA L3 j16 | ~2300 fps | 2353 fps |
| RGBA L1 j16 | ~5300 fps | 2477 fps |
| gray L6 j16 | 2245 fps | 1785 fps |

Two honest observations:

* **RGBA L6 gained ~46%** — removing a dead W·H·3+64 KB scratch allocation
  per worker (cycle 10) plus allocator behaviour accounts for the jump.
* **The gray fast path is content-dependent.** On high-entropy footage the
  R=G=B replication inside RGBA rows gives DEFLATE long literal runs, which
  can beat the smaller-but-denser gray stream. Choose `gray` for size and
  decode speed; benchmark both on YOUR footage before assuming throughput.

Thread scaling at L6 on this bin: 4→1190 · 8→1750 · 12→2034 · 16→2046 fps
(saturates around physical cores; SMT adds little once deflate caches fill).

## v1.6.1 — SIMD checksums (libdeflate crc32/adler32)

The zlib container's adler32 runs over the UNCOMPRESSED scanlines
(76–307 KB/frame) and the IDAT CRC over the compressed block — both were
table-driven. Delegating to libdeflate's SIMD checksums (byte-identical
output, same algorithms) moved the burst tiers hard (brow_1_4, 4000
frames, j16, best-of-2):

| config | v1.6.0 | v1.6.1 | gain |
|---|---:|---:|---:|
| L1 gray  | 5610 fps | **8557 fps** | **+53%** |
| L1 rgba  | 2796 fps | **3535 fps** | **+26%** |
| L6 gray  | 2135 fps | **2518 fps** | **+18%** |
| L6 rgba  |  983 fps |  1009 fps |  +3% |

## Storage bottleneck experiment (v1.6.1)

NVMe vs tmpfs, same runs — the disk is NOT the bottleneck at any tier:

| config | NVMe | tmpfs |
|---|---:|---:|
| L6 rgba | 983 | 983 |
| L6 gray | 2135 | 2128 |
| L1 rgba | 2796 | 2846 |
| L1 gray | 5610 | 5774 |

Raw sequential bin read: ~1.5 GB/s; 2000×55 KB file creation: ~9 300
files/s — both far above every extract tier. Memory: mmap read-only +
per-worker steady-state buffers (zero per-frame allocation since v1.5).

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

## Cross-platform builds (cycle 2)

| Target | Toolchain | Backend | Status |
|---|---|---|---|
| Linux x86-64 | gcc 16, LTO, runtime AVX-512/AVX2 dispatch | libdeflate 1.25 | 16/16 tests, full-bin verify PASS |
| Windows x86-64 | mingw-w64 gcc 16.1, LTO, static libgomp+libdeflate | static libdeflate | fixture + real-data subset PASS under Wine |

Windows CLI is fully static apart from system DLLs (KERNEL32/USER32/UCRT) —
no `libgomp-1.dll` hunting. Runtime CPU feature detection reports the host's
capabilities (`opngx info`), e.g. `SSE2 SSSE3 SSE4.1 AVX AVX2 AVX512BW`.

## Grayscale fast path — measured on real footage (4000 frames, L6, 16 jobs)

| mode | fps | size/frame |
|---|---:|---:|
| rgba | 882 | 56 KB |
| gray | **2245** | 36 KB |
