/* pngout.c — see pngout.h */
#include "pngout.h"
#include <string.h>

/* ---------- CRC32 (PNG polynomial, reflected) ---------- */
static uint32_t crc_table[256];
static int crc_ready = 0;

static void crc_init(void) {
    for (uint32_t n = 0; n < 256; n++) {
        uint32_t c = n;
        for (int k = 0; k < 8; k++)
            c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : (c >> 1);
        crc_table[n] = c;
    }
    crc_ready = 1;
}

uint32_t opngx_crc32(uint32_t crc, const void *buf, size_t len) {
    if (!crc_ready) crc_init();
    const uint8_t *p = (const uint8_t *)buf;
    crc ^= 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++)
        crc = crc_table[(crc ^ p[i]) & 0xFF] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFFu;
}

/* ---------- Adler-32 (zlib trailer), NMAX-blocked ---------- */
uint32_t opngx_adler32(const void *buf, size_t len) {
    const uint8_t *p = (const uint8_t *)buf;
    uint32_t a = 1, b = 0;
    while (len) {
        size_t t = len > 5552 ? 5552 : len;
        len -= t;
        do { a += *p++; b += a; } while (--t);
        a %= 65521u;
        b %= 65521u;
    }
    return (b << 16) | a;
}

/* ---------- chunk helpers ---------- */
static void put_u32be(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);  p[3] = (uint8_t)(v);
}

size_t opngx_png_size(size_t idat_len) {
    /* sig + IHDR + sRGB + gAMA + pHYs + IDAT + IEND */
    return 8 + (12+13) + (12+1) + (12+4) + (12+9) + (12+idat_len) + 12;
}

size_t opngx_png_assemble(uint8_t *out, uint32_t w, uint32_t h, int bit_depth,
                          int color_type, const uint8_t *idat, size_t idat_len) {
    uint8_t *o = out;
    static const uint8_t sig[8] = {0x89,'P','N','G','\r','\n',0x1a,'\n'};
    memcpy(o, sig, 8); o += 8;

    /* IHDR */
    uint8_t ihdr[13];
    put_u32be(ihdr, w);
    put_u32be(ihdr+4, h);
    ihdr[8]  = (uint8_t)bit_depth;      /* 8 or 16 */
    ihdr[9]  = (uint8_t)color_type;     /* 6 RGBA or 0 gray */
    ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
    put_u32be(o, 13); memcpy(o+4, "IHDR", 4); memcpy(o+8, ihdr, 13);
    put_u32be(o+21, opngx_crc32(0, o+4, 17)); o += 25;

    /* sRGB: perceptual intent 0 — matches reference files */
    o[0]=0; o[1]=0; o[2]=0; o[3]=1; memcpy(o+4,"sRGB",4); o[8]=0;
    put_u32be(o+9, opngx_crc32(0, o+4, 5)); o += 13;

    /* gAMA 45455 (2.2-ish), matches reference */
    put_u32be(o, 4); memcpy(o+4,"gAMA",4); put_u32be(o+8, 45455u);
    put_u32be(o+12, opngx_crc32(0, o+4, 8)); o += 16;

    /* pHYs 3779x3779 per meter (96 dpi), matches reference */
    {
        uint8_t d[9];
        put_u32be(d, 3779u); put_u32be(d+4, 3779u); d[8] = 1;
        put_u32be(o, 9); memcpy(o+4,"pHYs",4); memcpy(o+8, d, 9);
        put_u32be(o+17, opngx_crc32(0, o+4, 13)); o += 21;
    }

    /* IDAT */
    put_u32be(o, (uint32_t)idat_len);
    memcpy(o+4, "IDAT", 4);
    memcpy(o+8, idat, idat_len);
    put_u32be(o+8+idat_len, opngx_crc32(0, o+4, 4+idat_len));
    o += 12 + idat_len;

    /* IEND */
    put_u32be(o, 0); memcpy(o+4, "IEND", 4);
    put_u32be(o+8, opngx_crc32(0, o+4, 4));
    o += 12;

    return (size_t)(o - out);
}

size_t opngx_zlib_wrap(uint8_t *dst, size_t dst_cap,
                       const uint8_t *deflate_data, size_t deflate_len,
                       const uint8_t *uncompressed, size_t uncomp_len) {
    /* zlib stream: CMF/FLG + raw deflate + adler32(uncompressed data).
     * FLEVEL hint 1 mirrors the reference writer's header bytes (0x78 0x5E). */
    if (dst_cap < deflate_len + 6) return 0;
    uint32_t ad = opngx_adler32(uncompressed, uncomp_len); /* before any move */
    dst[0] = 0x78; dst[1] = 0x5E;
    memmove(dst + 2, deflate_data, deflate_len);
    put_u32be(dst + 2 + deflate_len, ad);
    return deflate_len + 6;
}
