/* transform.c — see transform.h
 *
 * Portability note: the expand kernels carry GCC target_clones so ONE binary
 * auto-selects AVX-512BW / AVX2 / baseline at runtime via ifunc on
 * glibc/x86-64. Other platforms run the portable scalar version. No
 * -march=native is required anywhere in shipped builds.
 */
#include "transform.h"
#include <math.h>
#include <string.h>

#if defined(__GNUC__) && !defined(__clang__) && defined(__ELF__) && defined(__x86_64__)
   /* ifunc-based runtime dispatch: glibc/Linux x86-64 only.
    * Other platforms run the portable -O3 autovectorized version. */
#  define OPNGX_MULTIVERSION(fn) \
     __attribute__((target_clones("arch=x86-64-v4","arch=x86-64-v3","default")))
#else
#  define OPNGX_MULTIVERSION(fn)
#endif

static double clampd(double x, double lo, double hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}

void opngx_build_lut8(uint8_t lut[256], double b, double c, double g) {
    const double mul = 1.0 + c / 50.0;
    for (int v = 0; v < 256; v++) {
        double x = clampd(floor((v + b) * mul + 0.5), 0.0, 255.0);
        if (g != 1.0 && g > 0.0)
            x = floor(255.0 * pow(x / 255.0, 1.0 / g) + 0.5);
        lut[v] = (uint8_t)x;
    }
}

void opngx_build_lut16(uint16_t lut[256], double b, double c, double g) {
    const double mul = 1.0 + c / 50.0;
    for (int v = 0; v < 256; v++) {
        double x = clampd(floor((v + b) * mul + 0.5), 0.0, 255.0);
        if (g != 1.0 && g > 0.0)
            x = floor(255.0 * pow(x / 255.0, 1.0 / g) + 0.5);
        /* scale to 16-bit container exactly like 8-bit value replication */
        lut[v] = (uint16_t)((uint8_t)x * 257u);
    }
}

OPNGX_MULTIVERSION(expand8)
void opngx_expand_rgba8(const uint8_t *gray, uint32_t w, uint32_t h,
                        const uint8_t lut[256], uint8_t *out) {
    uint32_t lut4[256];
    for (int v = 0; v < 256; v++)
        lut4[v] = 0xFF000000u | ((uint32_t)lut[v] * 0x01010101u);

    const size_t stride = (size_t)w * 4 + 1;
    memset(out, 0, (size_t)h * stride);           /* all filter bytes = 0 */
    for (uint32_t y = 0; y < h; y++) {
        uint8_t *row = out + (size_t)y * stride + 1;
        const uint8_t *src = gray + (size_t)y * w;
        for (uint32_t x = 0; x < w; x++) {
            uint32_t px = lut4[src[x]];
            memcpy(row + (size_t)x * 4, &px, 4);  /* compiles to one mov on LE */
        }
    }
}

OPNGX_MULTIVERSION(expand16)
void opngx_expand_rgba16(const uint8_t *gray, uint32_t w, uint32_t h,
                         const uint16_t lut[256], uint8_t *out) {
    const size_t stride = (size_t)w * 8 + 1;
    memset(out, 0, (size_t)h * stride);
    for (uint32_t y = 0; y < h; y++) {
        uint8_t *row = out + (size_t)y * stride + 1;
        const uint8_t *src = gray + (size_t)y * w;
        for (uint32_t x = 0; x < w; x++) {
            uint16_t v = lut[src[x]];             /* PNG wants big-endian */
            row[(size_t)x * 8 + 0] = (uint8_t)(v >> 8);
            row[(size_t)x * 8 + 1] = (uint8_t)(v);
            row[(size_t)x * 8 + 2] = (uint8_t)(v >> 8);
            row[(size_t)x * 8 + 3] = (uint8_t)(v);
            row[(size_t)x * 8 + 4] = (uint8_t)(v >> 8);
            row[(size_t)x * 8 + 5] = (uint8_t)(v);
            row[(size_t)x * 8 + 6] = 0xFF;
            row[(size_t)x * 8 + 7] = 0xFF;
        }
    }
}

OPNGX_MULTIVERSION(gray8)
void opngx_expand_gray8(const uint8_t *gray, uint32_t w, uint32_t h,
                        const uint8_t lut[256], uint8_t *out) {
    const size_t stride = (size_t)w + 1;
    memset(out, 0, (size_t)h * stride);
    for (uint32_t y = 0; y < h; y++) {
        const uint8_t *src = gray + (size_t)y * w;
        uint8_t *row = out + (size_t)y * stride + 1;
        for (uint32_t x = 0; x < w; x++)
            row[x] = lut[src[x]];
    }
}

OPNGX_MULTIVERSION(gray16)
void opngx_expand_gray16(const uint8_t *gray, uint32_t w, uint32_t h,
                         const uint16_t lut[256], uint8_t *out) {
    const size_t stride = (size_t)w * 2 + 1;
    memset(out, 0, (size_t)h * stride);
    for (uint32_t y = 0; y < h; y++) {
        const uint8_t *src = gray + (size_t)y * w;
        uint8_t *row = out + (size_t)y * stride + 1;
        for (uint32_t x = 0; x < w; x++) {       /* big-endian samples */
            uint16_t v = lut[src[x]];
            row[(size_t)x * 2 + 0] = (uint8_t)(v >> 8);
            row[(size_t)x * 2 + 1] = (uint8_t)v;
        }
    }
}
