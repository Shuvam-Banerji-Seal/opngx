/* port.c — see port.h */
#include "port.h"

#include <stdio.h>
#include <string.h>
#include <errno.h>

/* ------------------------------------------------------------------ */
#ifdef _WIN32
/* ============================ Windows ============================= */
#include <io.h>
#include <fcntl.h>

/* The A-suffixed Win32 APIs use the system ANSI codepage, which is NOT
 * UTF-8: any non-ASCII path (C:\Users\José, D:\भीम\x.bin) would fail or
 * mangle. Python hands us UTF-8, so convert explicitly and use the W
 * APIs everywhere a path crosses into the kernel. */
static wchar_t *win_wpath(const char *u8) {
    /* Python hands us UTF-8, but a Windows ANSI `main` argv arrives in the
     * system codepage. MB_ERR_INVALID_CHARS is essential: without it an
     * invalid-UTF-8 byte "succeeds" as U+FFFD replacements and the correct
     * ACP interpretation never gets a chance (found via Wine: open err=3). */
    UINT cps[2] = { CP_UTF8, CP_ACP };
    UINT flags[2] = { MB_ERR_INVALID_CHARS, 0 };
    static int dbg = -1;
    if (dbg < 0) dbg = getenv("OPNGX_DEBUG_WPATH") ? 1 : 0;
    for (int i = 0; i < 2; i++) {
        int n = MultiByteToWideChar(cps[i], flags[i], u8, -1, NULL, 0);
        if (n <= 0) {
            if (dbg) fprintf(stderr, "[wpath] cp=%u FAILED err=%lu\n",
                             (unsigned)cps[i], (unsigned long)GetLastError());
            continue;
        }
        wchar_t *w = (wchar_t *)malloc((size_t)n * sizeof(wchar_t));
        if (!w) return NULL;
        if (MultiByteToWideChar(cps[i], flags[i], u8, -1, w, n) == n) {
            if (dbg) {
                fprintf(stderr, "[wpath] cp=%u n=%d wide:", (unsigned)cps[i], n);
                for (int k = 0; k < n && k < 24; k++)
                    fprintf(stderr, " %04x", (unsigned)w[k]);
                fprintf(stderr, "\n");
            }
            return w;
        }
        if (dbg) fprintf(stderr, "[wpath] cp=%u second pass failed\n",
                         (unsigned)cps[i]);
        free(w);
    }
    return NULL;
}

FILE *port_fopen_u8(const char *path, const char *mode) {
    /* _wfopen is unreliable (NULL even with a valid wide path on some
     * Windows/Wine msvcrt combinations). Go through the kernel handle:
     * CreateFileW -> _open_osfhandle -> _fdopen. */
    DWORD access = GENERIC_READ;
    DWORD disp = OPEN_EXISTING;
    int oflags = _O_RDONLY;
    if (strchr(mode, 'r')) {
        if (strchr(mode, '+')) { access |= GENERIC_WRITE; oflags = _O_RDWR; }
    } else if (strchr(mode, 'a')) {
        access = GENERIC_WRITE;
        disp = OPEN_ALWAYS;
        oflags = _O_WRONLY | _O_CREAT | _O_APPEND;
    } else { /* 'w' */
        access = GENERIC_WRITE;
        disp = CREATE_ALWAYS;
        oflags = _O_WRONLY | _O_CREAT | _O_TRUNC;
    }
    oflags |= strchr(mode, 'b') ? _O_BINARY : _O_TEXT;

    wchar_t *wp = win_wpath(path);
    if (!wp) return NULL;
    HANDLE h = CreateFileW(wp, access, FILE_SHARE_READ, NULL, disp,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    free(wp);
    if (h == INVALID_HANDLE_VALUE) return NULL;
    int fd = _open_osfhandle((intptr_t)h, oflags);
    if (fd < 0) { CloseHandle(h); return NULL; }
    FILE *fp = _fdopen(fd, mode);
    if (!fp) _close(fd);
    return fp;
}

int port_map_file(const char *path, opngx_mapped_file *out) {
    memset(out, 0, sizeof *out);
    wchar_t *wp = win_wpath(path);
    if (!wp) return -1;
    HANDLE fh = CreateFileW(wp, GENERIC_READ, FILE_SHARE_READ, NULL,
                            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    free(wp);
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
    wchar_t *wp = win_wpath(path);
    if (!wp) return -1;
    HANDLE fh = CreateFileW(wp, GENERIC_WRITE, 0, NULL,
                            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    free(wp);
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
            /* skip drive components ("X:") and empty ones — CreateDirectory
             * on a drive root returns an error that is NOT ALREADY_EXISTS,
             * which made every absolute-Windows-path output dir fail
             * (the field-reported SQ_100_s1 bug) */
            if (!(q - tmp == 2 && tmp[1] == ':') && q != tmp + 1) {
                wchar_t *wc = win_wpath(tmp);
                if (!wc) return -1;
                BOOL okc = CreateDirectoryW(wc, NULL);
                free(wc);
                if (!okc && GetLastError() != ERROR_ALREADY_EXISTS)
                    return -1;
            }
            *q = keep;
        }
    {
        wchar_t *wc = win_wpath(tmp);
        if (!wc) return -1;
        BOOL okc = CreateDirectoryW(wc, NULL);
        free(wc);
        if (!okc && GetLastError() != ERROR_ALREADY_EXISTS)
            return -1;
    }
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


/* ---------------- UTF-8 directory enumeration (Win32) ---------------- */
struct port_dir {
    HANDLE h;
    char *utf8_cur;                 /* entry RETURNED to the caller */
    char *utf8_next;                /* pre-read ahead entry         */
    int done;
};

port_dir *port_opendir(const char *u8path) {
    wchar_t *wp = win_wpath(u8path);
    if (!wp) return NULL;
    size_t wl = wcslen(wp);
    wchar_t *pattern = (wchar_t *)malloc((wl + 3) * sizeof(wchar_t));
    if (!pattern) { free(wp); return NULL; }
    memcpy(pattern, wp, wl * sizeof(wchar_t));
    pattern[wl] = L'\\'; pattern[wl + 1] = L'*'; pattern[wl + 2] = 0;
    port_dir *d = (port_dir *)calloc(1, sizeof *d);
    if (!d) { free(pattern); free(wp); return NULL; }
    d->utf8_cur = (char *)calloc(1, 1024);
    d->utf8_next = (char *)calloc(1, 1024);
    if (!d->utf8_cur || !d->utf8_next) {
        free(d->utf8_cur); free(d->utf8_next);
        free(d); free(pattern); free(wp);
        return NULL;
    }
    WIN32_FIND_DATAW fd;
    d->h = FindFirstFileW(pattern, &fd);
    free(pattern);
    free(wp);
    if (d->h == INVALID_HANDLE_VALUE) {
        free(d->utf8_cur); free(d->utf8_next); free(d);
        return NULL;
    }
    WideCharToMultiByte(CP_UTF8, 0, fd.cFileName, -1,
                        d->utf8_cur, 1024, NULL, NULL);
    return d;
}

const char *port_readdir_utf8(port_dir *d) {
    if (!d || d->done) return NULL;
    char *rv = d->utf8_cur;         /* the entry we promise to return */
    if (d->h == INVALID_HANDLE_VALUE) { d->done = 1; return NULL; }
    WIN32_FIND_DATAW fd;
    if (!FindNextFileW(d->h, &fd)) {
        FindClose(d->h);
        d->h = INVALID_HANDLE_VALUE;
        d->done = 1;
        return rv;                  /* last entry; next call -> NULL */
    }
    /* decode the NEXT entry into the spare buffer, then swap roles —
     * writing into utf8_cur would clobber the string we just returned */
    WideCharToMultiByte(CP_UTF8, 0, fd.cFileName, -1,
                        d->utf8_next, 1024, NULL, NULL);
    char *tmp = d->utf8_cur;
    d->utf8_cur = d->utf8_next;
    d->utf8_next = tmp;
    return rv;
}

void port_closedir(port_dir *d) {
    if (!d) return;
    if (d->h != INVALID_HANDLE_VALUE) FindClose(d->h);
    free(d->utf8_cur);
    free(d->utf8_next);
    free(d);
}

int port_remove_flat_dir(const char *path) {
    wchar_t *wp = win_wpath(path);
    if (!wp) return -1;
    size_t wl = wcslen(wp);
    wchar_t *pattern = (wchar_t *)malloc((wl + 3) * sizeof(wchar_t));
    if (!pattern) { free(wp); return -1; }
    memcpy(pattern, wp, wl * sizeof(wchar_t));
    pattern[wl] = L'\\'; pattern[wl + 1] = L'*'; pattern[wl + 2] = 0;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern, &fd);
    free(pattern);
    if (h == INVALID_HANDLE_VALUE) { free(wp); return -1; }
    do {
        if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L".."))
            continue;
        wchar_t *full = (wchar_t *)malloc((wl + 2 + wcslen(fd.cFileName) + 1)
                                          * sizeof(wchar_t));
        if (!full) continue;
        memcpy(full, wp, wl * sizeof(wchar_t));
        full[wl] = L'\\';
        wcscpy(full + wl + 1, fd.cFileName);
        DeleteFileW(full);
        free(full);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    BOOL removed = RemoveDirectoryW(wp);
    free(wp);
    return removed ? 0 : -1;
}


/* ------------------------- worker pool (Win32) ------------------- */
typedef struct {
    void (*fn)(const port_worker_ctx *, void *);
    void *shared;
    int index;
} win_job;

static DWORD WINAPI win_worker(LPVOID p) {
    win_job *j = (win_job *)p;
    port_worker_ctx ctx = { j->index };
    j->fn(&ctx, j->shared);
    return 0;
}

void port_spawn_workers(int jobs,
                        void (*fn)(const port_worker_ctx *, void *),
                        void *shared) {
    if (jobs < 1) jobs = 1;
    if (jobs == 1) {
        port_worker_ctx ctx = { 0 };
        fn(&ctx, shared);
        return;
    }
    HANDLE *th = (HANDLE *)calloc((size_t)jobs, sizeof(HANDLE));
    win_job *jb = (win_job *)calloc((size_t)jobs, sizeof(win_job));
    if (!th || !jb) { free(th); free(jb);
        port_worker_ctx ctx = { 0 }; fn(&ctx, shared); return; }
    long started = 0;
    for (int i = 1; i < jobs; i++) {
        jb[i].fn = fn; jb[i].shared = shared; jb[i].index = i;
        th[i] = CreateThread(NULL, 0, win_worker, &jb[i], 0, NULL);
        if (th[i]) started++; else th[i] = NULL;
    }
    port_worker_ctx root = { 0 };          /* main thread joins the pool */
    fn(&root, shared);
    WaitForMultipleObjects((DWORD)started, th + 1, TRUE, INFINITE);
    for (long k = 1; k <= started; k++) CloseHandle(th[k]);
    free(th); free(jb);
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
#include <dirent.h>

struct port_dir {
    DIR *dp;
    char name[1024];
};

port_dir *port_opendir(const char *u8path) {
    DIR *dp = opendir(u8path);
    if (!dp) return NULL;
    port_dir *d = (port_dir *)calloc(1, sizeof *d);
    if (!d) { closedir(dp); return NULL; }
    d->dp = dp;
    return d;
}

const char *port_readdir_utf8(port_dir *d) {
    if (!d) return NULL;
    struct dirent *e = readdir(d->dp);
    if (!e) return NULL;
    snprintf(d->name, sizeof d->name, "%s", e->d_name);
    return d->name;
}

void port_closedir(port_dir *d) {
    if (!d) return;
    if (d->dp) closedir(d->dp);
    free(d);
}


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

FILE *port_fopen_u8(const char *path, const char *mode) {
    return fopen(path, mode);   /* POSIX paths are bytes already */
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
    char seen[16][32];
    int nseen = 0;
    FILE *nv = fopen("/proc/driver/nvidia/version", "r");
    if (nv) {
        char line[256];
        if (fgets(line, sizeof line, nv)) {
            char *p = strstr(line, " NVRM: ");
            if (!p) p = line;
            int n = snprintf(buf + off, cap - off, "  nvidia (%.180s)\n",
                             p + (p != line ? 7 : 0));
            if (n > 0 && off + (size_t)n < cap) { off += (size_t)n; found++; }
        }
        fclose(nv);
    }

    DIR *d = opendir("/sys/class/drm");
    if (!d) return found;
    struct dirent *e;
    while ((e = readdir(d))) {
        /* accept both cardN and renderD* nodes: some setups expose only
         * render nodes for iGPUs */
        if (strncmp(e->d_name, "card", 4) &&
            strncmp(e->d_name, "renderD", 7)) continue;
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
        {
            char sig[64];
            snprintf(sig, sizeof sig, "%s:%s", vname, devid);
            int dup = 0;
            for (int k = 0; k < nseen; k++)
                if (!strcmp(seen[k], sig)) { dup = 1; break; }
            if (dup) continue;
            if (nseen < 16) snprintf(seen[nseen++], 32, "%s", sig);
        }
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

int port_remove_flat_dir(const char *path) {
    DIR *d = opendir(path);
    if (!d) return -1;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        char full[1200];
        snprintf(full, sizeof full, "%s/%s", path, e->d_name);
        unlink(full);
    }
    closedir(d);
    return rmdir(path);
}


/* ------------------------ worker pool (pthreads) ----------------- */
#include <pthread.h>
typedef struct {
    void (*fn)(const port_worker_ctx *, void *);
    void *shared;
    int index;
} px_job;

static void *px_worker(void *p) {
    px_job *j = (px_job *)p;
    port_worker_ctx ctx = { j->index };
    j->fn(&ctx, j->shared);
    return NULL;
}

void port_spawn_workers(int jobs,
                        void (*fn)(const port_worker_ctx *, void *),
                        void *shared) {
    if (jobs < 1) jobs = 1;
    if (jobs == 1) {
        port_worker_ctx ctx = { 0 };
        fn(&ctx, shared);
        return;
    }
    pthread_t *th = calloc((size_t)jobs, sizeof(pthread_t));
    px_job *jb = calloc((size_t)jobs, sizeof(px_job));
    if (!th || !jb) { free(th); free(jb);
        port_worker_ctx ctx = { 0 }; fn(&ctx, shared); return; }
    long started = 0;
    for (int i = 1; i < jobs; i++) {
        jb[i].fn = fn; jb[i].shared = shared; jb[i].index = i;
        if (pthread_create(&th[i], NULL, px_worker, &jb[i]) == 0) started++;
        else th[i] = (pthread_t)0;
    }
    port_worker_ctx root = { 0 };          /* main thread joins the pool */
    fn(&root, shared);
    for (long k = 1; k <= started; k++)
        if (th[k]) pthread_join(th[k], NULL);
    free(th); free(jb);
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
