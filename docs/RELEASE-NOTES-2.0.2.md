# opngx v2.0.2 — pure-Python verifier fix; the sdist is now tested like the wheels

**Released:** 2026-09-30 · **ABI:** 5 (unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

A fix release for the v2 Python package. The v2 feature set is described in
the [v2.0.0 notes](https://github.com/Shuvam-Banerji-Seal/opngx/releases/tag/v2.0.0).
The [v2.0.1 notes](https://github.com/Shuvam-Banerji-Seal/opngx/releases/tag/v2.0.1)
cover the pip-installable wheels with the C engine inside.

## Fixed: `opngx verify` without the engine reported false mismatches

Checking the released v2.0.1 assets from clean installs showed that
installing the **sdist** failed 3 tests. Extraction was not the problem: the
fallback output was **pixel-identical** to the reference, checked
independently with PIL, 200 of 200 frames. The problem was the pure-Python
**verifier**, which `opngx verify` / `opngx.verify()` use when the
`opngx-engine` CLI isn't available.

- **The bug:** its PNG decoder reconstructed the *Average* and *Paeth* row
  filters from the still-filtered left neighbour. PNG predicts from the
  already-reconstructed byte, a sequential dependency the vectorised code
  skipped. Reference PNGs that use those filters were therefore reported as
  mismatches: 30 of 200 in the test fixture.
- **Other problems fixed:**
  - bytes per pixel were assumed rather than read from the colour type;
  - a failed comparison left `first_error` empty.
- **Who was affected:** only installs without the engine CLI, meaning the sdist or a source
  checkout without a build. Wheels, the Windows installer and the portable studio
  bundle the engine, so they were never affected. The engine's own verifier is
  a separate implementation and was always right.

The decoder now un-filters Sub/Average/Paeth rows byte by byte and None/Up
rows vectorised. It supports grey, RGB, grey-alpha and RGBA at 8 and 16 bits,
and rejects anything else with a clear error.

## Tests and CI

- **New regression test:** every PNG filter type, including mixed per-row filters, for
  grey/RGB/RGBA at 8 bits and RGBA at 16 bits.
  - It checks that the decoded pixels match PIL.
  - It checks that identical images verify and a one-bit change is caught.
  - It runs the 200-frame fixture through the pure-Python path.
  - It fails on the v2.0.1 code at the first Average-filtered image.
- **The sdist is now install-tested in CI:** before release, it's installed into a clean
  environment, where the test asserts that no native library is present and runs the
  analysis and core suites on the numpy fallback. That is the path this bug hid on.
- `test_backend_reported_truthfully` now expects `python-fallback` when there is no engine. The
  report was correct; the test assumed a native build.

## Verification

- pytest **87/87** in the development environment. Engine suite **46/46**.
- CI installs and tests:
  - wheels on CPython 3.9 and 3.13 (Linux build image, CentOS 7 / glibc 2.17, Ubuntu with the
    Qt extra, and Windows);
  - the sdist on the numpy fallback.

## Assets

| File | What |
|---|---|
| `opngx-setup-v2.0.2.exe` | Windows installer: engine + Qt studio + ffmpeg + docs, Start-menu shortcuts, uninstaller |
| `opngx-studio-portable-v2.0.2.exe` | Windows studio, single file, no install |
| `opngx-engine-v2.0.2.exe` | Windows CLI engine only |
| `opngx-2.0.2-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | Python package + C engine, Linux x86_64 (glibc ≥ 2.17) |
| `opngx-2.0.2-py3-none-win_amd64.whl` | Python package + C engine, Windows amd64 |
| `opngx-2.0.2.tar.gz` | Python sdist (numpy fallback) |
| `opngx-2.0.2-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.0.2_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
