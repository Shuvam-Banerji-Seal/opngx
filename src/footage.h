/* footage.h — minimal parser for Optronis .footage XML sidecars */
#ifndef OPNGX_FOOTAGE_H
#define OPNGX_FOOTAGE_H
#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint32_t resolution_x;
    uint32_t resolution_y;
    int64_t  num_images;
    double   framerate;
    double   framerate_real;   /* achieved capture rate (vendor tag) */
    double   exposure;
    int64_t  time_marker_ref;
    double   brightness;
    double   contrast;
    double   gamma;
    char     camera_name[256];
    int      has_processing;      /* SettingsProcessing section present */
} footage_t;

/* Returns 0 on success. Missing file => -1; malformed => -2. */
int footage_load(const char *path, footage_t *f);
void footage_defaults(footage_t *f);
#endif
