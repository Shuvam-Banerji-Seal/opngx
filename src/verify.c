/*
 * verify.c — pixel-exact verification of extracted PNGs against reference dirs.
 *
 * Compares decoded raw scanlines (post-inflate) byte-for-byte, which is a
 * complete proof of pixel equality for identical geometry/color type.
 */
#include "verify.h"
#include "pngout.h"
#include "compress.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <errno.h>
#include <stdatomic.h>
#include <stdlib.h>

#ifdef _OPENMP
#include <omp.h>
#endif

#if defined(OPNGX_HAVE_LIBDEFLATE)
#include <libdeflate.h>
static int zinflate(const uint8_t *in, size_t in_len, uint8_t *out, size_t out_len) {
    struct libdeflate_decompressor *d = libdeflate_alloc_decompressor();
    if (!d) return -1;
    enum libdeflate_result r =
        libdeflate_zlib_decompress(d, in, in_len, out, out_len, NULL);
    libdeflate_free_decompressor(d);
    return r == LIBDEFLATE_SUCCESS ? 0 : -1;
}
#else
#include <zlib.h>
static int zinflate(const uint8_t *in, size_t in_len, uint8_t *out, size_t out_len) {
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

    /* compare intersection (index-aligned since sorted; stop at min) */
    int64_t common = rn_n < on_n ? rn_n : on_n;
    int64_t mism = 0;
    uint64_t bytes_ok = 0;
    _Atomic int err_taken = 0;   /* only the FIRST failure records its text */

    #pragma omp parallel for schedule(dynamic, 64) reduction(+:mism,bytes_ok)
    for (int64_t i = 0; i < common; i++) {
        /* per-thread file buffers via malloc inside loop body scope */
        char p1[1200], p2[1200];
        snprintf(p1, sizeof p1, "%s/%s", ref_dir, rn[i]);
        snprintf(p2, sizeof p2, "%s/%s", out_dir, on[i]);
        FILE *f1 = fopen(p1, "rb"), *f2 = fopen(p2, "rb");
        if (!f1 || !f2) {
            if (!atomic_exchange(&err_taken, 1))
                snprintf(rep->first_error, sizeof rep->first_error,
                         "open failed: %.400s", f1 ? p2 : p1);
            mism++; if (f1) fclose(f1); if (f2) fclose(f2);
            continue;
        }
        fseek(f1, 0, SEEK_END); long l1 = ftell(f1); fseek(f1, 0, SEEK_SET);
        fseek(f2, 0, SEEK_END); long l2 = ftell(f2); fseek(f2, 0, SEEK_SET);
        if (l1 <= 0 || l2 <= 0) {
            #pragma omp critical
            { if (!atomic_load(&err_taken)) { atomic_store(&err_taken, 1);
              snprintf(rep->first_error, sizeof rep->first_error, "empty file: %.300s", p1); } }
            mism++; if (f1) fclose(f1); if (f2) fclose(f2);
            continue;
        }
        uint8_t *b1 = malloc((size_t)l1), *b2 = malloc((size_t)l2);
        if (!b1 || !b2) {
            free(b1); free(b2); fclose(f1); fclose(f2);
            mism++;
            continue;
        }
        size_t rd1 = fread(b1, 1, (size_t)l1, f1);
        size_t rd2 = fread(b2, 1, (size_t)l2, f2);
        fclose(f1); fclose(f2);
        png_view v1, v2;
        int bad = 0;
        if (rd1 != (size_t)l1 || rd2 != (size_t)l2 ||
            png_parse(b1, rd1, &v1) || png_parse(b2, rd2, &v2)) bad = 1;
        else if (v1.w != v2.w || v1.h != v2.h) bad = 1;
        /* bit-depth / color-type differences are handled below via
         * cross-layout comparison (gray channel vs RGBA channels) */
        else {
            unsigned ch1 = v1.color_type == 0 ? 1u : 4u;
            unsigned ch2 = v2.color_type == 0 ? 1u : 4u;
            unsigned bpp1 = ch1 * (v1.bit_depth == 16 ? 2u : 1u);
            unsigned bpp2 = ch2 * (v2.bit_depth == 16 ? 2u : 1u);
            size_t raw1 = (size_t)v1.h * ((size_t)v1.w * bpp1 + 1);
            size_t raw2 = (size_t)v2.h * ((size_t)v2.w * bpp2 + 1);
            uint8_t *r1 = malloc(raw1), *r2 = malloc(raw2);
            size_t pixbytes1 = (size_t)v1.h * v1.w * bpp1;
            size_t pixbytes2 = (size_t)v2.h * v2.w * bpp2;
            uint8_t *p1 = malloc(pixbytes1), *p2 = malloc(pixbytes2);
            int ok = r1 && r2 && p1 && p2 &&
                     zinflate(v1.idat, v1.idat_len, r1, raw1) == 0 &&
                     zinflate(v2.idat, v2.idat_len, r2, raw2) == 0 &&
                     png_unfilter(r1, v1.w, v1.h, bpp1) == 0 &&
                     png_unfilter(r2, v2.w, v2.h, bpp2) == 0;
            if (!ok) {
                bad = 1;
            } else if (ch1 != ch2 || v1.bit_depth != v2.bit_depth) {
                /* cross-layout comparison: gray channel must equal R=G=B */
                png_strip_filters(r1, v1.w, v1.h, bpp1, p1);
                png_strip_filters(r2, v2.w, v2.h, bpp2, p2);
                const uint32_t W = v1.w < v2.w ? v1.w : v2.w;
                const uint32_t H = v1.h < v2.h ? v1.h : v2.h;
                /* first sample of each pixel: R when RGBA, the value when gray */
                for (uint32_t y = 0; y < H && !bad; y++) {
                    const uint8_t *row1 = p1 + (size_t)y * v1.w * bpp1;
                    const uint8_t *row2 = p2 + (size_t)y * v2.w * bpp2;
                    for (uint32_t x = 0; x < W; x++) {
                        if (row1[x * bpp1] != row2[x * bpp2]) { bad = 1; break; }
                    }
                }
                if (!bad) bytes_ok += (uint64_t)W * H;
            } else {
                png_strip_filters(r1, v1.w, v1.h, bpp1, p1);
                png_strip_filters(r2, v2.w, v2.h, bpp2, p2);
                if (memcmp(p1, p2, pixbytes1)) bad = 1;
                else bytes_ok += (uint64_t)pixbytes1;
            }
            free(r1); free(r2); free(p1); free(p2);
        }
        free(v1.idat); free(v2.idat);
        free(b1); free(b2);
        if (bad) {
            if (!atomic_exchange(&err_taken, 1))
                snprintf(rep->first_error, sizeof rep->first_error,
                         "pixel mismatch: %.200s vs %.200s", p1, p2);
            mism++;
        }
    }

    rep->files_compared = common;
    rep->bytes_compared = bytes_ok;
    rep->mismatched_files = mism;
    if (mism && !atomic_load(&err_taken)) {
        snprintf(rep->first_error, sizeof rep->first_error,
                 "%lld file(s) differ", (long long)mism);
    } else if (mism && atomic_load(&err_taken) && rep->set_equal) {
        /* keep recorded first_error as-is */
    }

    for (int64_t i = 0; i < rn_n; i++) { free(rn[i]); }
    free(rn);
    for (int64_t i = 0; i < on_n; i++) { free(on[i]); }
    free(on);
    return mism ? 1 : 0;
}
