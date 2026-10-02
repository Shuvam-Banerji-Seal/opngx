/* encode.h — non-PNG output format encoders */
#ifndef OPNGX_ENCODE_H
#define OPNGX_ENCODE_H
#include <stddef.h>
#include <stdint.h>

/* 8-bit paletted grayscale BMP. Bottom-up rows per spec.
 * Returns bytes written or 0 if cap too small. */
size_t opngx_encode_bmp_gray(const uint8_t *gray, uint32_t w, uint32_t h,
                             uint8_t *out, size_t cap);

/* Baseline uncompressed little-endian TIFF.
 * gray!=0 -> 1 sample/pixel photometric=1; else RGB 3 samples.
 * Returns bytes written or 0. */
size_t opngx_encode_tiff(const uint8_t *pixels, uint32_t w, uint32_t h,
                         int gray, uint8_t *out, size_t cap);

/* Baseline JPEG from 8-bit gray (expanded internally to RGB).
 * quality 1..100. Returns bytes written or 0. */
/* 16-bit grey TIFF (uncompressed, little-endian). */
size_t opngx_encode_tiff16_gray(const uint16_t *px, uint32_t w, uint32_t h,
                                uint8_t *out, size_t cap);
/* Binary PGM (P5): pass px8 for 8-bit, or px16 (and px8 = NULL) for 16-bit. */
size_t opngx_encode_pgm(const uint8_t *px8, const uint16_t *px16,
                        uint32_t w, uint32_t h, uint8_t *out, size_t cap);
size_t opngx_encode_jpg(const uint8_t *gray, uint32_t w, uint32_t h,
                        int quality, uint8_t *out, size_t cap);

#endif
