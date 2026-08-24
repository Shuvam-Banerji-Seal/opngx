/* port.h — thin platform layer so the engine compiles unchanged on
 * Linux, Windows (MinGW/MSVC), macOS and anywhere POSIX-ish.
 *
 *  - file mapping (mmap / CreateFileMapping)
 *  - atomic whole-file writes
 *  - recursive mkdir
 *  - GPU enumeration (sysfs on Linux, EnumDisplayDevices on Windows)
 */
#ifndef OPNGX_PORT_H
#define OPNGX_PORT_H
#include <stdio.h>
#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
#  define WIN32_LEAN_AND_MEAN
#  include <windows.h>
#else
#  include <sys/stat.h>
#endif

typedef struct {
    const void *map;      /* read-only view of the whole file   */
    size_t      len;
    void       *_handle;  /* platform handle (fd or mapping)    */
    void       *_handle2;
} opngx_mapped_file;

/* Map `path` read-only. Returns 0 and fills `out` on success. */
int port_map_file(const char *path, opngx_mapped_file *out);
void port_unmap_file(opngx_mapped_file *m);

/* UTF-8 directory enumeration (Windows uses FindFirstFileW; POSIX wraps
 * opendir/readdir). Name stays valid until the next readdir call. */
typedef struct port_dir port_dir;
port_dir *port_opendir(const char *u8path);
const char *port_readdir_utf8(port_dir *d);
void port_closedir(port_dir *d);

/* fopen that accepts UTF-8 paths on Windows (ANSI-codepage safe). */
FILE *port_fopen_u8(const char *path, const char *mode);

/* Write the entire buffer to a new/truncated file. Returns 0 on success. */
int port_write_whole_file(const char *path, const void *buf, size_t n);

/* mkdir -p equivalent. Returns 0 on success (or already exists). */
int port_mkdir_p(const char *path);

/* Newline-separated GPU descriptions into buf; returns count found.
 * Portable: sysfs (Linux) / EnumDisplayDevices (Windows) / stub elsewhere. */
int port_detect_gpus(char *buf, size_t cap);

/* Remove a directory that contains only regular files (bench scratch dirs).
 * Returns 0 on success. */
int port_remove_flat_dir(const char *path);

/* Monotonic seconds for timing. */
double port_now_s(void);

/* Number of online CPUs. */
int port_cpu_count(void);

/* ---- cooperative worker pool (replaces the OpenMP dependency) ----
 * Runs `jobs` OS threads (>=1). Each invocation of `fn` receives a stable
 * worker index [0..jobs) plus the caller's shared pointer. Threads that
 * throw nothing and simply return end their shift. */
typedef struct { int index; } port_worker_ctx;
void port_spawn_workers(int jobs,
                        void (*fn)(const port_worker_ctx *, void *shared),
                        void *shared);

#endif
