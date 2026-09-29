"""ctypes bridge to the engine's analysis kernels (src/analysis.c, v2.0).

`available()` tells whether the loaded libopngx exports them (an older or
missing engine simply means the numpy implementations are used — results
are the same, gated by a parity test). Set OPNGX_ANALYSIS_BACKEND=python
to force numpy.
"""

from __future__ import annotations

import ctypes
import os
from typing import Optional

import numpy as np

_METHODS = {"circle": 0, "centroid": 1, "peak": 2}


class TrackParams(ctypes.Structure):
    """Mirror of C `opngx_track_params` (src/opngx.h). Keep in sync!"""

    _fields_ = [
        ("method", ctypes.c_int),
        ("window", ctypes.c_int),
        ("threshold", ctypes.c_double),
        ("min_pixels", ctypes.c_int),
        ("locate_block", ctypes.c_int),
        ("refine", ctypes.c_int),
        ("origin_x", ctypes.c_int),
        ("origin_y", ctypes.c_int),
    ]


_LIB = None
_TRIED = False


def _lib():
    global _LIB, _TRIED
    if _TRIED:
        return _LIB
    _TRIED = True
    if os.environ.get("OPNGX_ANALYSIS_BACKEND", "").lower() == "python":
        return None
    try:
        from opngx._engine import load_library

        lib = load_library()
    except Exception:  # noqa: BLE001
        lib = None
    if lib is None or not hasattr(lib, "opngx_track") or not hasattr(lib, "opngx_hist256"):
        return None
    P = ctypes.POINTER
    d = P(ctypes.c_double)
    lib.opngx_track.argtypes = [
        P(ctypes.c_uint8), ctypes.c_int64, ctypes.c_int, ctypes.c_int, P(TrackParams),
        d, d, d, d, d, P(ctypes.c_int8), d,
    ]
    lib.opngx_track.restype = ctypes.c_int
    lib.opngx_hist256.argtypes = [P(ctypes.c_uint8), ctypes.c_int64, ctypes.c_int64, P(ctypes.c_int64)]
    lib.opngx_hist256.restype = ctypes.c_int
    _LIB = lib
    return lib


def available() -> bool:
    return _lib() is not None


def reset() -> None:
    """Forget the cached decision (tests toggle the backend)."""
    global _LIB, _TRIED
    _LIB, _TRIED = None, False


def _ptr(a: np.ndarray, ctype):
    return a.ctypes.data_as(ctypes.POINTER(ctype))


def hist256(frames: np.ndarray) -> Optional[np.ndarray]:
    lib = _lib()
    if lib is None:
        return None
    f = np.ascontiguousarray(frames, dtype=np.uint8)
    k = len(f)
    out = np.empty((k, 256), dtype=np.int64)
    if k and lib.opngx_hist256(_ptr(f, ctypes.c_uint8), k, f[0].size, _ptr(out, ctypes.c_int64)) != 0:
        raise RuntimeError("opngx_hist256 failed")
    return out


def track(frames: np.ndarray, method: str, p: dict, origin=(0, 0)) -> Optional[dict]:
    """Native motion tracking on a (k, h, w) uint8 batch; None if unavailable.
    Returns window-frame coordinates like MotionTracking._measure()."""
    lib = _lib()
    if lib is None:
        return None
    f = np.ascontiguousarray(frames, dtype=np.uint8)
    if f.ndim != 3:
        raise ValueError("frames must be (k, h, w)")
    k, h, w = f.shape
    tp = TrackParams(
        _METHODS[method], int(p["window"]), float(p["threshold"]), int(p["min_pixels"]),
        int(p["locate_block"]), int(bool(p.get("refine", True))), int(origin[0]), int(origin[1]),
    )
    out = {n: np.empty(k, dtype=np.float64) for n in ("x", "y", "r", "peak", "area", "rms")}
    found = np.empty(k, dtype=np.int8)
    if k:
        rc = lib.opngx_track(
            _ptr(f, ctypes.c_uint8), k, h, w, ctypes.byref(tp),
            _ptr(out["x"], ctypes.c_double), _ptr(out["y"], ctypes.c_double),
            _ptr(out["r"], ctypes.c_double), _ptr(out["peak"], ctypes.c_double),
            _ptr(out["area"], ctypes.c_double), _ptr(found, ctypes.c_int8),
            _ptr(out["rms"], ctypes.c_double),
        )
        if rc != 0:
            raise RuntimeError(f"opngx_track failed (rc={rc})")
    out["found"] = found.astype(bool)
    return out
