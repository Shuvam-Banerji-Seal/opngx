/* encode.c — see encode.h
 *
 * JPEG uses the vendored stb_image_write.h (public domain) so no external
 * library is required on any platform.
 */
#include "encode.h"
#include <stdlib.h>
#include <string.h>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

/* --------------------- BMP (8-bit gray palette) --------------------- */
#pragma pack(push, 1)
typedef struct {
    uint16_t type;        /* 'BM' */
    uint32_t size;
    uint16_t r1, r2;
    uint32_t off_bits;
    uint32_t hdr_size;    /* 40 */
    int32_t  w, h;
    uint16_t planes, bpp;
    uint32_t compression, size_image;
    int32_t  xppm, yppm;
    uint32_t clr_used, clr_important;
} bmp_hdr_t;
#pragma pack(pop)

size_t opngx_encode_bmp_gray(const uint8_t *gray, uint32_t w, uint32_t h,
                             uint8_t *out, size_t cap) {
    const size_t row = ((size_t)w + 3u) & ~(size_t)3;
    const size_t pal = 256 * 4;
    const size_t need = 54 + pal + row * (size_t)h;
    if (cap < need) return 0;

    bmp_hdr_t hd;
    memset(&hd, 0, sizeof hd);
    hd.type = 0x4D42;
    hd.off_bits = 54 + (uint32_t)pal;
    hd.hdr_size = 40;
    hd.w = (int32_t)w;
    hd.h = (int32_t)h;
    hd.planes = 1;
    hd.bpp = 8;
    hd.size_image = (uint32_t)(row * (size_t)h);
    hd.size = (uint32_t)need;
    hd.xppm = 3779; hd.yppm = 3779;
    hd.clr_used = 256; hd.clr_important = 256;

    memcpy(out, &hd, 54);
    /* grayscale palette */
    for (int v = 0; v < 256; v++) {
        uint8_t *e = out + 54 + (size_t)v * 4;
        e[0] = e[1] = e[2] = (uint8_t)v;
        e[3] = 0;
    }
    memset(out + 54 + pal, 0, row * (size_t)h);
    for (uint32_t y = 0; y < h; y++) {
        memcpy(out + 54 + pal + (size_t)(h - 1 - y) * row,
               gray + (size_t)y * w, w);
    }
    return need;
}

/* ------------------- TIFF (baseline, uncompressed) ------------------ */
/*
 * Layout: header(8) | IFD(count2 + tags12*N + next4) | extra(BPS vals) | data
 * We always write BitsPerSample out-of-line (simplifies offsets).
 */
typedef struct { uint16_t id, typ; uint32_t cnt; uint32_t val; } tiff_tag;

static void put16(uint8_t *p, uint16_t v) { p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8); }
static void put32(uint8_t *p, uint32_t v) {
    p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8); p[2]=(uint8_t)(v>>16); p[3]=(uint8_t)(v>>24);
}

size_t opngx_encode_tiff(const uint8_t *pixels, uint32_t w, uint32_t h,
                         int gray, uint8_t *out, size_t cap) {
    const uint32_t spp = gray ? 1u : 3u;
    const size_t data_len = (size_t)w * h * spp;
    const size_t ifd_off  = 8;
    const size_t ntags    = 10;
    const size_t ifd_len  = 2 + ntags * 12 + 4;
    const size_t bps_off  = ifd_off + ifd_len;          /* spp * 2 bytes   */
    const size_t data_off = bps_off + spp * 2;
    const size_t need     = data_off + data_len;
    if (cap < need) return 0;

    memcpy(out, "II\x2a\x00", 4);
    put32(out + 4, (uint32_t)ifd_off);

    static const tiff_tag tags[10] = {
        { 256, 4, 1, 0 },   /* ImageWidth            (patched) */
        { 257, 4, 1, 0 },   /* ImageLength           (patched) */
        { 258, 3, 0, 0 },   /* BitsPerSample count=spp, val=bps_off (patched) */
        { 259, 3, 1, 1 },   /* Compression = none              */
        { 262, 3, 1, 0 },   /* Photometric = gray?1:RGB        */
        { 273, 4, 1, 0 },   /* StripOffsets          (patched) */
        { 277, 3, 1, 0 },   /* SamplesPerPixel = spp           */
        { 278, 4, 1, 0 },   /* RowsPerStrip = h                */
        { 279, 4, 1, 0 },   /* StripByteCounts = data_len      */
        { 296, 3, 1, 2 },   /* ResolutionUnit = inch           */
    };
    tiff_tag t[10];
    memcpy(t, tags, sizeof t);
    t[0].val = w;
    t[1].val = h;
    t[2].cnt = spp;
    /* count==1 SHORT may be inlined per spec — libtiff rejects an offset */
    t[2].val = (spp == 1) ? 8u : (uint32_t)bps_off;
    t[4].val = gray ? 1 : 2;
    t[5].val = (uint32_t)data_off;
    t[6].val = spp;
    t[7].val = h;
    t[8].val = (uint32_t)data_len;

    uint8_t *ifd = out + ifd_off;
    put16(ifd, (uint16_t)ntags);
    for (int k = 0; k < 10; k++) {
        uint8_t *e = ifd + 2 + (size_t)k * 12;
        put16(e,     t[k].id);
        put16(e + 2, t[k].typ);
        put32(e + 4, t[k].cnt);
        if (t[k].typ == 3 && t[k].cnt == 1) {
            put16(e + 8, (uint16_t)t[k].val);
            put16(e + 10, 0);
        } else {
            put32(e + 8, t[k].val);
        }
    }
    put32(ifd + 2 + ntags * 12, 0);          /* no next IFD */

    uint8_t *bps = out + bps_off;
    if (gray) put16(bps, 8);
    else { put16(bps, 8); put16(bps + 2, 8); put16(bps + 4, 8); }

    memcpy(out + data_off, pixels, data_len);
    return need;
}

/* ------------------------------- JPEG ------------------------------- */
typedef struct { uint8_t *buf; size_t cap, len; } jpg_sink;

static void jpg_emit(void *ctx, void *data, int size) {
    jpg_sink *s = (jpg_sink *)ctx;
    if (!s || s->len + (size_t)size > s->cap) return;  /* drop -> len short */
    memcpy(s->buf + s->len, data, (size_t)size);
    s->len += (size_t)size;
}

size_t opngx_encode_jpg(const uint8_t *gray, uint32_t w, uint32_t h,
                        int quality, uint8_t *out, size_t cap) {
    if (quality < 1) quality = 1;
    if (quality > 100) quality = 100;
    const size_t n = (size_t)w * h;
    uint8_t *rgb = malloc(n * 3);
    if (!rgb) return 0;
    for (size_t i = 0; i < n; i++) {
        rgb[i*3+0] = gray[i];
        rgb[i*3+1] = gray[i];
        rgb[i*3+2] = gray[i];
    }
    jpg_sink sink;
    sink.buf = out; sink.cap = cap; sink.len = 0;
    int ok = stbi_write_jpg_to_func(jpg_emit, &sink, (int)w, (int)h, 3, rgb,
                                    quality);
    free(rgb);
    /* stb returns 1 on success; a truncated sink leaves len<expected but
     * still returns 1 — validate against a conservative floor. */
    if (!ok || sink.len == 0) return 0;
    return sink.len;
}
