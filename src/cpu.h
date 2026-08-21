/* cpu.h — runtime CPU feature detection (portable, no compile-time arch lock-in)
 *
 * The shipped binary must run on ANY x86-64 (Intel/AMD, any generation) and
 * any ARM64 machine. SIMD speedups are selected at RUNTIME:
 *   - on GCC/glibc x86-64 we use target_clones multi-versioning
 *   - everywhere else the portable scalar path runs
 * This header exposes detection results for reporting and for choosing
 * kernels manually where multiversioning is unavailable.
 */
#ifndef OPNGX_CPU_H
#define OPNGX_CPU_H
#include <stddef.h>

typedef struct {
    int sse2;        /* baseline on x86-64 */
    int ssse3;
    int sse41;
    int avx;
    int avx2;
    int avx512bw;    /* byte/word AVX-512 — the useful one for LUT work */
    int neon;        /* ARM64 */
} opngx_cpu_features;

/* Fill feature flags via cpuid/sysctl. Safe on all architectures. */
void opngx_cpu_detect(opngx_cpu_features *f);

/* Human-readable one-line summary, e.g. "x86-64: SSE4.1 AVX2 AVX-512BW". */
size_t opngx_cpu_summary(char *buf, size_t cap);

#endif
