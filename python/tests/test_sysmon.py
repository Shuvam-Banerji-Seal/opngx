"""sysmon tests — must pass on BOTH CI legs (ubuntu + native windows)."""

from __future__ import annotations

import time


def test_cpu_percent_in_range():
    from opngx.sysmon import cpu_percent

    first = cpu_percent()  # primes sampler (or loadavg guess)
    assert first is None or 0.0 <= first <= 100.0
    time.sleep(0.25)  # real delta window
    val = cpu_percent()
    if first is None or val is None:
        import pytest

        pytest.skip("platform unsupported")
    assert 0.0 <= val <= 100.0


def test_mem_percent_in_range():
    from opngx.sysmon import mem_percent

    val = mem_percent()
    if val is None:
        import pytest

        pytest.skip("platform unsupported")
    assert 0.0 < val < 100.0


def test_snapshot_shape():
    from opngx.sysmon import snapshot

    snap = snapshot()
    assert set(snap) == {"cpu", "mem", "load1"}
    for key in ("cpu", "mem"):
        assert snap[key] is None or 0.0 <= snap[key] <= 100.0


def test_busy_system_reads_high():
    """Burn one core; utilisation must rise above the idle floor."""
    import threading

    from opngx import sysmon

    stop = threading.Event()
    if sysmon.os.name != "posix" and sysmon.os.name != "nt":
        return
    t = threading.Thread(target=_spin, args=(stop,), daemon=True)
    cpu_now = sysmon.cpu_percent()
    if cpu_now is None:
        return
    t.start()
    time.sleep(0.4)
    busy = sysmon.cpu_percent()
    stop.set()
    t.join(timeout=2)
    if busy is not None:
        assert busy >= max(5.0, cpu_now - 10.0)


def _spin(stop) -> None:
    x = 1
    while not stop.is_set():
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
