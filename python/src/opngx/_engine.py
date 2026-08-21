"""ctypes bindings to the native opngx engine (libopngx.so).

Discovery order:
    1. $OPNGX_ENGINE explicit path
    2. package-bundled copy
    3. repo build directory (../build relative to package)
    4. system library search path

If no native engine is found, callers should fall back to opngx._fallback.
"""

from __future__ import annotations

import ctypes
import os
import struct
from pathlib import Path
from typing import Optional

ABI_VERSION = 2

MODE_REFERENCE, MODE_RAW, MODE_CUSTOM = 0, 1, 2
BACKEND_AUTO, BACKEND_LIBDEFLATE, BACKEND_ZLIB = 0, 1, 2


class OpngxParams(ctypes.Structure):
    """Mirror of C `opngx_params` (src/opngx.h). Keep in sync!"""

    _fields_ = [
        ("bin_path", ctypes.c_char_p),
        ("footage_path", ctypes.c_char_p),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("num_frames", ctypes.c_int64),
        ("frame_stride", ctypes.c_int64),
        ("mode", ctypes.c_int),
        ("brightness", ctypes.c_double),
        ("contrast", ctypes.c_double),
        ("gamma", ctypes.c_double),
        ("bit_depth", ctypes.c_int),
        ("channels", ctypes.c_int),      # 6 = RGBA (default), 0 = gray
        ("out_dir", ctypes.c_char_p),
        ("prefix", ctypes.c_char_p),
        ("ext", ctypes.c_char_p),
        ("jobs", ctypes.c_int),
        ("level", ctypes.c_int),
        ("backend", ctypes.c_int),
        ("export_timestamps", ctypes.c_int),
        ("export_metadata", ctypes.c_int),
        ("verbose", ctypes.c_int),
    ]


class OpngxStats(ctypes.Structure):
    _fields_ = [
        ("frames_written", ctypes.c_int64),
        ("frames_total", ctypes.c_int64),
        ("bytes_written", ctypes.c_uint64),
        ("seconds", ctypes.c_double),
        ("mib_per_s_in", ctypes.c_double),
        ("frames_per_s", ctypes.c_double),
        ("backend_used", ctypes.c_char * 32),
    ]


class EngineError(RuntimeError):
    pass


def _candidates() -> list[Path]:
    env = os.environ.get("OPNGX_ENGINE")
    cands: list[Path] = []
    if env:
        cands.append(Path(env))
    here = Path(__file__).resolve().parent
    cands += [
        here / "_native" / "libopngx.so",
        here.parent.parent.parent / "build" / "libopngx.so",
        Path("/usr/local/lib/libopngx.so"),
        Path("/usr/lib/libopngx.so"),
    ]
    return cands


_lib = None
_lib_path: Optional[str] = None


def load_library() -> Optional[ctypes.CDLL]:
    """Return the loaded CDLL or None when unavailable."""
    global _lib, _lib_path
    if _lib is not None:
        return _lib
    for cand in _candidates():
        if cand.exists():
            try:
                lib = ctypes.CDLL(str(cand))
                _wire_prototypes(lib)
            except OSError:
                continue
            abi = lib.opngx_abi_version()
            if abi != ABI_VERSION:
                raise EngineError(
                    f"libopngx ABI {abi} != expected {ABI_VERSION} at {cand}"
                )
            _lib, _lib_path = lib, str(cand)
            return _lib
    return None


def library_path() -> Optional[str]:
    load_library()
    return _lib_path


def _wire_prototypes(lib: ctypes.CDLL) -> None:
    lib.opngx_version.restype = ctypes.c_char_p
    lib.opngx_abi_version.restype = ctypes.c_int
    lib.opngx_cpu_count.restype = ctypes.c_int
    lib.opngx_detect_gpus.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    lib.opngx_detect_gpus.restype = ctypes.c_int

    lib.opngx_job_create.argtypes = [
        ctypes.POINTER(OpngxParams),
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    lib.opngx_job_create.restype = ctypes.c_void_p
    lib.opngx_job_run.argtypes = [ctypes.c_void_p]
    lib.opngx_job_run.restype = ctypes.c_int
    lib.opngx_job_free.argtypes = [ctypes.c_void_p]
    lib.opngx_progress_done.argtypes = [ctypes.c_void_p]
    lib.opngx_progress_done.restype = ctypes.c_int64
    lib.opngx_progress_total.argtypes = [ctypes.c_void_p]
    lib.opngx_progress_total.restype = ctypes.c_int64
    lib.opngx_cancel.argtypes = [ctypes.c_void_p]
    lib.opngx_job_stats.argtypes = [ctypes.c_void_p]
    lib.opngx_job_stats.restype = ctypes.POINTER(OpngxStats)
    lib.opngx__set_range.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_int64]
    lib.opngx__set_range.restype = ctypes.c_int64


def version() -> str:
    lib = load_library()
    return lib.opngx_version().decode() if lib else "python-fallback"


def detect_gpus() -> list[str]:
    lib = load_library()
    if not lib:
        return []
    buf = ctypes.create_string_buffer(4096)
    n = lib.opngx_detect_gpus(buf, len(buf))
    if n <= 0:
        return []
    return [ln.strip() for ln in buf.value.decode().splitlines() if ln.strip()]
