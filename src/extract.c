/*
 * extract.c — parallel extraction engine.
 *
 * Design notes (see plans/plan.md):
 *  - input is mmap'ed read-only; frames are seek-addressable => perfect parallelism
 *  - one thread-local compressor + buffers per worker (no locks in hot path)
 *  - progress via atomics; cooperative cancel checked per frame
 *  - writes are single-shot write() syscalls; kernel page cache absorbs bursts
 */
#include "opngx.h"
#include "footage.h"
#include "transform.h"
#include "pngout.h"
#include "compress.h"
#include "port.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdatomic.h>
#include <ctype.h>

#ifdef _OPENMP
#include <omp.h>
#endif

struct opngx_job {
    /* owned copies */
    char *bin_path, *footage_path, *out_dir, *prefix, *ext;

    opngx_params p;
    uint8_t  lut8[256];
    uint16_t lut16[256];

    int64_t  stride;
    int64_t  frames_total;
    int64_t  start_index;    /* first frame index (for subrange/bench) */
    size_t   raw_len;        /* filtered-scanline bytes */
    int      color_type;     /* PNG color type in use (6 or 0) */
    size_t   idat_cap;
    size_t   file_cap;

    opngx_mapped_file mf;
    uint8_t *map;            /* == mf.map (convenience) */
    size_t   map_len;        /* == mf.len               */

    _Atomic int64_t done;
    _Atomic int     cancel;
    _Atomic int     backend_seen;   /* first worker reports real backend */
    _Atomic long long last_ms;      /* progress throttle (monotonic ms)   */

    opngx_stats stats;
    char err[512];
};

static void fill_luts(opngx_job *j) {
    double b, c, g;
    switch (j->p.mode) {
    case OPNGX_MODE_RAW:      b = 0; c = 0; g = 1; break;
    case OPNGX_MODE_CUSTOM:   b = j->p.brightness; c = j->p.contrast; g = j->p.gamma; break;
    case OPNGX_MODE_REFERENCE:
    default:                  b = j->p.brightness; c = j->p.contrast; g = j->p.gamma; break;
    }
    opngx_build_lut8(j->lut8, b, c, g);
    opngx_build_lut16(j->lut16, b, c, g);
}

opngx_job *opngx_job_create(const opngx_params *pin, char *err, size_t err_cap) {
    if (err && err_cap) err[0] = '\0';
    opngx_job *j = calloc(1, sizeof(*j));
    if (!j) { if (err) snprintf(err, err_cap, "oom"); return NULL; }

    j->p = *pin;
    /* own the strings */
    j->bin_path   = strdup(pin->bin_path ? pin->bin_path : "");
    j->out_dir    = strdup(pin->out_dir ? pin->out_dir : ".");
    j->prefix     = strdup(pin->prefix ? pin->prefix : "brow_");
    j->ext        = strdup(pin->ext ? pin->ext : ".Png");
    j->footage_path = pin->footage_path ? strdup(pin->footage_path) : NULL;
    j->p.bin_path = j->bin_path; j->p.out_dir = j->out_dir;
    j->p.prefix = j->prefix; j->p.ext = j->ext; j->p.footage_path = j->footage_path;

    /* --- geometry resolution order: explicit > XML > error --- */
    footage_t ft;
    int have_ft = 0;
    if (j->footage_path && j->footage_path[0]) {
        if (footage_load(j->footage_path, &ft) == 0) have_ft = 1;
        else { snprintf(j->err, sizeof j->err, "cannot parse footage '%s'", j->footage_path); goto fail; }
    }
    if (j->p.width == 0 || j->p.height == 0) {
        if (!have_ft) { snprintf(j->err, sizeof j->err,
            "unknown geometry: provide --width/--height or a .footage sidecar"); goto fail; }
        j->p.width = ft.resolution_x;
        j->p.height = ft.resolution_y;
    }
    if (j->p.mode == OPNGX_MODE_REFERENCE) {
        if (!have_ft) { snprintf(j->err, sizeof j->err,
            "reference mode needs a .footage sidecar (for Brightness/Contrast)"); goto fail; }
        j->p.brightness = ft.brightness;
        j->p.contrast = ft.contrast;
        j->p.gamma = ft.gamma;
        if (!(ft.brightness == 49.0 && ft.contrast == 18.0 && ft.gamma == 1.0))
            fprintf(stderr, "opngx: WARNING: footage settings (B=%.0f C=%.0f G=%g) differ from the "
                    "verified operating point (B=49 C=18 G=1); pixel fidelity not guaranteed.\n",
                    ft.brightness, ft.contrast, ft.gamma);
    }

    j->stride = j->p.frame_stride > 0 ? j->p.frame_stride : (int64_t)(8 + (size_t)j->p.width * j->p.height);

    /* --- map input --- */
    if (port_map_file(j->bin_path, &j->mf)) {
        snprintf(j->err, sizeof j->err, "cannot map '%s'", j->bin_path);
        goto fail;
    }
    j->map = (uint8_t *)j->mf.map;
    j->map_len = j->mf.len;

    /* --- frame count --- */
    int64_t cap_frames = (int64_t)(j->map_len / (size_t)j->stride);
    if (j->p.num_frames >= 0) j->frames_total = j->p.num_frames < cap_frames ? j->p.num_frames : cap_frames;
    else if (have_ft && ft.num_images > 0) j->frames_total = ft.num_images < cap_frames ? ft.num_images : cap_frames;
    else j->frames_total = cap_frames;
    if (j->frames_total <= 0) { snprintf(j->err, sizeof j->err, "no frames to extract"); goto fail; }

    /* --- buffers sizing --- */
    j->color_type = (j->p.channels == 0) ? 0 : 6;   /* 0 = gray fast path */
    size_t bytes_per_px;
    if (j->color_type == 0) bytes_per_px = (j->p.bit_depth == 16) ? 2 : 1;
    else                    bytes_per_px = (j->p.bit_depth == 16) ? 8 : 4;
    j->raw_len = (size_t)j->p.height * ((size_t)j->p.width * bytes_per_px + 1);
    j->idat_cap = j->raw_len + j->raw_len / 8 + 256; /* >= any deflate bound */
    j->file_cap = j->idat_cap + 128;

    fill_luts(j);
    atomic_store(&j->done, 0);
    atomic_store(&j->cancel, 0);
    memset(&j->stats, 0, sizeof j->stats);
    j->stats.frames_total = j->frames_total;
    return j;

fail:
    if (err && err_cap) { strncpy(err, j->err, err_cap - 1); err[err_cap-1] = '\0'; }
    if (j->mf.map || j->mf._handle) port_unmap_file(&j->mf);
    free(j->bin_path); free(j->out_dir); free(j->prefix); free(j->ext); free(j->footage_path);
    free(j);
    return NULL;
}

/* ---- timestamps pre-pass: read u64 LE headers sequentially ---- */
static int write_timestamps(opngx_job *j) {
    char path[1200];
    snprintf(path, sizeof path, "%s/%s_timestamps.csv", j->out_dir, j->prefix);
    FILE *fp = fopen(path, "w");
    if (!fp) { snprintf(j->err, sizeof j->err, "open %.380s: %s", path, strerror(errno)); return -1; }
    fprintf(fp, "frame_index,timestamp_raw,timestamp_hex\n");
    for (int64_t i = 0; i < j->frames_total; i++) {
        uint64_t ts = 0;
        memcpy(&ts, j->map + (size_t)(j->start_index + i) * (size_t)j->stride, 8); /* LE on LE hosts */
        fprintf(fp, "%lld,%llu,0x%016llX\n", (long long)(j->start_index + i),
                (unsigned long long)ts, (unsigned long long)ts);
    }
    fclose(fp);
    return 0;
}

/* ---- metadata.json ---- */
static int write_metadata(opngx_job *j, const footage_t *ft) {
    char path[1200];
    snprintf(path, sizeof path, "%s/metadata.json", j->out_dir);
    FILE *fp = fopen(path, "w");
    if (!fp) { snprintf(j->err, sizeof j->err, "open %.380s: %s", path, strerror(errno)); return -1; }
    fprintf(fp, "{\n");
    fprintf(fp, "  \"engine\": \"opngx %s\",\n", OPNGX_VERSION);
    fprintf(fp, "  \"source_bin\": \"%s\",\n", j->bin_path);
    fprintf(fp, "  \"width\": %u,\n", j->p.width);
    fprintf(fp, "  \"height\": %u,\n", j->p.height);
    fprintf(fp, "  \"frames\": %lld,\n", (long long)j->frames_total);
    fprintf(fp, "  \"frame_stride_bytes\": %lld,\n", (long long)j->stride);
    fprintf(fp, "  \"mode\": \"%s\",\n",
            j->p.mode == OPNGX_MODE_RAW ? "raw" :
            j->p.mode == OPNGX_MODE_CUSTOM ? "custom" : "reference");
    fprintf(fp, "  \"transform\": {\"brightness\": %.1f, \"contrast\": %.1f, \"gamma\": %g},\n",
            j->p.brightness, j->p.contrast, j->p.gamma);
    fprintf(fp, "  \"bit_depth\": %d,\n", j->p.bit_depth);
    if (ft && ft->camera_name[0]) fprintf(fp, "  \"camera_name\": \"%s\",\n", ft->camera_name);
    if (ft && ft->framerate > 0) fprintf(fp, "  \"framerate_nominal\": %g,\n", ft->framerate);
    if (ft && ft->exposure >= 0) fprintf(fp, "  \"exposure_us\": %g,\n", ft->exposure);

    /* timestamp-derived stats */
    if (j->frames_total > 1) {
        uint64_t t0, tN;
        memcpy(&t0, j->map, 8);
        memcpy(&tN, j->map + (size_t)(j->frames_total-1)*(size_t)j->stride, 8);
        double span = (double)tN - (double)t0;
        if (span > 0) {
            fprintf(fp, "  \"timestamp_first\": %llu,\n", (unsigned long long)t0);
            fprintf(fp, "  \"timestamp_last\": %llu,\n", (unsigned long long)tN);
            fprintf(fp, "  \"effective_fps_from_timestamps\": %.3f,\n",
                    (double)(j->frames_total-1) / (span / 1e6));
        }
    }
    fprintf(fp, "  \"backend\": \"%s\"\n", j->stats.backend_used);
    fprintf(fp, "}\n");
    fclose(fp);
    return 0;
}

/* ---- parallel extraction core ---- */
int opngx_job_run(opngx_job *j) {
    if (!j) return -1;
    if (port_mkdir_p(j->out_dir)) { snprintf(j->err, sizeof j->err, "mkdir %.300s failed", j->out_dir); return -1; }

    /* optional sidecars first (cheap) */
    if (j->p.export_timestamps && write_timestamps(j)) return -1;

    const int64_t N = j->frames_total;
    const int64_t stride = j->stride;
    const int64_t base = j->start_index;
    const uint32_t W = j->p.width, H = j->p.height;
    const int bits16 = (j->p.bit_depth == 16);

    /* geometry sanity for mmap reads */
    if ((uint64_t)N * (uint64_t)stride > j->map_len) {
        snprintf(j->err, sizeof j->err, "file truncated: need %lld bytes, have %zu",
                 (long long)(N*stride), j->map_len);
        return -1;
    }

    double t0 = port_now_s();
    atomic_store(&j->done, 0);
    atomic_store(&j->backend_seen, 0);
    atomic_store(&j->last_ms, 0);
    const long long start_ms = (long long)(port_now_s() * 1000.0);
    int hard_fail = 0;

    #pragma omp parallel num_threads(j->p.jobs > 0 ? j->p.jobs : opngx_cpu_count()) \
                         reduction(|:hard_fail)
    {
        cctx *c = cctx_create(
            j->p.backend == OPNGX_BACKEND_ZLIB ? C_BACKEND_ZLIB :
            j->p.backend == OPNGX_BACKEND_LIBDEFLATE ? C_BACKEND_LIBDEFLATE :
            C_BACKEND_AUTO, j->p.level);
        uint8_t *scan = malloc(j->raw_len);
        uint8_t *idat = malloc(j->idat_cap);
        uint8_t *filebuf = malloc(j->file_cap);
        char path[1200];

        if (!c || !scan || !idat || !filebuf) hard_fail |= 1;

        #pragma omp for schedule(dynamic, 32)
        for (int64_t i = 0; i < N; i++) {
            if (atomic_load_explicit(&j->cancel, memory_order_relaxed)) continue;
            if (hard_fail || !c || !scan || !idat || !filebuf) continue;

            const uint8_t *frame = j->map + (size_t)(base + i) * (size_t)stride + 8;

            if (j->color_type == 0) {
                if (bits16) opngx_expand_gray16(frame, W, H, j->lut16, scan);
                else        opngx_expand_gray8 (frame, W, H, j->lut8,  scan);
            } else {
                if (bits16) opngx_expand_rgba16(frame, W, H, j->lut16, scan);
                else        opngx_expand_rgba8 (frame, W, H, j->lut8,  scan);
            }

            size_t idat_len = cctx_compress(c, scan, j->raw_len, idat + 6, j->idat_cap - 6);
            if (idat_len == 0) { hard_fail |= 2; continue; }

            /* wrap raw deflate into zlib stream; adler over uncompressed scan */
            size_t zlen = opngx_zlib_wrap(idat, j->idat_cap, idat + 6, idat_len,
                                          scan, j->raw_len);
            if (zlen != idat_len + 6) { hard_fail |= 4; continue; }

            size_t flen = opngx_png_assemble(filebuf, W, H, bits16 ? 16 : 8,
                                             j->color_type, idat, zlen);

            snprintf(path, sizeof path, "%s/%s%05lld%s", j->out_dir, j->prefix,
                     (long long)(base + i), j->ext);
            if (port_write_whole_file(path, filebuf, flen)) { hard_fail |= 8; continue; }
            long long done_now =
                atomic_fetch_add_explicit(&j->done, 1, memory_order_relaxed) + 1;

            /* live progress: any worker may claim the next 250ms slot */
            if (j->p.verbose) {
                long long ms = (long long)(port_now_s() * 1000.0);
                long long expected_ms = atomic_load(&j->last_ms);
                if (ms - expected_ms >= 250 &&
                    atomic_compare_exchange_strong(&j->last_ms, &expected_ms, ms)) {
                    double el = (ms - start_ms) / 1000.0;
                    double frac = (double)done_now / (double)N;
                    double eta = frac > 0.004 ? el / frac - el : 0.0;
                    fprintf(stderr, "\ropngx: %lld/%lld (%5.1f%%)  %7.0f fps  eta %4.0fs",
                            (long long)done_now, (long long)N, 100.0 * frac,
                            el > 0 ? done_now / el : 0.0, eta);
                    fflush(stderr);
                }
            }
        }

        cctx_free(c);
        free(scan); free(idat); free(filebuf);
    }

    double dt = port_now_s() - t0;
    snprintf(j->stats.backend_used, sizeof j->stats.backend_used, "%s",
             atomic_load(&j->backend_seen) == C_BACKEND_ZLIB ? "zlib" :
             "libdeflate");
    j->stats.seconds = dt;
    j->stats.frames_written = atomic_load(&j->done);
    j->stats.bytes_written = j->stats.frames_written *
        (uint64_t)(8 + (int64_t)W * H); /* input bytes consumed */
    j->stats.mib_per_s_in = dt > 0 ? (double)j->stats.bytes_written / (1048576.0 * dt) : 0;
    j->stats.frames_per_s = dt > 0 ? (double)j->stats.frames_written / dt : 0;
    if (j->p.verbose)
        fprintf(stderr, "\ropngx: %lld/%lld (100.0%%)%*s\n",
                (long long)j->stats.frames_written, (long long)N, 20, "");

    if (hard_fail) {
        snprintf(j->err, sizeof j->err, "extraction failed (mask 0x%x): see errno messages above", hard_fail);
        return -1;
    }
    if (atomic_load(&j->cancel)) return 2; /* cancelled */

    /* metadata last (needs backend name) */
    if (j->p.export_metadata) {
        footage_t ft; int ok = (j->footage_path && footage_load(j->footage_path, &ft) == 0);
        if (write_metadata(j, ok ? &ft : NULL)) return -1;
    }
    return 0;
}

void opngx_job_free(opngx_job *j) {
    if (!j) return;
    if (j->mf.map || j->mf._handle) port_unmap_file(&j->mf);
    free(j->bin_path); free(j->out_dir); free(j->prefix); free(j->ext); free(j->footage_path);
    free(j);
}

const char *opngx_job_errstr(const opngx_job *j) { return j ? j->err : ""; }
int64_t opngx_progress_done(const opngx_job *j) { return j ? atomic_load(&j->done) : 0; }
int64_t opngx_progress_total(const opngx_job *job) { return job ? job->frames_total : 0; }
void opngx_cancel(opngx_job *j) { if (j) atomic_store(&j->cancel, 1); }
const opngx_stats *opngx_job_stats(const opngx_job *j) { return j ? &j->stats : NULL; }

int opngx_extract(const opngx_params *p, opngx_stats *stats, char *err, size_t err_cap) {
    opngx_job *j = opngx_job_create(p, err, err_cap);
    if (!j) return -1;
    int rc = opngx_job_run(j);
    if (rc != 0 && err && err_cap) { strncpy(err, j->err, err_cap-1); err[err_cap-1]='\0'; }
    if (stats) *stats = j->stats;
    opngx_job_free(j);
    return rc;
}

const char *opngx_version(void) { return OPNGX_VERSION; }

/* subrange support for CLI bench/subset extraction */
int64_t opngx__set_range(opngx_job *j, int64_t start, int64_t frames) {
    if (!j) return -1;
    int64_t cap = (int64_t)(j->map_len / (size_t)j->stride);
    if (start < 0 || start >= cap) return -1;
    j->start_index = start;
    int64_t avail = cap - start;
    j->frames_total = (frames >= 0 && frames <= avail) ? frames : avail;
    j->stats.frames_total = j->frames_total;
    return j->frames_total;
}

int opngx_cpu_count(void) {
#ifdef _OPENMP
    return omp_get_max_threads();
#else
    return port_cpu_count();
#endif
}
