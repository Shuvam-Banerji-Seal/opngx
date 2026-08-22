/* libapi.c — thin C shim exposing opngx_job API with plain-C ABI stability
 * for ctypes bindings. All functions are already declared in opngx.h; this
 * file exists to keep the shared library's exported surface explicit and to
 * host any future ABI shims (struct-size guards etc.). */
#include "opngx.h"

/* Compile-time sanity: params struct layout version. Bump OPNGX_ABI_VERSION
 * in opngx.h whenever opngx_params changes so bindings can assert match. */
#ifndef OPNGX_ABI_VERSION
#define OPNGX_ABI_VERSION 1
#endif

int opngx_abi_version(void) { return OPNGX_ABI_VERSION; }
