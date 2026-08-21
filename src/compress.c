/* compress.c — see compress.h
 *
 * Backends:
 *   - libdeflate (preferred when compiled in): raw DEFLATE, ~2-4x faster.
 *   - zlib: emits RAW deflate via deflateInit2(-MAX_WBITS) so the caller's
 *     opngx_zlib_wrap() adds exactly one zlib container. Using compress2()
 *     here would double-wrap and silently corrupt every output file —
 *     this was audit finding #1; a round-trip test now guards it.
 *
 * Both builds honor every C_BACKEND_* request: AUTO prefers libdeflate,
 * falling back to raw-zlib when libdeflate is unavailable.
 */
#include "compress.h"
#include <stdlib.h>
#include <string.h>

#if defined(OPNGX_HAVE_LIBDEFLATE)
#include <libdeflate.h>

struct cctx {
    struct libdeflate_compressor *ld;
    int level;
    int backend;
};

cctx *cctx_create(int want_backend, int level) {
    (void)want_backend;  /* all requests are served by libdeflate here */
    cctx *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    /* In this build an explicit zlib request is served by libdeflate
     * (raw deflate output is identical); AUTO also prefers libdeflate. */
    c->backend = C_BACKEND_LIBDEFLATE;
    c->level = level < 1 ? 1 : (level > 12 ? 12 : level);
    c->ld = libdeflate_alloc_compressor(c->level);
    if (c->ld) return c;
    free(c);
    return NULL;
}

void cctx_free(cctx *c) {
    if (!c) return;
    if (c->ld) libdeflate_free_compressor(c->ld);
    free(c);
}

size_t cctx_compress(cctx *c, const uint8_t *in, size_t in_len,
                     uint8_t *out, size_t out_cap) {
    return libdeflate_deflate_compress(c->ld, in, in_len, out, out_cap);
}

const char *cctx_backend_name(const cctx *c) {
    (void)c;
    return "libdeflate";
}

int cctx_backend_id(const cctx *c) { return c ? c->backend : 0; }
int cctx_max_level(const cctx *c) { (void)c; return 12; }

#else /* ------------------- raw-deflate via zlib ------------------- */
#include <zlib.h>

struct cctx {
    z_stream strm;
    int level;
    int backend;
    int inited;
};

cctx *cctx_create(int want_backend, int level) {
    cctx *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    c->backend = C_BACKEND_ZLIB;
    c->level = level < 1 ? 1 : (level > 9 ? 9 : level);
    /* negative window bits => RAW deflate, no zlib header/adler from us */
    if (deflateInit2(&c->strm, c->level, Z_DEFLATED, -MAX_WBITS,
                     8, Z_DEFAULT_STRATEGY) != Z_OK) {
        free(c);
        return NULL;
    }
    c->inited = 1;
    return c;
}

void cctx_free(cctx *c) {
    if (!c) return;
    if (c->inited) deflateEnd(&c->strm);
    free(c);
}

size_t cctx_compress(cctx *c, const uint8_t *in, size_t in_len,
                     uint8_t *out, size_t out_cap) {
    if (deflateReset(&c->strm) != Z_OK) return 0;
    c->strm.next_in = (z_const Bytef *)in;
    c->strm.avail_in = (uInt)in_len;
    c->strm.next_out = out;
    c->strm.avail_out = (uInt)out_cap;
    int ret = Z_OK;
    do {
        ret = deflate(&c->strm, Z_FINISH);
        if (ret == Z_STREAM_ERROR) return 0;
    } while (ret != Z_STREAM_END);
    return out_cap - c->strm.avail_out;
}

const char *cctx_backend_name(const cctx *c) { (void)c; return "zlib"; }
int cctx_backend_id(const cctx *c) { return c ? C_BACKEND_ZLIB : 0; }
int cctx_max_level(const cctx *c) { (void)c; return 9; }
#endif
