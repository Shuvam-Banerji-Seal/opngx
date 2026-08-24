# opngx v1.6.1 — performance: SIMD checksums + the storage answer

**Developer:** Shuvam Banerji Seal

## Is the NVMe the bottleneck? No — measured.
NVMe vs RAM-disk at every tier differs by 0–3% (noise), sequential bin
read runs at ~1.5 GB/s, and creating 55 KB files sustains ~9 300/s —
all far above extraction speeds. The bottleneck is CPU, and inside it
our own checksums.

## SIMD checksums (byte-identical output)
The zlib container's adler32 runs over the *uncompressed* scanlines
(76–307 KB/frame) and the IDAT CRC over the compressed block — both were
table-driven. They now delegate to libdeflate's SIMD implementations
when linked (identical algorithms, identical bytes — every gate green):

| config (j16, brow_1_4) | v1.6.0 | v1.6.1 | gain |
|---|---:|---:|---:|
| L1 gray  | 5 610 fps | **8 557 fps** | **+53%** |
| L1 rgba  | 2 796 fps | **3 535 fps** | **+26%** |
| L6 gray  | 2 135 fps | **2 518 fps** | **+18%** |
| L6 rgba  |   983 fps |  1 009 fps |  +3% |

Burst tier (L1 gray) is now **8.5 kHz** — a full 50k-frame recording in
under 6 seconds of pure extraction.

Memory management remains mmap read-only + per-worker steady-state
buffers (zero per-frame allocation); the verifier reuses per-worker
decode slots (v1.5.4).
