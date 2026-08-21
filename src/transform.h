/* transform.h — LUT construction and scanline expansion */
#ifndef OPNGX_TRANSFORM_H
#define OPNGX_TRANSFORM_H
#include <stdint.h>

/*
 * Vendor display transform (verified pixel-exact against reference exports):
 *   out = clamp(round_half_up((v + brightness) * (1 + contrast/50)), 0, 255)
 * Optional gamma applied afterwards on normalized range:
 *   out = round(255 * (out/255)^(1/gamma))
 * RAW mode = identity LUT.
 */
void opngx_build_lut8 (uint8_t  lut[256], double b, double c, double g);
void opngx_build_lut16(uint16_t lut[256], double b, double c, double g);

/* Expand W*H gray bytes into PNG scanlines (RGBA, filter byte 0 per row).
 * out must hold h*(w*4+1) resp. h*(w*8+1) bytes. */
void opngx_expand_rgba8 (const uint8_t *gray, uint32_t w, uint32_t h,
                         const uint8_t  lut[256], uint8_t *out);
void opngx_expand_rgba16(const uint8_t *gray, uint32_t w, uint32_t h,
                         const uint16_t lut[256], uint8_t *out);

/* Grayscale fast paths (color type 0): 4x less deflate input than RGBA,
 * identical pixel values. out holds h*(w*bytes_per_px+1). */
void opngx_expand_gray8 (const uint8_t *gray, uint32_t w, uint32_t h,
                         const uint8_t  lut[256], uint8_t *out);
void opngx_expand_gray16(const uint8_t *gray, uint32_t w, uint32_t h,
                         const uint16_t lut[256], uint8_t *out);
#endif
