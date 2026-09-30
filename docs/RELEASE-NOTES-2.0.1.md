# opngx v2.0.1 — the complete v2 release: pip-installable Python package with the C engine inside

**Released:** 2026-09-30 · **ABI:** 5 (unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

v2.0.0 introduced analysis modules, motion tracking, Brownian/optical-trap
analysis, the four-workspace studio, themes, the editor and the in-app docs
(see the [v2.0.0 notes](https://github.com/Shuvam-Banerji-Seal/opngx/releases/tag/v2.0.0)
for all of it). It shipped only as Windows programs and a Linux CLI, though.
**v2.0.1 finishes the v2 release**: the Python package now ships as
platform wheels with the compiled C engine inside, plus an sdist. Every wheel
is install-tested in CI before it can be published.

Code, ABI, CLI, output tree and numbers are unchanged from 2.0.0.

---

## Python wheels with the engine inside

```bash
# Linux x86_64 (any distro with glibc ≥ 2.17)
pip install opngx-2.0.1-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
# Windows amd64
pip install opngx-2.0.1-py3-none-win_amd64.whl
# add the Qt studio (PySide6 + ffmpeg)
pip install "opngx-2.0.1-py3-none-win_amd64.whl[qt]"
```

Each wheel contains:
- the Python API (`opngx`, `opngx.analysis`);
- the `opngx` and `opngx-ui` commands;
- the bundled guides;
- the native library (`libopngx.so` / `libopngx.dll`), which the package loads automatically;
- the `opngx-engine` CLI, used by `opngx verify` for byte-level checks.

The wheels are `py3-none-<platform>`: the package is pure Python plus a
ctypes library, so **one wheel serves CPython 3.9 through 3.13+**.

- **Linux:** compiled with GCC 14 in the manylinux_2_28 container, with libdeflate linked in
  statically. (manylinux2014's GCC 10 can't compile the engine's AVX2/AVX-512 dispatch, which
  targets x86-64-v3/v4.) The C code needs no glibc symbol newer than 2.17, and
  `auditwheel repair` certifies the wheel as **manylinux2014**. CI installs and tests it inside
  CentOS 7 (glibc 2.17) on CPython 3.9 and 3.13. There, pip picks an older NumPy, because current
  NumPy releases no longer ship glibc-2.17 wheels.
- **Windows:** built with MinGW. libdeflate and the GCC/pthread runtime are linked
  statically, so the DLL imports only Windows system libraries (CI checks this).
- **sdist:** `opngx-2.0.1.tar.gz` installs on any platform. Extraction and analysis
  then use the numpy path: same pixels and numbers, only slower. You can also
  point it at a self-built engine with `OPNGX_ENGINE=/path/to/libopngx.so`.

```python
import opngx, opngx.analysis as oa
run = oa.analyze("recording.bin", ["motion_tracking", "brownian_motion"])
run["motion_tracking"].save("trajectory.csv")
```

## Packaging fixes

- **Metadata:**
  - the project now links to this repository (homepage, docs, changelog, issues);
  - it has a real PyPI README and an SPDX `MIT` licence with the licence file;
  - classifiers cover Python 3.9–3.13, Linux and Windows, physics and image processing.
- **Studio extra:** `opngx[qt]` now also installs `imageio-ffmpeg` and `pillow`,
  which video export and the studio need.
- **CI:** a new *Wheels* workflow runs on every push and every tag. It builds
  both wheels and the sdist, and installs each wheel into a fresh environment
  on CPython 3.9 and 3.13, with the venv not activated. It then checks that
  the bundled engine is the one that loads, and runs the analysis and core test
  suites against the installed package. The Linux wheel is also tested on
  current Ubuntu with the Qt extra.
- **Tests:** the CLI tests now find the `opngx` command of the interpreter
  running them, rather than whatever is on `PATH`. Before, they failed in a
  non-activated Windows venv even though the command worked.
- **Release title:** the release is now titled from the first heading of these notes.

## Verification

- pytest **86/86** (new AN-18 checks the package metadata and native staging).
- Engine suite **46/46**.
- Wheels install and pass the suites:
  - Linux: CPython 3.9 and 3.13;
  - Windows: CPython 3.13 under Wine locally, and 3.9/3.13 on real Windows in CI.
- Windows `.exe` selftests (ui / engine / batch / video / analysis) pass in CI.

## Assets

| File | What |
|---|---|
| `opngx-setup-v2.0.1.exe` | Windows installer: engine + Qt studio + ffmpeg + docs, Start-menu shortcuts, uninstaller |
| `opngx-studio-portable-v2.0.1.exe` | Windows studio, single file, no install |
| `opngx-engine-v2.0.1.exe` | Windows CLI engine only |
| `opngx-2.0.1-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | Python package + C engine, Linux x86_64 |
| `opngx-2.0.1-py3-none-win_amd64.whl` | Python package + C engine, Windows amd64 |
| `opngx-2.0.1.tar.gz` | Python sdist (numpy fallback) |
| `opngx-2.0.1-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.0.1_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
