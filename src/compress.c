/* compress.c — see compress.h */
#include "compress.h"
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

#if defined(OPNGX_HAVE_LIBDEFLATE)
#include <libdeflate.h>

struct cctx {
    struct libdeflate_compressor *ld;
    int level;
    int backend;
};

cctx *cctx_create(int want_backend, int level) {
    cctx *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    int use_ld = (want_backend != C_BACKEND_ZLIB); /* AUTO prefers libdeflate */
    if (use_ld) {
        c->backend = C_BACKEND_LIBDEFLATE;
        c->level = level < 1 ? 1 : (level > 12 ? 12 : level);
        c->ld = libdeflate_alloc_compressor(c->level);
        if (c->ld) return c;
        if (want_backend == C_BACKEND_LIBDEFLATE) { free(c); return NULL; } /* explicit: fail */
    }
    c->backend = C_BACKEND_ZLIB;
    c->level = level < 1 ? 1 : (level > 9 ? 9 : level);
    return c;
}

void cctx_free(cctx *c) {
    if (!c) return;
    if (c->ld) libdeflate_free_compressor(c->ld);
    free(c);
}

size_t cctx_compress(cctx *c, const uint8_t *in, size_t in_len,
                     uint8_t *out, size_t out_cap) {
    if (c->backend == C_BACKEND_LIBDEFLATE)
        return libdeflate_deflate_compress(c->ld, in, in_len, out, out_cap);
    /* zlib fallback: uLongf bound per call */
    uLongf dst = (uLongf)out_cap;
    if (compress2(out, &dst, in, in_len, c->level) != Z_OK) return 0;
    return (size_t)dst;
}

const char *cctx_backend_name(const cctx *c) {
    return c->backend == C_BACKEND_LIBDEFLATE ? "libdeflate" : "zlib";
}

int cctx_max_level(const cctx *c) { return c->backend == C_BACKEND_LIBDEFLATE ? 12 : 9; }

#else /* zlib-only build */

struct cctx { int level; int backend; };

cctx *cctx_create(int want_backend, int level) {
    cctx *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    c->backend = C_BACKEND_ZLIB;
    c->level = level < 1 ? 1 : (level > 9 ? 9 : level);
    return c;
}
void cctx_free(cctx *c) { free(c); }

size_t cctx_compress(cctx *c, const uint8_t *in, size_t in_len,
                     uint8_t *out, size_t out_cap) {
    uLongf dst = (uLongf)out_cap;
    if (compress2(out, &dst, in, in_len, c->level) != Z_OK) return 0;
    return (size_t)dst;
}
const char *cctx_backend_name(const cctx *c) { (void)c; return "zlib"; }
int cctx_max_level(const cctx *c) { (void)c; return 9; }
#endif
