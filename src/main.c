/*
 * main.c — opngx-engine CLI
 *
 * Subcommands:
 *   extract  — extract PNGs from one .bin (+ optional sidecars)
 *   batch    — walk a directory of .bin files, extract each
 *   verify   — pixel-exact comparison of two directories
 *   info     — show metadata for a bin/footage pair + machine capabilities
 *   bench    — timed extraction on a frame subrange
 */
#include "opngx.h"
#include "footage.h"
#include "verify.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <dirent.h>
#include <unistd.h>

static void usage(void) {
    fputs(
"opngx-engine " OPNGX_VERSION " — Optronis .bin -> PNG extraction engine\n"
"\n"
"Usage:\n"
"  opngx-engine extract --bin FILE [--footage FILE] --out DIR [options]\n"
"  opngx-engine batch   --in-dir DIR --out-root DIR [options]\n"
"  opngx-engine verify  REF_DIR OUT_DIR [--prefix brow] [--ext .Png]\n"
"  opngx-engine info    [--bin FILE] [--footage FILE]\n"
"  opngx-engine bench   --bin FILE [--frames N] [--jobs N] [--level N]\n"
"                       [--backend auto|libdeflate|zlib] [--repeat R]\n"
"\n"
"Extract options:\n"
"  -m, --mode MODE        reference | raw | custom      (default: reference)\n"
"      --brightness F     custom brightness            (default 0)\n"
"      --contrast F       custom contrast              (default 0)\n"
"      --gamma F          custom gamma (1 = off)       (default 1)\n"
"      --bit-depth N      8 or 16                      (default 8)\n"
"      --channels C       rgba (6, default) or gray (0 fast path)\n"
"      --prefix S         output filename prefix       (default: brow_)\n"
"      --ext S            output extension             (default: .Png)\n"
"  -j, --jobs N           worker threads               (default: all cores)\n"
"  -l, --level N          deflate level                (default: 6)\n"
"      --backend B        auto | libdeflate | zlib\n"
"      --width N --height N  override geometry (else from footage)\n"
"      --start N          first frame index            (default 0)\n"
"      --frames N         number of frames             (default: all)\n"
"      --timestamps       export per-frame timestamps CSV\n"
"      --metadata         export metadata.json\n"
"  -v, --verbose          progress output\n"
"  -h, --help\n", stderr);
}

typedef struct { int64_t start, frames; } range_t;

static int parse_i64(const char *s, int64_t *out) {
    char *end; long long v = strtoll(s, &end, 10);
    if (!s[0] || *end) return -1;
    *out = v; return 0;
}
static int parse_mode(const char *s, opngx_mode *m) {
    if (!strcasecmp(s, "reference")) *m = OPNGX_MODE_REFERENCE;
    else if (!strcasecmp(s, "raw") || !strcasecmp(s, "linear")) *m = OPNGX_MODE_RAW;
    else if (!strcasecmp(s, "custom")) *m = OPNGX_MODE_CUSTOM;
    else return -1;
    return 0;
}
static int parse_backend(const char *s, opngx_backend *b) {
    if (!strcasecmp(s, "auto")) *b = OPNGX_BACKEND_AUTO;
    else if (!strcasecmp(s, "libdeflate")) *b = OPNGX_BACKEND_LIBDEFLATE;
    else if (!strcasecmp(s, "zlib")) *b = OPNGX_BACKEND_ZLIB;
    else return -1;
    return 0;
}

static void print_stats(const opngx_stats *st) {
    fprintf(stderr,
        "opngx: %lld/%lld frames in %.2fs | %.0f frames/s | %.1f MiB/s input | backend=%s\n",
        (long long)st->frames_written, (long long)st->frames_total, st->seconds,
        st->frames_per_s, st->mib_per_s_in, st->backend_used);
}

/* ---- extract ---- */
static int cmd_extract(int argc, char **argv) {
    opngx_params p; memset(&p, 0, sizeof p);
    p.num_frames = -1; p.frame_stride = -1; p.mode = OPNGX_MODE_REFERENCE;
    p.jobs = opngx_cpu_count(); p.level = 6; p.backend = OPNGX_BACKEND_AUTO;
    p.bit_depth = 8; p.gamma = 1.0;
    p.channels = 6;
    const char *bin = NULL, *footage = NULL, *outdir = NULL;
    range_t rng = {0, -1};
    int verbose = 0;

    for (int i = 0; i < argc; i++) {
        const char *a = argv[i];
        #define NEXTSTR(var) do { \
            if (++i >= argc) { fprintf(stderr, "missing value after %s\n", a); return 2; } \
            (var) = argv[i]; \
        } while (0)
        #define NEXTFUN(var, fn) do { \
            if (++i >= argc) { fprintf(stderr, "missing value after %s\n", a); return 2; } \
            (var) = fn(argv[i]); \
        } while (0)
        #define NEXTPARSE(var, fn) do { \
            if (++i >= argc) { fprintf(stderr, "missing value after %s\n", a); return 2; } \
            if (fn(argv[i], &(var))) { fprintf(stderr, "bad value for %s: %s\n", a, argv[i]); return 2; } \
        } while (0)
        if (!strcmp(a, "--bin") || !strcmp(a, "-b")) NEXTSTR(bin);
        else if (!strcmp(a, "--footage") || !strcmp(a, "-f")) NEXTSTR(footage);
        else if (!strcmp(a, "--out") || !strcmp(a, "-o")) NEXTSTR(outdir);
        else if (!strcmp(a, "--mode") || !strcmp(a, "-m")) NEXTPARSE(p.mode, parse_mode);
        else if (!strcmp(a, "--brightness")) NEXTFUN(p.brightness, atof);
        else if (!strcmp(a, "--contrast")) NEXTFUN(p.contrast, atof);
        else if (!strcmp(a, "--gamma")) NEXTFUN(p.gamma, atof);
        else if (!strcmp(a, "--bit-depth")) NEXTFUN(p.bit_depth, atoi);
        else if (!strcmp(a, "--channels")) {
            /* 6 = RGBA (default), 0 = grayscale fast path */
            if (++i >= argc) { fprintf(stderr, "missing value after %s\n", a); return 2; }
            if (!strcmp(argv[i], "gray") || !strcmp(argv[i], "0")) p.channels = 0;
            else if (!strcmp(argv[i], "rgba") || !strcmp(argv[i], "6")) p.channels = 6;
            else { fprintf(stderr, "bad channels: %s\n", argv[i]); return 2; }
        }
        else if (!strcmp(a, "--prefix")) NEXTSTR(p.prefix);
        else if (!strcmp(a, "--ext")) NEXTSTR(p.ext);
        else if (!strcmp(a, "--jobs") || !strcmp(a, "-j")) NEXTFUN(p.jobs, atoi);
        else if (!strcmp(a, "--level") || !strcmp(a, "-l")) NEXTFUN(p.level, atoi);
        else if (!strcmp(a, "--backend")) NEXTPARSE(p.backend, parse_backend);
        else if (!strcmp(a, "--width")) { int64_t t; NEXTPARSE(t, parse_i64); p.width = (uint32_t)t; }
        else if (!strcmp(a, "--height")) { int64_t t; NEXTPARSE(t, parse_i64); p.height = (uint32_t)t; }
        else if (!strcmp(a, "--start")) NEXTPARSE(rng.start, parse_i64);
        else if (!strcmp(a, "--frames")) NEXTPARSE(rng.frames, parse_i64);
        else if (!strcmp(a, "--timestamps")) p.export_timestamps = 1;
        else if (!strcmp(a, "--metadata")) p.export_metadata = 1;
        else if (!strcmp(a, "--verbose") || !strcmp(a, "-v")) verbose = 1;
        else if (!strcmp(a, "--help") || !strcmp(a, "-h")) { usage(); return 0; }
        else { fprintf(stderr, "unknown option: %s\n", a); return 2; }
        #undef NEXTSTR
        #undef NEXTFUN
        #undef NEXTPARSE
    }
    if (!bin || !outdir) { usage(); return 2; }
    if (rng.start < 0 || rng.frames < -1) { fprintf(stderr, "bad range\n"); return 2; }

    /* subrange support: wrap params via num_frames + a temp offset is not in the
     * engine API; instead use --start by adjusting num_frames semantics here:
     * engine extracts [0, num_frames). For bench/subset we pass start through
     * a dedicated field below. */
    p.bin_path = bin; p.footage_path = footage; p.out_dir = outdir;
    p.verbose = verbose;

    char err[512] = "";
    opngx_job *job = opngx_job_create(&p, err, sizeof err);
    if (!job) { fprintf(stderr, "opngx: error: %s\n", err); return 1; }

    /* apply range: engine always starts at 0; emulate --start by skipping via
     * num_frames only when start==0. For start>0 we expose it as full run of
     * requested count beginning at start using the public struct: */
    extern int64_t opngx__set_range(opngx_job*, int64_t start, int64_t frames);
    if (rng.start > 0 || rng.frames >= 0)
        opngx__set_range(job, rng.start, rng.frames);

    int rc = opngx_job_run(job);
    print_stats(opngx_job_stats(job));
    opngx_job_free(job);
    if (rc == 2) { fprintf(stderr, "opngx: cancelled\n"); return 130; }
    if (rc != 0) { fprintf(stderr, "opngx: error: %s\n", err[0] ? err : "run failed"); return 1; }
    return 0;
}

/* ---- batch ---- */
static int cmd_batch(int argc, char **argv) {
    const char *indir = NULL, *outroot = NULL, *prefix = NULL;
    int jobs = opngx_cpu_count(), level = 6;
    int timestamps = 0, metadata = 0;
    const char *mode_s = "reference";
    for (int i = 0; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--in-dir")) indir = argv[++i];
        else if (!strcmp(a, "--out-root")) outroot = argv[++i];
        else if (!strcmp(a, "--prefix")) prefix = argv[++i];
        else if (!strcmp(a, "--jobs") || !strcmp(a, "-j")) jobs = atoi(argv[++i]);
        else if (!strcmp(a, "--level") || !strcmp(a, "-l")) level = atoi(argv[++i]);
        else if (!strcmp(a, "--mode") || !strcmp(a, "-m")) mode_s = argv[++i];
        else if (!strcmp(a, "--timestamps")) timestamps = 1;
        else if (!strcmp(a, "--metadata")) metadata = 1;
        else { fprintf(stderr, "unknown option: %s\n", a); return 2; }
    }
    if (!indir || !outroot) { usage(); return 2; }
    opngx_mode mode;
    if (parse_mode(mode_s, &mode)) { fprintf(stderr, "bad mode\n"); return 2; }

    DIR *d = opendir(indir);
    if (!d) { perror("opendir"); return 1; }
    char bins[256][1024]; int nbins = 0;
    struct dirent *e;
    /* scan indir and one nesting level (vendor layout: <root>/<cam>/<name>.bin) */
    while ((e = readdir(d)) && nbins < 256) {
        if (e->d_name[0] == '.') continue;
        char sub[1100];
        snprintf(sub, sizeof sub, "%.900s/%.150s", indir, e->d_name);
        DIR *sd = opendir(sub);
        if (sd) {
            struct dirent *se;
            while ((se = readdir(sd)) && nbins < 256) {
                size_t L = strlen(se->d_name);
                if (L > 4 && !strcmp(se->d_name + L - 4, ".bin"))
                    snprintf(bins[nbins++], sizeof bins[0], "%.900s/%.100s", sub, se->d_name);
            }
            closedir(sd);
        } else {
            size_t L = strlen(e->d_name);
            if (L > 4 && !strcmp(e->d_name + L - 4, ".bin"))
                snprintf(bins[nbins++], sizeof bins[0], "%.1000s", sub);
        }
    }
    closedir(d);

    int rc_all = 0;
    for (int k = 0; k < nbins; k++) {
        char foot[1200], outdir[1200], stem[1024];
        snprintf(stem, sizeof stem, "%.1020s", bins[k]);
        size_t sl = strlen(stem); if (sl > 4) stem[sl-4] = '\0';
        snprintf(foot, sizeof foot, "%.1190s.footage", stem);
        /* dir name: basename with '.' -> '_' */
        const char *base = strrchr(stem, '/'); base = base ? base+1 : stem;
        snprintf(outdir, sizeof outdir, "%.1000s/%.180s", outroot, base);
        for (char *q = outdir + strlen(outroot) + 1; *q; q++) if (*q == '.') *q = '_';

        fprintf(stderr, "opngx: batch %d/%d: %s -> %s\n", k+1, nbins, bins[k], outdir);
        opngx_params p; memset(&p, 0, sizeof p);
        p.bin_path = bins[k]; p.footage_path = foot; p.out_dir = outdir;
        p.prefix = prefix;
        p.mode = mode; p.jobs = jobs; p.level = level; p.backend = OPNGX_BACKEND_AUTO;
        p.bit_depth = 8; p.gamma = 1.0;
        p.channels = 6;
        p.num_frames = -1; p.frame_stride = -1;
        p.export_timestamps = timestamps; p.export_metadata = metadata;

        char err[512] = "";
        int rc = opngx_extract(&p, NULL, err, sizeof err);
        if (rc != 0 && rc != 2) { fprintf(stderr, "opngx: error: %s\n", err); rc_all = 1; }
    }
    return rc_all;
}

/* ---- verify ---- */
static int cmd_verify(int argc, char **argv) {
    const char *ref = NULL, *out = NULL, *prefix = "brow_", *ext = ".Png";
    int positional = 0, subset = 0;
    for (int i = 0; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--prefix")) prefix = argv[++i];
        else if (!strcmp(a, "--ext")) ext = argv[++i];
        else if (!strcmp(a, "--subset")) subset = 1; /* out must be a correct subset of ref */
        else if (!positional) { ref = a; positional++; }
        else if (positional == 1) { out = a; positional++; }
        else { fprintf(stderr, "too many args\n"); return 2; }
    }
    if (!ref || !out) { fprintf(stderr, "usage: opngx-engine verify REF OUT [--prefix P] [--ext E] [--subset]\n"); return 2; }
    verify_report rep;
    char err[512] = "";
    int rc = opngx_verify(ref, out, prefix, ext, &rep, err, sizeof err);
    printf("ref files:    %lld\n", (long long)rep.files_ref);
    printf("out files:    %lld\n", (long long)rep.files_out);
    printf("compared:     %lld\n", (long long)rep.files_compared);
    printf("bytes equal:  %llu\n", (unsigned long long)rep.bytes_compared);
    printf("mismatches:   %lld\n", (long long)rep.mismatched_files);
    int names_ok = subset ? (rep.files_out <= rep.files_ref && rep.mismatched_files == 0)
                          : rep.set_equal;
    printf("name sets:    %s\n", rep.set_equal ? "EQUAL" :
                                    (names_ok ? "SUBSET-OK" : "DIFFER"));
    if (rep.first_error[0]) printf("first error:  %s\n", rep.first_error);
    if (rc < 0) { fprintf(stderr, "error: %s\n", err); return 1; }
    int pass = (rc == 0 && names_ok && rep.files_out > 0);
    printf("RESULT: %s%s\n", pass ? "PASS (pixel-exact)" : "FAIL",
           subset ? " [subset mode]" : "");
    return pass ? 0 : 1;
}

/* ---- info ---- */
static int cmd_info(int argc, char **argv) {
    const char *bin = NULL, *footage = NULL;
    for (int i = 0; i < argc; i++) {
        if (!strcmp(argv[i], "--bin")) bin = argv[++i];
        else if (!strcmp(argv[i], "--footage")) footage = argv[++i];
    }
    printf("opngx-engine %s\n", opngx_version());
    printf("cpus:         %d\n", opngx_cpu_count());
    char gpus[2048];
    if (opngx_detect_gpus(gpus, sizeof gpus) > 0) {
        printf("gpus:\n%s", gpus);
    } else {
        printf("gpus:         none detected\n");
    }
    if (bin) {
        footage_t ft; memset(&ft, 0, sizeof ft);
        char fpath[1200];
        if (!footage) {
            size_t L = strlen(bin);
            snprintf(fpath, sizeof fpath, "%.*s.footage", (int)(L > 4 ? L-4 : L), bin);
            footage = fpath;
        }
        if (footage_load(footage, &ft) == 0) {
            printf("camera:       %s\n", ft.camera_name);
            printf("resolution:   %ux%u\n", ft.resolution_x, ft.resolution_y);
            printf("num_images:   %lld\n", (long long)ft.num_images);
            printf("framerate:    %g\n", ft.framerate);
            printf("exposure_us:  %g\n", ft.exposure);
            printf("processing:   B=%.0f C=%.0f G=%g (%s)\n", ft.brightness, ft.contrast, ft.gamma,
                   (ft.brightness==49 && ft.contrast==18 && ft.gamma==1) ?
                   "verified operating point" : "UNVERIFIED for fidelity");
        } else {
            printf("footage:      not available (%s)\n", footage);
        }
        if (bin) {
            FILE *fp = fopen(bin, "rb");
            if (fp) {
                fseek(fp, 0, SEEK_END); long sz = ftell(fp); fclose(fp);
                printf("bin_size:     %ld bytes\n", sz);
                if (ft.resolution_x && ft.resolution_y) {
                    long long stride = 8 + (long long)ft.resolution_x*ft.resolution_y;
                    printf("frame_stride: %lld => capacity %lld frames\n",
                           stride, (long long)(sz / stride));
                }
            }
        }
    }
    return 0;
}

/* ---- bench ---- */
static int cmd_bench(int argc, char **argv) {
    const char *bin = NULL, *backend_s = "auto";
    int64_t frames = 2000;
    int jobs = opngx_cpu_count(), level = 6, repeat = 1;
    for (int i = 0; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--bin")) bin = argv[++i];
        else if (!strcmp(a, "--frames")) frames = strtoll(argv[++i], NULL, 10);
        else if (!strcmp(a, "--jobs") || !strcmp(a, "-j")) jobs = atoi(argv[++i]);
        else if (!strcmp(a, "--level") || !strcmp(a, "-l")) level = atoi(argv[++i]);
        else if (!strcmp(a, "--backend")) backend_s = argv[++i];
        else if (!strcmp(a, "--repeat")) repeat = atoi(argv[++i]);
        else { fprintf(stderr, "unknown option: %s\n", a); return 2; }
    }
    if (!bin) { fprintf(stderr, "bench needs --bin\n"); return 2; }
    opngx_backend be;
    if (parse_backend(backend_s, &be)) { fprintf(stderr, "bad backend\n"); return 2; }

    /* auto-detect sibling .footage so reference mode works */
    char footpath[1100];
    {
        size_t L = strlen(bin);
        snprintf(footpath, sizeof footpath, "%.*s.footage", (int)(L > 4 ? L - 4 : L), bin);
    }

    printf("jobs,level,backend,frames,seconds,frames_per_s,mib_per_s_in\n");
    double best = 0;
    for (int r = 0; r < repeat; r++) {
        char outdir[64]; snprintf(outdir, sizeof outdir, "/tmp/opngxbench-%d-%d", getpid(), r);
        opngx_params p; memset(&p, 0, sizeof p);
        p.bin_path = bin; p.footage_path = footpath; p.out_dir = outdir;
        p.mode = OPNGX_MODE_REFERENCE; p.jobs = jobs; p.level = level; p.backend = be;
        p.bit_depth = 8; p.gamma = 1.0;
        p.num_frames = frames; p.frame_stride = -1;
        char err[512] = "";
        opngx_stats st;
        int rc = opngx_extract(&p, &st, err, sizeof err);
        if (rc != 0) { fprintf(stderr, "bench failed: %s\n", err); return 1; }
        printf("%d,%d,%s,%lld,%.3f,%.1f,%.1f\n", jobs, level, st.backend_used,
               (long long)st.frames_written, st.seconds, st.frames_per_s, st.mib_per_s_in);
        if (st.frames_per_s > best) best = st.frames_per_s;
        /* cleanup */
        char cmd[128]; snprintf(cmd, sizeof cmd, "rm -rf '%s'", outdir);
        if (system(cmd)) {}
    }
    fprintf(stderr, "best: %.1f frames/s\n", best);
    return 0;
}

int main(int argc, char **argv) {
    /* Full-core utilization defaults: bind threads to CPUs and use all
     * physical+logical processors unless the user overrides. Honored by
     * GNU/LLVM OpenMP; ignored where unsupported. */
#ifndef _WIN32
    setenv("OMP_PROC_BIND", "close", 0);      /* don't clobber user config */
    setenv("OMP_SCHEDULE", "dynamic,32", 0);
#endif
    if (argc < 2) { usage(); return 2; }
    const char *cmd = argv[1];
    if (!strcmp(cmd, "-h") || !strcmp(cmd, "--help") || !strcmp(cmd, "help")) { usage(); return 0; }
    if (!strcmp(cmd, "--version") || !strcmp(cmd, "version")) { puts("opngx-engine " OPNGX_VERSION); return 0; }
    if (!strcmp(cmd, "extract")) return cmd_extract(argc-2, argv+2);
    if (!strcmp(cmd, "batch"))   return cmd_batch(argc-2, argv+2);
    if (!strcmp(cmd, "verify"))  return cmd_verify(argc-2, argv+2);
    if (!strcmp(cmd, "info"))    return cmd_info(argc-2, argv+2);
    if (!strcmp(cmd, "bench"))   return cmd_bench(argc-2, argv+2);
    usage();
    return 2;
}
