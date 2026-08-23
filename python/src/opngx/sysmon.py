"""Cross-platform system monitoring — stdlib only, psutil never required.

Powers the studio's live CPU/RAM chips so users can *see* the machine
saturate during extraction/rendering.

  Linux   : /proc/stat + /proc/meminfo
  Windows : kernel32.GetSystemTimes + GlobalMemoryStatusEx (ctypes)
  others  : graceful None (UI shows an em-dash)
"""

from __future__ import annotations

import os
import time

_last_cpu_times: tuple[float, float] | None = None  # (idle, total)
_last_poll: float = 0.0
_last_value: float | None = None


def _cpu_times_linux() -> tuple[float, float] | None:
    try:
        with open("/proc/stat", "rb") as f:
            fields = f.readline().split()[1:]
        vals = [float(x) for x in fields]
    except (OSError, ValueError):
        return None
    # user nice system idle iowait irq softirq steal ...
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)
    total = sum(vals)
    return idle, total


def _cpu_times_windows() -> tuple[float, float] | None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        idle = wintypes.FILETIME()
        kern = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)
        ):
            return None
        to_s = lambda ft: (ft.dwHighDateTime << 32 | ft.dwLowDateTime) / 1e7  # noqa: E731
        idle_s = to_s(idle)
        # kernel time INCLUDES idle; total = kernel + user
        total_s = to_s(kern) + to_s(user)
        return idle_s, total_s
    except Exception:
        return None


def cpu_percent() -> float | None:
    """Overall CPU utilisation percent (0..100) since the previous call.

    First call primes the sampler and returns a best-effort value based on
    a short internal window; subsequent calls are near-instant deltas.
    """
    global _last_cpu_times, _last_poll, _last_value
    now = time.monotonic()

    if os.name == "nt":
        cur = _cpu_times_windows()
    elif os.path.exists("/proc/stat"):
        cur = _cpu_times_linux()
    else:
        return None
    if cur is None:
        return None

    if _last_cpu_times is None or now - _last_poll < 0.1:
        # prime or poll too soon — fall back to loadavg heuristic on POSIX
        try:
            load1 = os.getloadavg()[0]
            ncpu = os.cpu_count() or 1
            guess = max(0.0, min(100.0, load1 / ncpu * 100.0))
            return (
                _last_value
                if (_last_value is not None and now - _last_poll < 0.1)
                else guess
            )
        except (AttributeError, OSError):
            return _last_value

    idle_d = cur[0] - _last_cpu_times[0]
    total_d = cur[1] - _last_cpu_times[1]
    _last_cpu_times = cur
    _last_poll = now
    if total_d <= 0:
        return _last_value
    _last_value = max(0.0, min(100.0, (1.0 - idle_d / total_d) * 100.0))
    return _last_value


def mem_percent() -> float | None:
    """Used physical memory percent (0..100)."""
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
                ctypes.byref(stat)
            ):
                return float(stat.dwMemoryLoad)
        except Exception:
            return None
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k.strip()] = int(v.strip().split()[0])
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        if total > 0:
            return max(0.0, min(100.0, (total - avail) / total * 100.0))
    except (OSError, ValueError, IndexError):
        pass
    return None


def snapshot() -> dict[str, float | None]:
    """One-shot dict for UI chips: {'cpu': %, 'mem': %, 'load1': float|None}."""
    load1: float | None = None
    try:
        load1 = os.getloadavg()[0]
    except (AttributeError, OSError):
        pass
    return {"cpu": cpu_percent(), "mem": mem_percent(), "load1": load1}
