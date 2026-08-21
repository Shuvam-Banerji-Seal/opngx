/* cpu.c — see cpu.h */
#include "cpu.h"
#include <stdio.h>
#include <string.h>

#if defined(__x86_64__) || defined(_M_X64)
#include <cpuid.h>  /* GCC/Clang __builtin_cpu_supports wrapper header */

void opngx_cpu_detect(opngx_cpu_features *f) {
    memset(f, 0, sizeof *f);
    __builtin_cpu_init();
    f->sse2     = __builtin_cpu_supports("sse2");
    f->ssse3    = __builtin_cpu_supports("ssse3");
    f->sse41    = __builtin_cpu_supports("sse4.1");
    f->avx      = __builtin_cpu_supports("avx");
    f->avx2     = __builtin_cpu_supports("avx2");
    f->avx512bw = __builtin_cpu_supports("avx512bw");
}
#else
void opngx_cpu_detect(opngx_cpu_features *f) {
    memset(f, 0, sizeof *f);
#if defined(__aarch64__) || defined(_M_ARM64)
    f->neon = 1;
#endif
}
#endif

size_t opngx_cpu_summary(char *buf, size_t cap) {
    opngx_cpu_features f;
    opngx_cpu_detect(&f);
    size_t off = 0;
#if defined(__aarch64__)
    off += (size_t)snprintf(buf + off, cap - off, "ARM64 NEON:%d", f.neon);
#elif defined(__x86_64__)
    if (f.sse2)                off += (size_t)snprintf(buf+off, cap-off, "SSE2 ");
    if (f.ssse3)               off += (size_t)snprintf(buf+off, cap-off, "SSSE3 ");
    if (f.sse41)               off += (size_t)snprintf(buf+off, cap-off, "SSE4.1 ");
    if (f.avx)                 off += (size_t)snprintf(buf+off, cap-off, "AVX ");
    if (f.avx2)                off += (size_t)snprintf(buf+off, cap-off, "AVX2 ");
    if (f.avx512bw)            off += (size_t)snprintf(buf+off, cap-off, "AVX512BW ");
#else
    off += (size_t)snprintf(buf + off, cap - off, "generic");
#endif
    if (off && buf[off-1] == ' ') off--;
    if (off < cap) buf[off] = '\0';
    return off;
}
