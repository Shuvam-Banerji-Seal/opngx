/*
 * opngx.h — Public API for the opngx extraction engine.
 *
 * Optronis TimeViewer .bin footage → PNG extractor.
 * Frame layout (reverse-engineered, see docs/FORMAT.md):
 *   per frame: [u64 LE timestamp][W*H bytes, 1 byte/pixel grayscale]
 *   no global file header.
 *
 * Copyright (c) 2026 — MIT License
 */
#ifndef OPNGX_H
#define OPNGX_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define OPNGX_VERSION "2.0.4"

/* Default DEFLATE level (v2.0.4: was 6). Measured on all five project
 * recordings with libdeflate: level 1 is 2.8-4.3x faster than 6 for files
 * only 1.0-1.7% larger; pixels are identical at every level. */
#define OPNGX_DEFAULT_LEVEL 1
#define OPNGX_ABI_VERSION 5

/* Output formats */
typedef enum {
    OPNGX_FMT_PNG = 0,
    OPNGX_FMT_BMP = 1,
    OPNGX_FMT_TIF = 2,
    OPNGX_FMT_JPG = 3
} opngx_format;

/* Quality modes */
typedef enum {
    OPNGX_MODE_REFERENCE = 0, /* replicate vendor display transform (B/C from footage) */
    OPNGX_MODE_RAW       = 1, /* identity LUT — sensor-faithful, no clipping            */
    OPNGX_MODE_CUSTOM    = 2  /* user brightness/contrast/gamma                          */
} opngx_mode;

/* Compression backends */
typedef enum {
    OPNGX_BACKEND_AUTO      = 0, /* libdeflate if available, else zlib */
    OPNGX_BACKEND_LIBDEFLATE= 1,
    OPNGX_BACKEND_ZLIB      = 2
} opngx_backend;

typedef struct {
    /* input */
    const char *bin_path;
    const char *footage_path;   /* optional XML sidecar (may be NULL) */
    uint32_t    width;
    uint32_t    height;
    int64_t     num_frames;     /* -1 => derive from XML/filesize */
    int64_t     frame_stride;   /* -1 => 8 + width*height         */

    /* transform */
    opngx_mode  mode;
    double      brightness;     /* used by REFERENCE (from XML) / CUSTOM */
    double      contrast;       /* multiplier = 1 + contrast/50          */
    double      gamma;          /* 1.0 = off                             */
    /* FIX-1: bitmask of transform fields that REFERENCE mode should take
     * from the sidecar instead of using the values above.
     *   1 = brightness, 2 = contrast, 4 = gamma; 0 = use the values above.
     * A user-supplied transform must never be silently discarded, and a
     * field the user did not supply must still fall back to the vendor
     * value — hence a per-field mask rather than one on/off switch.
     * python/src/opngx/extractor.py resolves the transform itself and
     * always passes 0. */
    int         use_sidecar_transform;
    int         bit_depth;      /* 8 (default) or 16 (PNG only)          */
    int         channels;       /* 6 = RGBA (default), 0 = grayscale     */
    int         format;         /* OPNGX_FMT_*                            */
    int         jpeg_quality;   /* 1..100, used when format == JPEG       */

    /* region of interest (cycle 22). crop_w/crop_h == 0 mean "to the frame
     * edge" (cycle 23; v1.7.0 wrongly expanded 0 to the full width).
     * Output geometry becomes crop_w x crop_h; output pixel (x,y) is the
     * LUT-mapped source pixel (crop_x + x, crop_y + y). Must satisfy
     * 0 <= crop_x < W, 0 <= crop_y < H, crop_w >= 1, crop_h >= 1 and
     * crop_x + crop_w <= W, crop_y + crop_h <= H. */
    uint32_t    crop_x;
    uint32_t    crop_y;
    uint32_t    crop_w;         /* 0 => to the right edge  */
    uint32_t    crop_h;         /* 0 => to the bottom edge */

    /* output */
    const char *out_dir;
    const char *prefix;         /* default "brow_"                       */
    const char *ext;            /* default ".Png"                        */

    /* engine */
    int          jobs;          /* <=0 => all cores                      */
    int          level;         /* deflate level (clamped per backend)   */
    opngx_backend backend;

    /* extra data export */
    int export_timestamps;      /* write <prefix>_timestamps.csv         */
    int export_metadata;        /* write metadata.json                   */

    /* misc */
    int verbose;

    /* ADD-6: optional push-progress callback. Invoked from worker threads
     * at most every ~100 ms and exactly once at completion with the final
     * totals. Bindings must marshal to their own UI thread. May be NULL. */
    void (*progress_fn)(int64_t done, int64_t total, void *user);
    void *progress_user;
} opngx_params;

/* Statistics returned by a run */
typedef struct {
    int64_t  frames_written;
    int64_t  frames_total;
    uint64_t bytes_written;
    double   seconds;           /* wall time of run()                    */
    double   mib_per_s_in;      /* input throughput                      */
    double   frames_per_s;
    char     backend_used[32];
} opngx_stats;

/* Opaque job handle (shared-library API with progress/cancel) */
typedef struct opngx_job opngx_job;

opngx_job *opngx_job_create(const opngx_params *p, char *err, size_t err_cap);
int        opngx_job_run(opngx_job *job);              /* 0 = ok */
void       opngx_job_free(opngx_job *job);
const char *opngx_job_errstr(const opngx_job *job);
int64_t    opngx_progress_done(const opngx_job *job);
int64_t    opngx_progress_total(const opngx_job *job);
void       opngx_cancel(opngx_job *job);               /* cooperative, thread-safe */
const opngx_stats *opngx_job_stats(const opngx_job *job);

/* One-shot convenience (used by CLI): run + fill stats. Returns 0 on success. */
int opngx_extract(const opngx_params *p, opngx_stats *stats,
                  char *err, size_t err_cap);

/* ---- analysis kernels (v2.0, src/analysis.c) ------------------------
 * Native versions of the analysis-module hot paths. Single-threaded and
 * re-entrant per call; frames are k contiguous (h, w) uint8 images. */
typedef struct {
    int    method;        /* 0 = circle (+ridge refine), 1 = centroid, 2 = peak */
    int    window;        /* search window edge (px), >= 1                    */
    double threshold;     /* fraction between window median (0) and peak (1)  */
    int    min_pixels;    /* fewer above-threshold pixels => not found        */
    int    locate_block;  /* coarse-search block (px)                          */
    int    refine;        /* circle: ridge refinement on/off                  */
    int    origin_x;      /* full-frame offset of frame (0,0): aligns the     */
    int    origin_y;      /*   coarse grid so a crop never moves the search   */
} opngx_track_params;

/* Track one spot/ring per frame. Outputs are k-long arrays; positions are
 * in frame coordinates (add the crop origin for full-frame). Returns 0,
 * -1 on bad arguments, -2 on allocation failure. */
int opngx_track(const uint8_t *frames, int64_t k, int h, int w,
                const opngx_track_params *p,
                double *x, double *y, double *radius, double *peak,
                double *area, int8_t *found, double *fit_rms);

/* k frames of npx pixels -> k x 256 int64 histograms. Returns 0 / -1. */
int opngx_hist256(const uint8_t *frames, int64_t k, int64_t npx, int64_t *out);

/* Utilities */
const char *opngx_version(void);
int opngx_abi_version(void);   /* ABI handshake for ctypes bindings */
int opngx_detect_gpus(char *buf, size_t cap);   /* newline-separated GPU descriptions */
int opngx_cpu_count(void);

#ifdef __cplusplus
}
#endif
#endif /* OPNGX_H */
