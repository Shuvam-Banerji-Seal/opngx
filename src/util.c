/* util.c — GPU reporting for the CLI/info surfaces.
 * Detection logic lives in port.c so every target gets it. */
#include "opngx.h"
#include "port.h"

int opngx_detect_gpus(char *buf, size_t cap) {
    return port_detect_gpus(buf, cap);
}
