# Contributing to opngx

Thanks for helping make Optronis footage extraction faster and more correct.

## Ground rules

1. **Correctness beats speed.** Every performance change must keep the test
   suite green — especially `tests/test_engine.sh` T-1 (pixel-exact vs an
   independently computed reference) and the real-data subset gate.
2. **No `-march=native` in shipped builds.** Portability across Intel/AMD/
   ARM64 is a hard requirement. Use runtime dispatch (GCC `target_clones`)
   or guarded intrinsics with a scalar fallback.
3. **Verify before asserting.** Claims in `docs/BENCHMARKS.md` must be
   reproducible from the commands shown.
4. **Keep ABI discipline.** Changing `opngx_params` requires bumping
   `OPNGX_ABI_VERSION` in `src/opngx.h` *and* updating the ctypes mirror in
   `python/src/opngx/_engine.py` in the same commit.

## Workflow

```bash
fork & clone
cmake -S . -B build && cmake --build build -j
pip install -e ./python[dev]
bash tests/test_engine.sh          # must print: 16 passed, 0 failed
python -m pytest python/tests -q   # must pass
```

Branches: `feat/<topic>` or `fix/<topic>`. Keep PRs focused; include before/after
benchmark numbers for perf changes (`bench` subcommand output).

## Commit style

`area: imperative summary` — e.g. `engine: add grayscale fast path`,
`verify: handle Paeth edge case`. Reference issues in the body.

## Reporting bugs

Include: engine version (`opngx-engine --version`), CPU/GPU info
(`opngx info`), a synthetic fixture reproducing the failure
(`tests/gen_fixture.py`) if possible, and full command lines.
Never attach proprietary footage you are not licensed to share.
