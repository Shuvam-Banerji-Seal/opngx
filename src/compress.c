/* compress.c — see compress.h
 *
 * Backends:
 *   - libdeflate (preferred): raw DEFLATE, ~2-4x faster than zlib.
 *     When compiled in, zlib is NOT required at all.
 *   - zlib fallback used only when built without libdeflate.
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
    cctx *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    int use_ld = (want_backend != C_BACKEND_ZLIB); /* AUTO prefers libdeflate */
    if (use_ld) {
        c->backend = C_BACKEND_LIBDEFLATE;
        c->level = level < 1 ? 1 : (level > 12 ? 12 : level);
        c->ld = libdeflate_alloc_compressor(c->level);
        if (c->ld) return c;
        if (want_backend == C_BACKEND_LIBDEFLATE) { free(c); return NULL; }
    }
    /* no libdeflate -> cannot honor a zlib request in this build */
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

int cctx_max_level(const cctx *c) { (void)c; return 12; }

#else /* ------------------- zlib-only build ------------------- */
#include <zlib.h>

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
