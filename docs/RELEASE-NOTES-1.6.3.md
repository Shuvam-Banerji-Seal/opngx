# opngx v1.6.3 — Critical Hotfix: Batch/Single Extract Crash

**Developer:** Shuvam Banerji Seal

## Fixed (Critical Regression from 1.5.4–1.6.2)

### `UnboundLocalError` on every Extract click
All versions from 1.5.4 to 1.6.2 crashed immediately when clicking **Extract**
in both Single and Batch modes:

```
[13:37:33] ERROR: cannot access local variable 'o' where it is not associated with a value
```

**Root Cause:** In `qt_app.py:1700`, the v1.6 tree refactoring introduced:

```python
od = run_out_dir(out, b, o["fmt"])  # o used before assignment
o = opts
```

`o` was referenced one line *before* it was defined. Python 3.12+ raises
`UnboundLocalError` with the message above and aborts the worker thread.

**Fix:** `o = opts` now precedes `od = run_out_dir(...)`. The regression is
covered by the existing `AR-10` gate (duplicate/missing self-call detection)
and a new functional test that exercises the batch worker path without requiring a display.

*Reported on Windows 11 (i7-12700, 720p) with SQ_100_s1.bin — 1.5.3 was the last
good version. Verified fixed under Wine against the real Windows binary (27/27
engine gates).*

## Verification this release
- Linux 27/27 engine gates · Wine (real Windows binary) **27/27**
- 51/51 pytest (including AR-10, AR-15, audit regressions)
- Packaged selftests (UI / Engine / Video) green on the Windows runner
- Note: the exe is unsigned — Windows SmartScreen may ask for
  "More info → Run anyway" on first launch.
