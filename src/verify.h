/* verify.h — pixel-exact directory comparison */
#ifndef OPNGX_VERIFY_H
#define OPNGX_VERIFY_H
#include <stddef.h>
#include <stdint.h>
#include "opngx.h"

typedef struct {
    int64_t  files_ref;
    int64_t  files_out;
    int64_t  files_compared;
    uint64_t bytes_compared;      /* raw scanline bytes proven equal */
    int64_t  mismatched_files;
    int      set_equal;           /* name sets identical */
    char     first_error[512];
} verify_report;

void verify_report_init(verify_report *r);

/* Returns 0 = all equal, 1 = differences found, -1 = hard error (err filled). */
int opngx_verify(const char *ref_dir, const char *out_dir,
                 const char *prefix, const char *ext,
                 verify_report *rep, char *err, size_t err_cap);

/* ADD-7: verify an extracted directory directly against the source .bin.
 * Uses p->bin_path/footage_path/geometry/mode/transform/container fields
 * and p->out_dir/prefix/ext. Filenames encode absolute frame indices;
 * files outside the bin's range fail the subset claim.
 * Returns 0 = all equal, 1 = differences, -1 = hard error (err filled). */
int opngx_verify_bin(const opngx_params *p, verify_report *rep,
                     char *err, size_t err_cap);
#endif
