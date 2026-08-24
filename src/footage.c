/* footage.c — minimal, dependency-free XML sidecar reader.
 *
 * The Optronis .footage file is a small flat XML document. We only need a
 * handful of scalar tags, so a targeted string scan is sufficient and avoids
 * pulling in an XML library. Tags are matched case-sensitively as emitted by
 * the vendor tool.
 */
#include "footage.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

void footage_defaults(footage_t *f) {
    memset(f, 0, sizeof(*f));
    f->num_images = -1;
    f->framerate = -1;
    f->framerate_real = -1;
    f->exposure = -1;
    f->time_marker_ref = -1;
    f->gamma = 1.0;
}

static const char *find_tag(const char *xml, const char *tag) {
    char pat[96];
    snprintf(pat, sizeof pat, "<%s>", tag);
    const char *p = strstr(xml, pat);
    if (!p) return NULL;
    return p + strlen(pat);
}

static int parse_i64(const char *xml, const char *tag, int64_t *out) {
    const char *v = find_tag(xml, tag);
    if (!v) return -1;
    char *end = NULL;
    long long r = strtoll(v, &end, 10);
    if (end == v) return -1;
    *out = (int64_t)r;
    return 0;
}

static int parse_dbl(const char *xml, const char *tag, double *out) {
    const char *v = find_tag(xml, tag);
    if (!v) return -1;
    char *end = NULL;
    double r = strtod(v, &end);
    if (end == v) return -1;
    *out = r;
    return 0;
}

static void parse_str(const char *xml, const char *tag, char *dst, size_t cap) {
    const char *v = find_tag(xml, tag);
    if (!v) { dst[0] = '\0'; return; }
    const char *e = strchr(v, '<');
    size_t n = e ? (size_t)(e - v) : strlen(v);
    if (n >= cap) n = cap - 1;
    memcpy(dst, v, n);
    dst[n] = '\0';
    /* trim whitespace/CRLF */
    size_t L = strlen(dst);
    while (L && isspace((unsigned char)dst[L-1])) dst[--L] = '\0';
}

int footage_load(const char *path, footage_t *f) {
    footage_defaults(f);
    FILE *fp = fopen(path, "rb");
    if (!fp) return -1;
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return -2; }
    long sz = ftell(fp);
    if (sz <= 0 || sz > (4L << 20)) { fclose(fp); return -2; } /* sanity: ≤4 MiB */
    rewind(fp);
    char *xml = malloc((size_t)sz + 1);
    if (!xml) { fclose(fp); return -2; }
    size_t rd = fread(xml, 1, (size_t)sz, fp);
    fclose(fp);
    xml[rd] = '\0';

    int64_t iv;
    double dv;
    if (parse_i64(xml, "ResolutionX", &iv) == 0) f->resolution_x = (uint32_t)iv;
    if (parse_i64(xml, "ResolutionY", &iv) == 0) f->resolution_y = (uint32_t)iv;
    if (parse_i64(xml, "NumberOfImages", &iv) == 0) f->num_images = iv;
    if (parse_dbl(xml, "Framerate", &dv) == 0) f->framerate = dv;
    if (parse_dbl(xml, "FramerateReal", &dv) == 0) f->framerate_real = dv;
    if (parse_dbl(xml, "Exposure", &dv) == 0) f->exposure = dv;
    if (parse_i64(xml, "TimeMarkerReference", &iv) == 0) f->time_marker_ref = iv;

    const char *proc = strstr(xml, "<SettingsProcessing>");
    if (proc) {
        f->has_processing = 1;
        if (parse_dbl(proc, "Brightness", &dv) == 0) f->brightness = dv;
        if (parse_dbl(proc, "Contrast", &dv) == 0) f->contrast = dv;
        if (parse_dbl(proc, "Gamma", &dv) == 0 && dv > 0.0) f->gamma = dv;
    }
    parse_str(xml, "Name", f->camera_name, sizeof f->camera_name);

    free(xml);

    if (f->resolution_x == 0 || f->resolution_y == 0) return -2;
    return 0;
}
