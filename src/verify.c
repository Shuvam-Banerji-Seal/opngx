/*
 * verify.c — pixel-exact verification of extracted PNGs against reference dirs.
 *
 * Compares decoded raw scanlines (post-inflate) byte-for-byte, which is a
 * complete proof of pixel equality for identical geometry/color type.
 */
#include "verify.h"
#include "pngout.h"
#include "compress.h"
#include "port.h"
#include "opngx.h"
#include "footage.h"
#include "transform.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <errno.h>
#include <stdatomic.h>
#include <stdlib.h>

#if defined(OPNGX_HAVE_LIBDEFLATE)
#include <libdeflate.h>
static int zinflate_len(const uint8_t *in, size_t in_len,
                        uint8_t *out, size_t out_len) {
    struct libdeflate_decompressor *d = libdeflate_alloc_decompressor();
    if (!d) return -1;
    enum libdeflate_result r =
        libdeflate_zlib_decompress(d, in, in_len, out, out_len, NULL);
    libdeflate_free_decompressor(d);
    return r == LIBDEFLATE_SUCCESS ? 0 : -1;
}
#else
#include <zlib.h>
static int zinflate_len(const uint8_t *in, size_t in_len,
                        uint8_t *out, size_t out_len) {
    uLongf dst = (uLongf)out_len;
    if (uncompress(out, &dst, in, in_len) != Z_OK) return -1;
    return dst == out_len ? 0 : -1;   /* reject short/garbage tails */
}
#endif

/* --- PNG row-filter reconstruction (spec: None/Sub/Up/Average/Paeth) ---
 * Reconstructs filtered scanlines in-place into true pixel rows so that
 * comparisons are independent of the encoder's filter choices. */
static int png_unfilter(uint8_t *data, uint32_t w, uint32_t h,
                        unsigned bpp_bytes) {
    const size_t stride = (size_t)w * bpp_bytes + 1;
    const size_t rw = (size_t)w * bpp_bytes;
    for (uint32_t y = 0; y < h; y++) {
        uint8_t *row = data + (size_t)y * stride;
        uint8_t ftype = row[0];
        uint8_t *px = row + 1;
        const uint8_t *prev = y ? (row - stride + 1) : NULL;
        switch (ftype) {
        case 0: /* None */
            break;
        case 1: /* Sub */
            for (size_t i = bpp_bytes; i < rw; i++)
                px[i] = (uint8_t)(px[i] + px[i - bpp_bytes]);
            break;
        case 2: /* Up */
            if (prev)
                for (size_t i = 0; i < rw; i++)
                    px[i] = (uint8_t)(px[i] + prev[i]);
            break;
        case 3: { /* Average */
            for (size_t i = 0; i < rw; i++) {
                unsigned a = i >= bpp_bytes ? px[i - bpp_bytes] : 0;
                unsigned b = prev ? prev[i] : 0;
                px[i] = (uint8_t)(px[i] + ((a + b) >> 1));
            }
            break;
        }
        case 4: { /* Paeth */
            for (size_t i = 0; i < rw; i++) {
                unsigned a = i >= bpp_bytes ? px[i - bpp_bytes] : 0;
                unsigned b = prev ? prev[i] : 0;
                unsigned c = (prev && i >= bpp_bytes) ? prev[i - bpp_bytes] : 0;
                int p = (int)a + (int)b - (int)c;
                int pa = abs(p - (int)a);
                int pb = abs(p - (int)b);
                int pc = abs(p - (int)c);
                unsigned pred = (pa <= pb && pa <= pc) ? a : (pb <= pc) ? b : c;
                px[i] = (uint8_t)(px[i] + pred);
            }
            break;
        }
        default:
            return -1; /* unknown filter */
        }
    }
    return 0;
}

/* Extract just the pixel rows (drop filter bytes) into dst. */
static void png_strip_filters(const uint8_t *data, uint32_t w, uint32_t h,
                              unsigned bpp_bytes, uint8_t *dst) {
    const size_t stride = (size_t)w * bpp_bytes + 1;
    const size_t rw = (size_t)w * bpp_bytes;
    for (uint32_t y = 0; y < h; y++)
        memcpy(dst + (size_t)y * rw, data + (size_t)y * stride + 1, rw);
}

/* --- minimal PNG chunk walker --- */
typedef struct {
    uint32_t w, h, bit_depth, color_type;
    uint8_t *idat; size_t idat_len;
} png_view;

/* Binary search a sorted name array; -1 when absent. */
static int64_t find_name(char **arr, int64_t n, const char *name) {
    int64_t lo = 0, hi = n - 1;
    while (lo <= hi) {
        int64_t mid = lo + (hi - lo) / 2;
        int c = strcmp(arr[mid], name);
        if (c == 0) return mid;
        if (c < 0) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

static int png_parse(const uint8_t *buf, size_t len, png_view *v) {
    static const uint8_t sig[8] = {0x89,'P','N','G','\r','\n',0x1a,'\n'};
    memset(v, 0, sizeof *v);
    if (len < 8 || memcmp(buf, sig, 8)) return -1;
    size_t pos = 8;
    size_t idat_cap = 0;
    while (pos + 12 <= len) {
        uint32_t clen = ((uint32_t)buf[pos]<<24)|((uint32_t)buf[pos+1]<<16)|
                        ((uint32_t)buf[pos+2]<<8)|buf[pos+3];
        const char *typ = (const char*)buf+4+pos;
        if (pos + 12 + (size_t)clen > len) return -1;
        if (!memcmp(typ, "IHDR", 4) && clen >= 13) {
            const uint8_t *d = buf+8+pos;
            v->w = ((uint32_t)d[0]<<24)|((uint32_t)d[1]<<16)|((uint32_t)d[2]<<8)|d[3];
            v->h = ((uint32_t)d[4]<<24)|((uint32_t)d[5]<<16)|((uint32_t)d[6]<<8)|d[7];
            v->bit_depth = d[8]; v->color_type = d[9];
        } else if (!memcmp(typ, "IDAT", 4)) {
            if (v->idat_len + clen > idat_cap) {
                idat_cap = (v->idat_len + clen) * 2 + 1024;
                v->idat = realloc(v->idat, idat_cap);
                if (!v->idat) return -1;
            }
            memcpy(v->idat + v->idat_len, buf+8+pos, clen);
            v->idat_len += clen;
        } else if (!memcmp(typ, "IEND", 4)) {
            break;
        }
        pos += 12 + (size_t)clen;
    }
    if (!v->w || !v->h || !v->idat) return -1;
    return 0;
}

/* --- directory listing of matching names --- */
static int list_names(const char *dir, const char *prefix, const char *ext,
                      char ***names, int64_t *count) {
    DIR *d = opendir(dir);
    if (!d) return -1;
    size_t plen = strlen(prefix), elen = strlen(ext);
    char **arr = NULL; int64_t n = 0, cap = 0;
    struct dirent *e;
    while ((e = readdir(d))) {
        size_t L = strlen(e->d_name);
        if (L <= plen + elen) continue;
        if (memcmp(e->d_name, prefix, plen)) continue;
        if (memcmp(e->d_name + L - elen, ext, elen)) continue;
        /* strict pattern: middle must be digits only */
        int alldigit = 1;
        for (size_t k = plen; k < L - elen; k++)
            if (e->d_name[k] < '0' || e->d_name[k] > '9') { alldigit = 0; break; }
        if (!alldigit) continue;
        if (n == cap) { cap = cap ? cap*2 : 256; arr = realloc(arr, (size_t)cap*sizeof(char*)); }
        arr[n++] = strdup(e->d_name);
    }
    closedir(d);
    /* sort */
    for (int64_t i = 1; i < n; i++) {
        char *k = arr[i]; int64_t jj = i-1;
        while (jj >= 0 && strcmp(arr[jj], k) > 0) { arr[jj+1] = arr[jj]; jj--; }
        arr[jj+1] = k;
    }
    *names = arr; *count = n;
    return 0;
}

void verify_report_init(verify_report *r) { memset(r, 0, sizeof *r); }

/* ---- parallel comparison core (portable worker pool) ---- */
typedef struct {
    char **rn, **on;
    const char *ref_dir, *out_dir;
    verify_report *rep;
    _Atomic int64_t cursor;      /* dynamic claim cursor (over OUT names)  */
    int64_t rn_n;
    int64_t common;
    _Atomic int64_t mism;
    _Atomic int64_t not_in_ref;  /* out names absent from ref (subset check) */
    _Atomic uint64_t bytes_ok;
    _Atomic int err_taken;
} vshared_t;

static int zinflate_len(const uint8_t *in, size_t in_len,
                        uint8_t *out, size_t out_len);

/* ---- shared decode/compare helpers (used by both verifiers) ---- */

/* Decode one PNG file into stripped pixel rows (post-unfilter).
 * On success returns 0, *q_out holds h*w*bpp bytes and v is filled
 * (v.idat already released). On failure returns -1 with `why` filled. */
static int load_png_pixels(const char *path, png_view *v, uint8_t **q_out,
                           unsigned *bpp_out, char *why, size_t why_cap) {
    *q_out = NULL;
    memset(v, 0, sizeof *v);
    FILE *f = fopen(path, "rb");
    if (!f) { snprintf(why, why_cap, "open failed: %.400s", path); return -1; }
    fseek(f, 0, SEEK_END);
    long l = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (l <= 0) {
        fclose(f);
        snprintf(why, why_cap, "empty file: %.400s", path);
        return -1;
    }
    uint8_t *b = malloc((size_t)l);
    if (!b || fread(b, 1, (size_t)l, f) != (size_t)l) {
        free(b);
        fclose(f);
        snprintf(why, why_cap, "read failed: %.400s", path);
        return -1;
    }
    fclose(f);

    int rc = -1;
    uint8_t *r = NULL;
    if (png_parse(b, (size_t)l, v)) {
        snprintf(why, why_cap, "bad PNG structure: %.400s", path);
        goto out;
    }
    {
        unsigned ch = v->color_type == 0 ? 1u : 4u;
        unsigned bpp = ch * (v->bit_depth == 16 ? 2u : 1u);
        if (bpp_out) *bpp_out = bpp;
        size_t raw = (size_t)v->h * ((size_t)v->w * bpp + 1);
        r = malloc(raw);
        *q_out = malloc((size_t)v->h * v->w * bpp);
        if (!r || !*q_out ||
            zinflate_len(v->idat, v->idat_len, r, raw) ||
            png_unfilter(r, v->w, v->h, bpp)) {
            snprintf(why, why_cap, "inflate/unfilter failed: %.400s", path);
            goto out;
        }
        png_strip_filters(r, v->w, v->h, bpp, *q_out);
        rc = 0;
    }
out:
    free(r);
    free(v->idat);
    v->idat = NULL;
    free(b);
    if (rc && *q_out) { free(*q_out); *q_out = NULL; }
    return rc;
}

/* Pixel equality for two decoded buffers. Handles identical layouts via
 * memcmp and gray-vs-RGBA cross-layout via first-channel comparison.
 * Returns 0 when equal. */
static int pixels_differ(const png_view *a, const uint8_t *qa,
                         const png_view *b, const uint8_t *qb,
                         uint64_t *ok_bytes) {
    unsigned cha = a->color_type == 0 ? 1u : 4u;
    unsigned chb = b->color_type == 0 ? 1u : 4u;
    unsigned bpa = cha * (a->bit_depth == 16 ? 2u : 1u);
    unsigned bpb = chb * (b->bit_depth == 16 ? 2u : 1u);
    if (a->w != b->w || a->h != b->h) return 1;
    if (cha == chb && a->bit_depth == b->bit_depth) {
        size_t n = (size_t)a->h * a->w * bpa;
        if (memcmp(qa, qb, n)) return 1;
        *ok_bytes = (uint64_t)n;
        return 0;
    }
    /* cross-layout: gray value must equal RGBA R (=G=B) */
    const uint32_t W = a->w, H = a->h;
    for (uint32_t y = 0; y < H; y++) {
        const uint8_t *ra = qa + (size_t)y * a->w * bpa;
        const uint8_t *rb = qb + (size_t)y * b->w * bpb;
        for (uint32_t x = 0; x < W; x++)
            if (ra[x * bpa] != rb[x * bpb]) return 1;
    }
    *ok_bytes = (uint64_t)W * H;
    return 0;
}

/* Compare one pair resolved BY NAME (subset-safe: a --start>0 extract
 * must verify against its own names, not against sorted positions). */
static int verify_one_pair(vshared_t *vs, int64_t oi, int64_t ri) {
    char p1[1200], p2[1200];
    snprintf(p1, sizeof p1, "%.500s/%.600s", vs->ref_dir, vs->rn[ri]);
    snprintf(p2, sizeof p2, "%.500s/%.600s", vs->out_dir, vs->on[oi]);

    png_view v1, v2;
    uint8_t *q1 = NULL, *q2 = NULL;
    unsigned bpp1 = 0, bpp2 = 0;
    char why[256] = "";
    int bad = 0;
    uint64_t ok_bytes = 0;

    if (load_png_pixels(p1, &v1, &q1, &bpp1, why, sizeof why) ||
        load_png_pixels(p2, &v2, &q2, &bpp2, why, sizeof why)) {
        bad = 1;
        goto done;
    }
    bad = pixels_differ(&v1, q1, &v2, q2, &ok_bytes);

done:
    free(q1); free(q2);
    if (bad && !atomic_exchange(&vs->err_taken, 1)) {
        if (why[0])
            snprintf(vs->rep->first_error, sizeof vs->rep->first_error,
                     "%s", why);
        else
            snprintf(vs->rep->first_error, sizeof vs->rep->first_error,
                     "pixel mismatch: %.200s vs %.200s", p1, p2);
    }
    if (!bad)
        atomic_fetch_add(&vs->bytes_ok, ok_bytes);
    return bad;
}

static void vworker(const port_worker_ctx *w, void *ud) {
    (void)w;
    vshared_t *vs = (vshared_t *)ud;
    const int64_t G = 64;
    for (;;) {
        int64_t i = atomic_fetch_add_explicit(&vs->cursor, G,
                                              memory_order_relaxed);
        if (i >= vs->common) break;   /* common == number of OUT names */
        int64_t end = i + G < vs->common ? i + G : vs->common;
        for (; i < end; i++) {
            int64_t ri = find_name(vs->rn, vs->rn_n, vs->on[i]);
            if (ri < 0) {
                atomic_fetch_add(&vs->not_in_ref, 1);
                continue;
            }
            if (verify_one_pair(vs, i, ri))
                atomic_fetch_add(&vs->mism, 1);
        }
    }
}

int opngx_verify(const char *ref_dir, const char *out_dir,
                 const char *prefix, const char *ext,
                 verify_report *rep, char *err, size_t err_cap) {
    if (err && err_cap) err[0] = '\0';
    verify_report_init(rep);

    char **rn = NULL, **on = NULL;
    int64_t rn_n = 0, on_n = 0;
    if (list_names(ref_dir, prefix, ext, &rn, &rn_n)) {
        snprintf(err, err_cap, "cannot scan ref dir '%s': %s", ref_dir, strerror(errno));
        return -1;
    }
    if (list_names(out_dir, prefix, ext, &on, &on_n)) {
        snprintf(err, err_cap, "cannot scan out dir '%s': %s", out_dir, strerror(errno));
        return -1;
    }
    rep->files_ref = rn_n; rep->files_out = on_n;

    /* set equality check */
    rep->set_equal = (rn_n == on_n);
    if (rep->set_equal) {
        for (int64_t i = 0; i < rn_n; i++)
            if (strcmp(rn[i], on[i])) { rep->set_equal = 0; break; }
    }
    if (!rep->set_equal) {
        snprintf(rep->first_error, sizeof rep->first_error,
                 "name sets differ: ref=%lld out=%lld", (long long)rn_n, (long long)on_n);
    }

    /* pair every OUT name to its REF name (subset-safe by-name matching) */
    int64_t common = on_n;

    vshared_t vs;
    vs.rn = rn; vs.on = on;
    vs.ref_dir = ref_dir; vs.out_dir = out_dir;
    vs.rep = rep;
    vs.cursor = 0; vs.common = common; vs.mism = 0; vs.bytes_ok = 0;
    vs.not_in_ref = 0; vs.rn_n = rn_n;
    vs.err_taken = 0;

    port_spawn_workers(port_cpu_count(), vworker, &vs);

    int64_t matched = on_n - atomic_load(&vs.not_in_ref);
    rep->files_compared = matched;
    rep->bytes_compared = atomic_load(&vs.bytes_ok);
    rep->mismatched_files = atomic_load(&vs.mism);
    if (rep->mismatched_files && !atomic_load(&vs.err_taken))
        snprintf(rep->first_error, sizeof rep->first_error,
                 "%lld file(s) differ",
                 (long long)rep->mismatched_files);
    {
        int64_t nabsent = atomic_load(&vs.not_in_ref);
        if (nabsent > 0) {
            char note[96];
            snprintf(note, sizeof note,
                     "%lld output file(s) absent from reference set",
                     (long long)nabsent);
            size_t cur = strlen(rep->first_error);
            if (cur && rep->mismatched_files == 0 && cur + 3 < sizeof rep->first_error)
                rep->first_error[cur++] = ';', rep->first_error[cur++] = ' ';
            snprintf(rep->first_error + cur,
                     sizeof rep->first_error - cur, "%s", note);
        }
    }

    for (int64_t i = 0; i < rn_n; i++) { free(rn[i]); }
    free(rn);
    for (int64_t i = 0; i < on_n; i++) { free(on[i]); }
    free(on);
    if (atomic_load(&vs.not_in_ref) > 0 && !rep->set_equal)
        return 1;   /* subset claim broken: names not present in ref */
    return rep->mismatched_files ? 1 : 0;
}

/* ==================== ADD-7: verify against source .bin ====================
 * Compares an extracted directory directly against the recording itself:
 * each output file's decoded pixels must equal the LUT-mapped frame at the
 * absolute index encoded in its filename. No vendor reference set needed.
 */

typedef struct {
    const opngx_params *p;
    const uint8_t *map;
    size_t map_len;
    int64_t stride, avail;
    uint32_t W, H;
    int bits16, color_type;
    uint8_t  lut8[256];
    uint16_t lut16[256];
    char **on;
    int64_t n_on;
    const char *out_dir;
    _Atomic int64_t cursor;
    _Atomic int64_t mism;
    _Atomic int64_t badidx;     /* unparseable / out-of-range filenames */
    _Atomic int64_t err_taken;
    _Atomic uint64_t bytes_ok;
    verify_report *rep;
} bshared;

static void fill_luts_for(const opngx_params *p, uint8_t *l8, uint16_t *l16) {
    double b, c, g = 1.0;
    switch (p->mode) {
    case OPNGX_MODE_RAW:    b = 0; c = 0; break;
    case OPNGX_MODE_CUSTOM: b = p->brightness; c = p->contrast; g = p->gamma > 0 ? p->gamma : 1.0; break;
    default:                b = p->brightness; c = p->contrast; g = p->gamma > 0 ? p->gamma : 1.0; break;
    }
    opngx_build_lut8(l8, b, c, g);
    opngx_build_lut16(l16, b, c, g);
}

static int bverify_one(bshared *bs, const char *name) {
    /* filename → absolute frame index */
    size_t plen = strlen(bs->p->prefix), elen = strlen(bs->p->ext);
    size_t L = strlen(name);
    if (L <= plen + elen || memcmp(name, bs->p->prefix, plen) ||
        memcmp(name + L - elen, bs->p->ext, elen)) {
        atomic_fetch_add(&bs->badidx, 1);
        return 0;
    }
    int64_t idx = 0;
    for (size_t k = plen; k < L - elen; k++) {
        if (name[k] < '0' || name[k] > '9') {
            atomic_fetch_add(&bs->badidx, 1);
            return 0;
        }
        idx = idx * 10 + (name[k] - '0');
    }
    if (idx >= bs->avail) {
        atomic_fetch_add(&bs->badidx, 1);
        return 0;
    }

    const uint32_t W = bs->W, H = bs->H;
    const unsigned bpp = (bs->color_type == 0 ? 1u : 4u) * (bs->bits16 ? 2u : 1u);
    const size_t raw_len = (size_t)H * ((size_t)W * bpp + 1);

    uint8_t *scratch = malloc(raw_len);
    uint8_t *qref = malloc((size_t)W * H * bpp);
    int rc = -1;
    png_view v;
    uint8_t *q = NULL;
    char why[256] = "";
    if (!scratch || !qref) goto out;

    {
        const uint8_t *frame = bs->map + (size_t)idx * (size_t)bs->stride + 8;
        if (bs->color_type == 0) {
            if (bs->bits16) opngx_expand_gray16(frame, W, H, bs->lut16, scratch);
            else            opngx_expand_gray8 (frame, W, H, bs->lut8,  scratch);
        } else {
            if (bs->bits16) opngx_expand_rgba16(frame, W, H, bs->lut16, scratch);
            else            opngx_expand_rgba8 (frame, W, H, bs->lut8,  scratch);
        }
        for (uint32_t y = 0; y < H; y++)
            memcpy(qref + (size_t)y * W * bpp,
                   scratch + (size_t)y * (W * bpp + 1) + 1, W * bpp);
    }

    {
        char path[1200];
        snprintf(path, sizeof path, "%.500s/%.600s", bs->out_dir, name);
        if (load_png_pixels(path, &v, &q, NULL, why, sizeof why)) goto out;
    }

    rc = pixels_differ(&v, q,
                       &(png_view){
                           .w = W, .h = H,
                           .bit_depth = (uint32_t)(bs->bits16 ? 16 : 8),
                           .color_type = (uint32_t)bs->color_type,
                       }, qref,
                       &(uint64_t){ 0 });
    if (!rc)
        atomic_fetch_add(&bs->bytes_ok, (uint64_t)W * H * bpp);

out:
    free(scratch);
    free(qref);
    free(q);
    if (rc && !atomic_exchange(&bs->err_taken, 1))
        snprintf(bs->rep->first_error, sizeof bs->rep->first_error, "%s",
                 why[0] ? why : "pixel mismatch vs source bin");
    return rc;
}

static void bworker(const port_worker_ctx *w, void *ud) {
    (void)w;
    bshared *bs = ud;
    const int64_t G = 64;
    for (;;) {
        int64_t i = atomic_fetch_add_explicit(&bs->cursor, G,
                                              memory_order_relaxed);
        if (i >= bs->n_on) break;
        int64_t end = i + G < bs->n_on ? i + G : bs->n_on;
        for (; i < end; i++)
            if (bverify_one(bs, bs->on[i]))
                atomic_fetch_add(&bs->mism, 1);
    }
}

int opngx_verify_bin(const opngx_params *pin, verify_report *rep,
                     char *err, size_t err_cap) {
    if (err && err_cap) err[0] = '\0';
    verify_report_init(rep);
    opngx_params p = *pin;
    /* normalize naming defaults once — workers must never see NULL */
    char pfx[64], extv[64];
    snprintf(pfx, sizeof pfx, "%s",
             p.prefix && p.prefix[0] ? p.prefix : "brow_");
    snprintf(extv, sizeof extv, "%s",
             p.ext && p.ext[0] ? p.ext : ".Png");
    p.prefix = pfx;
    p.ext = extv;

    footage_t ft;
    int have_ft = 0;
    int ref_mode = p.mode == OPNGX_MODE_REFERENCE;

    if (!(p.width && p.height) || ref_mode) {
        /* geometry may come from the sidecar AND reference B/C always does */
        if (!have_ft && p.footage_path && p.footage_path[0])
            have_ft = footage_load(p.footage_path, &ft) == 0;
        if (!have_ft) {
            snprintf(err, err_cap,
                     "unknown geometry / reference mode needs a .footage "
                     "sidecar (or use --mode custom/raw with --width/--height)");
            return -1;
        }
        if (!(p.width && p.height)) {
            p.width = ft.resolution_x;
            p.height = ft.resolution_y;
        }
        if (ref_mode) {
            p.brightness = ft.brightness;
            p.contrast = ft.contrast;
            p.gamma = ft.gamma > 0 ? ft.gamma : 1.0;
        }
    }

    opngx_mapped_file mf;
    if (port_map_file(p.bin_path, &mf)) {
        snprintf(err, err_cap, "cannot map '%s'", p.bin_path);
        return -1;
    }

    bshared bs;
    memset(&bs, 0, sizeof bs);
    bs.p = &p;
    bs.map = mf.map;
    bs.map_len = mf.len;
    bs.W = p.width;
    bs.H = p.height;
    bs.bits16 = p.bit_depth == 16;
    bs.color_type = p.channels == 0 ? 0 : 6;
    bs.out_dir = p.out_dir && p.out_dir[0] ? p.out_dir : ".";
    bs.stride = p.frame_stride > 0
        ? p.frame_stride
        : (int64_t)(8 + (size_t)p.width * p.height);
    int64_t cap_frames = (int64_t)(mf.len / (size_t)bs.stride);
    bs.avail = p.num_frames >= 0 && p.num_frames < cap_frames ? p.num_frames
                                                              : cap_frames;
    fill_luts_for(&p, bs.lut8, bs.lut16);

    int rc = list_names(bs.out_dir, p.prefix, p.ext, &bs.on, &bs.n_on);
    if (rc) {
        port_unmap_file(&mf);
        snprintf(err, err_cap, "cannot scan dir '%s': %s",
                 bs.out_dir, strerror(errno));
        return -1;
    }

    rep->files_ref = bs.avail;   /* frames addressable in the bin */
    rep->files_out = bs.n_on;
    rep->set_equal = (bs.n_on == bs.avail);
    bs.rep = rep;
    bs.cursor = 0;

    port_spawn_workers(port_cpu_count(), bworker, &bs);

    rep->files_compared = bs.n_on - atomic_load(&bs.badidx);
    rep->bytes_compared = atomic_load(&bs.bytes_ok);
    rep->mismatched_files = atomic_load(&bs.mism);

    int badidx = atomic_load(&bs.badidx) > 0;
    if (rep->mismatched_files && !atomic_load(&bs.err_taken))
        snprintf(rep->first_error, sizeof rep->first_error,
                 "%lld file(s) differ from source bin",
                 (long long)rep->mismatched_files);
    if (badidx && !atomic_load(&bs.err_taken) && !rep->mismatched_files) {
        char note[96];
        snprintf(note, sizeof note, "%lld output file(s) outside bin range/naming",
                 (long long)atomic_load(&bs.badidx));
        size_t cur = strlen(rep->first_error);
        if (cur && cur + 3 < sizeof rep->first_error)
            rep->first_error[cur++] = ';', rep->first_error[cur++] = ' ';
        snprintf(rep->first_error + cur, sizeof rep->first_error - cur, "%s", note);
    }

    for (int64_t i = 0; i < bs.n_on; i++) free(bs.on[i]);
    free(bs.on);
    port_unmap_file(&mf);

    if (rep->mismatched_files || badidx) return 1;
    return rep->files_compared > 0 ? 0 : 1;
}
