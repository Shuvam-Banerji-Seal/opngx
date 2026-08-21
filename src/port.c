/* port.c — see port.h */
#include "port.h"

#include <stdio.h>
#include <string.h>
#include <errno.h>

/* ------------------------------------------------------------------ */
#ifdef _WIN32
/* ============================ Windows ============================= */

int port_map_file(const char *path, opngx_mapped_file *out) {
    memset(out, 0, sizeof *out);
    HANDLE fh = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL,
                            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (fh == INVALID_HANDLE_VALUE) return -1;
    LARGE_INTEGER sz;
    if (!GetFileSizeEx(fh, &sz) || sz.QuadPart <= 0) {
        CloseHandle(fh);
        return -1;
    }
    HANDLE fm = CreateFileMappingA(fh, NULL, PAGE_READONLY,
                                   (DWORD)((uint64_t)sz.QuadPart >> 32),
                                   (DWORD)(uint64_t)sz.QuadPart, NULL);
    if (!fm) { CloseHandle(fh); return -1; }
    void *view = MapViewOfFile(fm, FILE_MAP_READ, 0, 0, 0);
    if (!view) { CloseHandle(fm); CloseHandle(fh); return -1; }
    out->map = view;
    out->len = (size_t)sz.QuadPart;
    out->_handle = fh;
    out->_handle2 = fm;
    return 0;
}

void port_unmap_file(opngx_mapped_file *m) {
    if (m->map) UnmapViewOfFile(m->map);
    if (m->_handle2) CloseHandle((HANDLE)m->_handle2);
    if (m->_handle) CloseHandle((HANDLE)m->_handle);
    memset(m, 0, sizeof *m);
}

int port_write_whole_file(const char *path, const void *buf, size_t n) {
    HANDLE fh = CreateFileA(path, GENERIC_WRITE, 0, NULL,
                            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (fh == INVALID_HANDLE_VALUE) return -1;
    size_t off = 0;
    while (off < n) {
        DWORD chunk = (n - off > 0x40000000u) ? 0x40000000u : (DWORD)(n - off);
        DWORD written = 0;
        if (!WriteFile(fh, (const char *)buf + off, chunk, &written, NULL) ||
            written != chunk) {
            CloseHandle(fh);
            return -1;
        }
        off += written;
    }
    CloseHandle(fh);
    return 0;
}

int port_mkdir_p(const char *path) {
    char tmp[1024];
    size_t len = strlen(path);
    if (len == 0 || len >= sizeof tmp) return -1;
    memcpy(tmp, path, len + 1);
    for (char *q = tmp + 1; *q; q++)
        if (*q == '/' || *q == '\\') {
            char keep = *q; *q = '\0';
            if (!CreateDirectoryA(tmp, NULL) &&
                GetLastError() != ERROR_ALREADY_EXISTS)
                return -1;
            *q = keep;
        }
    if (!CreateDirectoryA(tmp, NULL) && GetLastError() != ERROR_ALREADY_EXISTS)
        return -1;
    return 0;
}

/* GPU enumeration via Display Devices (adapter descriptions). */
int port_detect_gpus(char *buf, size_t cap) {
    int found = 0;
    size_t off = 0;
    for (DWORD i = 0; off < cap; i++) {
        DISPLAY_DEVICEA dd;
        dd.cb = sizeof dd;
        if (!EnumDisplayDevicesA(NULL, i, &dd, 0)) break;
        if (!(dd.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP)) continue;
        int n = snprintf(buf + off, cap - off, "  adapter%lu (%s)\n",
                         (unsigned long)i, dd.DeviceString);
        if (n <= 0 || off + (size_t)n >= cap) break;
        off += (size_t)n;
        found++;
    }
    return found;
}

double port_now_s(void) {
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
}

int port_cpu_count(void) {
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    int n = (int)si.dwNumberOfProcessors;
    return n > 0 ? n : 1;
}

#else
/* ========================= POSIX / Linux / macOS ==================== */
#include <stdlib.h>
#include <time.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>

int port_map_file(const char *path, opngx_mapped_file *out) {
    memset(out, 0, sizeof *out);
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    struct stat st;
    if (fstat(fd, &st) || st.st_size <= 0) { close(fd); errno = EINVAL; return -1; }
    void *p = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (p == MAP_FAILED) { close(fd); return -1; }
    madvise(p, (size_t)st.st_size, MADV_SEQUENTIAL);
#ifdef MADV_HUGEPAGE
    madvise(p, (size_t)st.st_size, MADV_HUGEPAGE);   /* best effort */
#endif
    out->map = p;
    out->len = (size_t)st.st_size;
    out->_handle = (void *)(intptr_t)fd;
    return 0;
}

void port_unmap_file(opngx_mapped_file *m) {
    if (m->map) munmap((void *)m->map, m->len);
    if (m->_handle) close((int)(intptr_t)m->_handle);
    memset(m, 0, sizeof *m);
}

int port_write_whole_file(const char *path, const void *buf, size_t n) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) return -1;
    size_t off = 0;
    while (off < n) {
        ssize_t w = write(fd, (const char *)buf + off, n - off);
        if (w <= 0) {
            if (errno == EINTR) continue;
            close(fd);
            return -1;
        }
        off += (size_t)w;
    }
    close(fd);
    return 0;
}

static int mkdir_posix(const char *p) { return mkdir(p, 0755); }

int port_mkdir_p(const char *path) {
    char tmp[1024];
    size_t len = strlen(path);
    if (len == 0 || len >= sizeof tmp) return -1;
    memcpy(tmp, path, len + 1);
    while (len > 1 && tmp[len-1] == '/') tmp[--len] = '\0';
    for (char *q = tmp + 1; *q; q++) {
        if (*q == '/') {
            *q = '\0';
            if (mkdir_posix(tmp) && errno != EEXIST) return -1;
            *q = '/';
        }
    }
    if (mkdir_posix(tmp) && errno != EEXIST) return -1;
    return 0;
}

/* sysfs PCI enumeration (Linux); returns 0 entries elsewhere. */
int port_detect_gpus(char *buf, size_t cap) {
#if defined(__linux__)
    static const struct { unsigned vid; const char *name; } vendors[] = {
        {0x1002, "AMD"}, {0x10de, "NVIDIA"}, {0x8086, "Intel"},
    };
    int found = 0;
    size_t off = 0;
    DIR *d = opendir("/sys/class/drm");
    if (!d) return 0;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (strncmp(e->d_name, "card", 4)) continue;
        char base[512], vpath[600];
        snprintf(base, sizeof base, "/sys/class/drm/%s/device", e->d_name);
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

        char devid[32] = "";
        snprintf(vpath, sizeof vpath, "%s/device", base);
        f = fopen(vpath, "r");
        if (f) { if (fscanf(f, "%31s", devid) != 1) devid[0] = '\0'; fclose(f); }

        int n = snprintf(buf + off, cap - off, "  %s (%s, %s)\n",
                         e->d_name, vname, devid);
        if (n > 0 && off + (size_t)n < cap) off += (size_t)n;
        found++;
    }
    closedir(d);
    return found;
#else
    (void)buf; (void)cap;
    return 0;
#endif
}

double port_now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + 1e-9 * (double)ts.tv_nsec;
}

int port_cpu_count(void) {
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    return n > 0 ? (int)n : 1;
}
#endif
