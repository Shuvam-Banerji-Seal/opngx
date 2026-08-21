/* compress.h — deflate backend abstraction (libdeflate preferred, zlib fallback) */
#ifndef OPNGX_COMPRESS_H
#define OPNGX_COMPRESS_H
#include <stddef.h>
#include <stdint.h>

#define C_BACKEND_AUTO        0
#define C_BACKEND_LIBDEFLATE 1
#define C_BACKEND_ZLIB       2

typedef struct cctx cctx;

/* want_backend: C_BACKEND_* ; level clamped to backend range */
cctx *cctx_create(int want_backend, int level);
void  cctx_free(cctx *c);

/* Raw deflate stream (no zlib wrapper). Returns length or 0 on failure. */
size_t cctx_compress(cctx *c, const uint8_t *in, size_t in_len,
                     uint8_t *out, size_t out_cap);

const char *cctx_backend_name(const cctx *c);
int         cctx_backend_id(const cctx *c);   /* C_BACKEND_* */
int cctx_max_level(const cctx *c);

#endif
