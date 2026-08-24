/* pngout.c — see pngout.h */
#include "pngout.h"
#include <string.h>

#if defined(OPNGX_HAVE_LIBDEFLATE)
#include <libdeflate.h>
/* libdeflate's checksums are SIMD-accelerated (PCLMULQDQ CRC / vector
 * adler). At burst speeds the table-driven versions below were costing
 * up to ~25% of the per-frame budget, so when libdeflate is linked we
 * delegate — outputs stay byte-identical (same algorithms/semantics). */
#endif

#if !defined(OPNGX_HAVE_LIBDEFLATE)
/* ---------- CRC32 (PNG polynomial, reflected) ----------
 * Table is a compile-time constant: no lazy-init race between worker
 * threads. Only compiled for the zlib-fallback build (libdeflate
 * builds delegate to libdeflate_crc32). */
static const uint32_t crc_table[256] = {
    0x00000000u, 0x77073096u, 0xEE0E612Cu, 0x990951BAu, 0x076DC419u, 0x706AF48Fu, 0xE963A535u, 0x9E6495A3u,
    0x0EDB8832u, 0x79DCB8A4u, 0xE0D5E91Eu, 0x97D2D988u, 0x09B64C2Bu, 0x7EB17CBDu, 0xE7B82D07u, 0x90BF1D91u,
    0x1DB71064u, 0x6AB020F2u, 0xF3B97148u, 0x84BE41DEu, 0x1ADAD47Du, 0x6DDDE4EBu, 0xF4D4B551u, 0x83D385C7u,
    0x136C9856u, 0x646BA8C0u, 0xFD62F97Au, 0x8A65C9ECu, 0x14015C4Fu, 0x63066CD9u, 0xFA0F3D63u, 0x8D080DF5u,
    0x3B6E20C8u, 0x4C69105Eu, 0xD56041E4u, 0xA2677172u, 0x3C03E4D1u, 0x4B04D447u, 0xD20D85FDu, 0xA50AB56Bu,
    0x35B5A8FAu, 0x42B2986Cu, 0xDBBBC9D6u, 0xACBCF940u, 0x32D86CE3u, 0x45DF5C75u, 0xDCD60DCFu, 0xABD13D59u,
    0x26D930ACu, 0x51DE003Au, 0xC8D75180u, 0xBFD06116u, 0x21B4F4B5u, 0x56B3C423u, 0xCFBA9599u, 0xB8BDA50Fu,
    0x2802B89Eu, 0x5F058808u, 0xC60CD9B2u, 0xB10BE924u, 0x2F6F7C87u, 0x58684C11u, 0xC1611DABu, 0xB6662D3Du,
    0x76DC4190u, 0x01DB7106u, 0x98D220BCu, 0xEFD5102Au, 0x71B18589u, 0x06B6B51Fu, 0x9FBFE4A5u, 0xE8B8D433u,
    0x7807C9A2u, 0x0F00F934u, 0x9609A88Eu, 0xE10E9818u, 0x7F6A0DBBu, 0x086D3D2Du, 0x91646C97u, 0xE6635C01u,
    0x6B6B51F4u, 0x1C6C6162u, 0x856530D8u, 0xF262004Eu, 0x6C0695EDu, 0x1B01A57Bu, 0x8208F4C1u, 0xF50FC457u,
    0x65B0D9C6u, 0x12B7E950u, 0x8BBEB8EAu, 0xFCB9887Cu, 0x62DD1DDFu, 0x15DA2D49u, 0x8CD37CF3u, 0xFBD44C65u,
    0x4DB26158u, 0x3AB551CEu, 0xA3BC0074u, 0xD4BB30E2u, 0x4ADFA541u, 0x3DD895D7u, 0xA4D1C46Du, 0xD3D6F4FBu,
    0x4369E96Au, 0x346ED9FCu, 0xAD678846u, 0xDA60B8D0u, 0x44042D73u, 0x33031DE5u, 0xAA0A4C5Fu, 0xDD0D7CC9u,
    0x5005713Cu, 0x270241AAu, 0xBE0B1010u, 0xC90C2086u, 0x5768B525u, 0x206F85B3u, 0xB966D409u, 0xCE61E49Fu,
    0x5EDEF90Eu, 0x29D9C998u, 0xB0D09822u, 0xC7D7A8B4u, 0x59B33D17u, 0x2EB40D81u, 0xB7BD5C3Bu, 0xC0BA6CADu,
    0xEDB88320u, 0x9ABFB3B6u, 0x03B6E20Cu, 0x74B1D29Au, 0xEAD54739u, 0x9DD277AFu, 0x04DB2615u, 0x73DC1683u,
    0xE3630B12u, 0x94643B84u, 0x0D6D6A3Eu, 0x7A6A5AA8u, 0xE40ECF0Bu, 0x9309FF9Du, 0x0A00AE27u, 0x7D079EB1u,
    0xF00F9344u, 0x8708A3D2u, 0x1E01F268u, 0x6906C2FEu, 0xF762575Du, 0x806567CBu, 0x196C3671u, 0x6E6B06E7u,
    0xFED41B76u, 0x89D32BE0u, 0x10DA7A5Au, 0x67DD4ACCu, 0xF9B9DF6Fu, 0x8EBEEFF9u, 0x17B7BE43u, 0x60B08ED5u,
    0xD6D6A3E8u, 0xA1D1937Eu, 0x38D8C2C4u, 0x4FDFF252u, 0xD1BB67F1u, 0xA6BC5767u, 0x3FB506DDu, 0x48B2364Bu,
    0xD80D2BDAu, 0xAF0A1B4Cu, 0x36034AF6u, 0x41047A60u, 0xDF60EFC3u, 0xA867DF55u, 0x316E8EEFu, 0x4669BE79u,
    0xCB61B38Cu, 0xBC66831Au, 0x256FD2A0u, 0x5268E236u, 0xCC0C7795u, 0xBB0B4703u, 0x220216B9u, 0x5505262Fu,
    0xC5BA3BBEu, 0xB2BD0B28u, 0x2BB45A92u, 0x5CB36A04u, 0xC2D7FFA7u, 0xB5D0CF31u, 0x2CD99E8Bu, 0x5BDEAE1Du,
    0x9B64C2B0u, 0xEC63F226u, 0x756AA39Cu, 0x026D930Au, 0x9C0906A9u, 0xEB0E363Fu, 0x72076785u, 0x05005713u,
    0x95BF4A82u, 0xE2B87A14u, 0x7BB12BAEu, 0x0CB61B38u, 0x92D28E9Bu, 0xE5D5BE0Du, 0x7CDCEFB7u, 0x0BDBDF21u,
    0x86D3D2D4u, 0xF1D4E242u, 0x68DDB3F8u, 0x1FDA836Eu, 0x81BE16CDu, 0xF6B9265Bu, 0x6FB077E1u, 0x18B74777u,
    0x88085AE6u, 0xFF0F6A70u, 0x66063BCAu, 0x11010B5Cu, 0x8F659EFFu, 0xF862AE69u, 0x616BFFD3u, 0x166CCF45u,
    0xA00AE278u, 0xD70DD2EEu, 0x4E048354u, 0x3903B3C2u, 0xA7672661u, 0xD06016F7u, 0x4969474Du, 0x3E6E77DBu,
    0xAED16A4Au, 0xD9D65ADCu, 0x40DF0B66u, 0x37D83BF0u, 0xA9BCAE53u, 0xDEBB9EC5u, 0x47B2CF7Fu, 0x30B5FFE9u,
    0xBDBDF21Cu, 0xCABAC28Au, 0x53B39330u, 0x24B4A3A6u, 0xBAD03605u, 0xCDD70693u, 0x54DE5729u, 0x23D967BFu,
    0xB3667A2Eu, 0xC4614AB8u, 0x5D681B02u, 0x2A6F2B94u, 0xB40BBE37u, 0xC30C8EA1u, 0x5A05DF1Bu, 0x2D02EF8Du,
};
#endif /* !OPNGX_HAVE_LIBDEFLATE */

uint32_t opngx_crc32(uint32_t crc, const void *buf, size_t len) {
#if defined(OPNGX_HAVE_LIBDEFLATE)
    return (uint32_t)libdeflate_crc32(crc, buf, len);
#else
    const uint8_t *p = (const uint8_t *)buf;
    crc ^= 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++)
        crc = crc_table[(crc ^ p[i]) & 0xFF] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFFu;
#endif
}

/* ---------- Adler-32 (zlib trailer), NMAX-blocked ---------- */
uint32_t opngx_adler32(const void *buf, size_t len) {
#if defined(OPNGX_HAVE_LIBDEFLATE)
    return (uint32_t)libdeflate_adler32(1, buf, len);
#else
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
#endif
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
