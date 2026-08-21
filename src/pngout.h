/* pngout.h — PNG container assembly + checksums + zlib wrapper */
#ifndef OPNGX_PNGOUT_H
#define OPNGX_PNGOUT_H
#include <stddef.h>
#include <stdint.h>

uint32_t opngx_crc32(uint32_t crc, const void *buf, size_t len);
uint32_t opngx_adler32(const void *buf, size_t len);

/* Exact assembled file size for a given IDAT payload length. */
size_t opngx_png_size(size_t idat_len);

/* Assemble a full PNG into out; returns bytes written.
 * color_type: 6 = RGBA (4 or 8 bytes/px), 0 = grayscale (1 or 2 bytes/px).
 * out must hold opngx_png_size(idat_len). */
size_t opngx_png_assemble(uint8_t *out, uint32_t w, uint32_t h, int bit_depth,
                          int color_type, const uint8_t *idat, size_t idat_len);

/* Wrap raw deflate data into a zlib stream (header 0x78 0x5E + adler32 of
 * the UNCOMPRESSED payload). dst must hold deflate_len+6 bytes.
 * Returns stream length or 0 if dst too small. */
size_t opngx_zlib_wrap(uint8_t *dst, size_t dst_cap,
                       const uint8_t *deflate_data, size_t deflate_len,
                       const uint8_t *uncompressed, size_t uncomp_len);
#endif
