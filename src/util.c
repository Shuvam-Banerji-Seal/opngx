/* util.c — machine capability detection (CPUs, GPUs) */
#include "opngx.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>

/*
 * Dependency-free GPU enumeration via sysfs PCI IDs:
 *   /sys/class/drm/cardN/device/vendor  0x1002 = AMD, 0x10de = NVIDIA, 0x8086 = Intel
 * Names resolved from the 'product' sysfs attribute when present.
 */
int opngx_detect_gpus(char *buf, size_t cap) {
    static const struct { unsigned vid; const char *name; } vendors[] = {
        {0x1002, "AMD"}, {0x10de, "NVIDIA"}, {0x8086, "Intel"},
    };
    size_t off = 0;
    int found = 0;
    DIR *d = opendir("/sys/class/drm");
    if (!d) return 0;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (strncmp(e->d_name, "card", 4)) continue;
        char base[512];
        snprintf(base, sizeof base, "/sys/class/drm/%s/device", e->d_name);
        char vpath[600];
        snprintf(vpath, sizeof vpath, "%s/vendor", base);
        FILE *f = fopen(vpath, "r");
        if (!f) continue;
        unsigned vid = 0;
        int ok = fscanf(f, "%x", &vid) == 1;
        fclose(f);
        if (!ok) continue;
        const char *vname = NULL;
        for (size_t k = 0; k < sizeof vendors / sizeof vendors[0]; k++)
            if (vendors[k].vid == vid) { vname = vendors[k].name; break; }
        if (!vname) continue;

        char prod[256] = "";
        snprintf(vpath, sizeof vpath, "%s/product", base);
        f = fopen(vpath, "r");
        if (f) {
            if (!fgets(prod, sizeof prod, f)) prod[0] = '\0';
            fclose(f);
            size_t L = strlen(prod);
            while (L && (prod[L-1] == '\n' || prod[L-1] == '\r')) prod[--L] = '\0';
        }
        char devid[32] = "";
        snprintf(vpath, sizeof vpath, "%s/device", base);
        f = fopen(vpath, "r");
        if (f) { if (fscanf(f, "%31s", devid) != 1) devid[0] = '\0'; fclose(f); }

        int n;
        if (prod[0])
            n = snprintf(buf + off, cap - off, "  %s (%s, %s, %s)\n", e->d_name, vname, prod, devid);
        else
            n = snprintf(buf + off, cap - off, "  %s (%s, %s)\n", e->d_name, vname, devid);
        if (n > 0 && off + (size_t)n < cap) off += (size_t)n;
        found++;
    }
    closedir(d);
    return found;
}
