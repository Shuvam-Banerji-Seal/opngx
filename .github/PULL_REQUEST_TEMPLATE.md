<!-- Thank you for contributing! Checklist before opening the PR -->
## What

<!-- one paragraph -->

## Why

<!-- link issues; show the failing case fixed -->

## Verification

- [ ] `bash tests/test_engine.sh` → 16 passed, 0 failed
- [ ] `python -m pytest python/tests -q` → all pass
- [ ] No `-march=native`; portable build verified (`cmake -S . -B /tmp/pb && cmake --build /tmp/pb`)
- [ ] Perf changes include before/after `bench` numbers
- [ ] ABI change (if any): `OPNGX_ABI_VERSION` bumped + ctypes mirror updated in same commit

## Benchmarks (if perf-relevant)

```
before:
after:
```
